"""Orquestación de una pasada: consultar, detectar bajadas, notificar y guardar."""

import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import httpx

from price_detective.config import Settings
from price_detective.errors import HistoryError, NotifyError, SourceError
from price_detective.history import History, detect_drops, offer_key
from price_detective.models import SourceResult
from price_detective.report import compose_alert, compose_summary
from price_detective.schedule import due_summary_slot, summary_slot_in_future
from price_detective.sources import PriceSource
from price_detective.sources.apple import AppleSource
from price_detective.sources.chollometro import ChollometroSource
from price_detective.telegram import TelegramNotifier

__all__ = [
    "EXIT_ALL_SOURCES_FAILED",
    "EXIT_CONFIG_ERROR",
    "EXIT_HISTORY_ERROR",
    "EXIT_NOTIFY_FAILED",
    "EXIT_OK",
    "EXIT_UNEXPECTED",
    "run",
]

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_CONFIG_ERROR = 2
EXIT_ALL_SOURCES_FAILED = 3
EXIT_HISTORY_ERROR = 4
EXIT_NOTIFY_FAILED = 5

# Solo Chollómetro alimenta el histórico y las alertas; Apple es la referencia
# de precio que aparece en el resumen.
_ALERT_SOURCE = "chollometro"


def _fetch(source: PriceSource, client: httpx.Client) -> SourceResult:
    """Consulta una fuente aislando su fallo; solo captura `SourceError`."""
    try:
        offers = tuple(source.fetch(client))
    except SourceError as exc:
        log.warning("La fuente %s ha fallado: %s", source.name, exc)
        return SourceResult(source=source.name, error=str(exc))
    log.info("Fuente %s: %d ofertas", source.name, len(offers))
    return SourceResult(source=source.name, offers=offers)


def run(
    settings: Settings,
    client: httpx.Client,
    now: datetime,
    force_summary: bool,
    history_path: Path,
) -> int:
    """Ejecuta una pasada y devuelve el código de salida (`EXIT_*`).

    El histórico se guarda solo después de notificar con éxito: si Telegram
    falla no se marca nada como visto y la siguiente ejecución repite la alerta.
    """
    sources: list[PriceSource] = [
        ChollometroSource(),
        AppleSource(settings.reference_prices),
    ]
    results = [_fetch(source, client) for source in sources]
    if not any(result.ok for result in results):
        log.error("Todas las fuentes han fallado; no se toca el histórico")
        return EXIT_ALL_SOURCES_FAILED

    try:
        history = History.load(history_path)
    except HistoryError as exc:
        log.error("%s", exc)
        return EXIT_HISTORY_ERROR

    alert_offers = [
        offer
        for result in results
        if result.source == _ALERT_SOURCE
        for offer in result.offers
    ]
    # `detect_drops` actualiza el mínimo en el mismo paso: se captura antes.
    previous_mins: dict[str, Decimal] = {
        key: record.min_price for key, record in history.keys.items()
    }
    drops = detect_drops(history, alert_offers)
    log.info("Alertas: %d", len(drops))

    # Con `force_summary` se registra el slot pendiente, si lo hay, para que el
    # resumen programado de ese slot no se duplique; si no hay ninguno, el
    # resumen forzado no registra slot.
    if summary_slot_in_future(history.last_summary_slot, now):
        log.warning(
            "last_summary_slot %s es posterior a ahora; se ignora",
            history.last_summary_slot,
        )
    slot = due_summary_slot(now, settings.summary_hours, history.last_summary_slot)
    send_summary = force_summary or slot is not None
    log.info(
        "Resumen: slot=%s forzado=%s enviar=%s",
        slot.isoformat() if slot is not None else "ninguno",
        force_summary,
        send_summary,
    )

    notifier = TelegramNotifier(client, settings)
    try:
        for offer in drops:
            notifier.send(compose_alert(offer, previous_mins[offer_key(offer)]))
        if send_summary:
            notifier.send(compose_summary(results))
    except NotifyError as exc:
        log.error("No se pudo notificar; el histórico no se guarda: %s", exc)
        return EXIT_NOTIFY_FAILED

    if send_summary and slot is not None:
        history.mark_summary_sent(slot)
    if history.changed:
        try:
            history.save(history_path)
        except HistoryError as exc:
            log.error("%s", exc)
            return EXIT_HISTORY_ERROR
        log.info("Histórico guardado")
    else:
        log.info("Histórico sin cambios; no se guarda")
    return EXIT_OK
