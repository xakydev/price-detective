"""Fuente Chollómetro: ofertas del JSON `data-vue3` de la página de búsqueda.

Política ante datos mal formados: solo cuentan los hilos que pasan el filtro de
identidad (vigentes y con modelo/capacidad reconocidos). Si uno de ellos está
roto (falta un campo, precio no numérico o no positivo), se descarta con un
`log.warning` y se siguen usando los demás. Si ninguno de ellos se puede
interpretar, o falta la estructura general de la página, la fuente entera
falla con `SourceParseError`. Los hilos que no son un móvil se ignoran aunque
estén incompletos.
"""

import json
import logging
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any

import httpx

from price_detective.errors import PriceDetectiveError, SourceParseError
from price_detective.matching import classify
from price_detective.models import Offer
from price_detective.sources import get

__all__ = ["SEARCH_URL", "ChollometroSource", "parse_offers"]

SEARCH_URL = "https://www.chollometro.com/search?q=iphone%2017&hide_expired=true"
_COMPONENT = "ThreadMainListItemNormalizer"

log = logging.getLogger(__name__)


class _ThreadCollector(HTMLParser):
    """Recoge el `props.thread` de cada bloque `ThreadMainListItemNormalizer`."""

    def __init__(self) -> None:
        super().__init__()
        self.threads: list[dict[str, Any]] = []
        self.articles = 0  # artículos de oferta presentes en el HTML
        self.payloads = 0  # atributos data-vue3 con JSON válido

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "article" and (dict(attrs).get("id") or "").startswith("thread_"):
            self.articles += 1
        for key, value in attrs:
            if key != "data-vue3" or not value:
                continue
            try:
                payload = json.loads(value)
            except json.JSONDecodeError:
                continue
            self.payloads += 1
            if isinstance(payload, dict) and payload.get("name") == _COMPONENT:
                props = payload.get("props")
                thread = props.get("thread") if isinstance(props, dict) else None
                if isinstance(thread, dict):
                    self.threads.append(thread)


def _ref(thread: dict[str, Any]) -> str:
    """Referencia de la oferta para los mensajes: su `threadId`, nunca el título."""
    thread_id = thread.get("threadId")
    return f"threadId {thread_id}" if thread_id is not None else "sin id"


def _to_offer(thread: dict[str, Any]) -> Offer | None:
    """Oferta del hilo; `None` si no es relevante, `SourceParseError` si está rota."""
    if thread.get("isExpired"):
        return None
    title = str(thread.get("title", ""))
    classified = classify(title)
    if classified is None or not thread.get("price"):
        return None
    model, storage_gb = classified
    merchant = thread.get("merchant") or {}
    if not isinstance(merchant, dict):
        raise SourceParseError(
            f"Chollómetro: `merchant` no es un objeto en {_ref(thread)}"
        )
    try:
        return Offer(
            source="chollometro",
            offer_id=f"chollometro:{thread['threadId']}",
            model=model,
            storage_gb=storage_gb,
            price_eur=Decimal(str(thread["price"])),
            title=title,
            store=str(merchant.get("merchantName") or "Chollómetro"),
            url=str(thread["shareableLink"]),
        )
    except KeyError as exc:
        raise SourceParseError(
            f"Chollómetro: falta el campo {exc} en {_ref(thread)}"
        ) from exc
    except (InvalidOperation, PriceDetectiveError) as exc:
        raise SourceParseError(
            f"Chollómetro: precio inválido {thread['price']!r} en {_ref(thread)}"
        ) from exc


def parse_offers(html: str) -> list[Offer]:
    """Extrae las ofertas válidas; `SourceParseError` si no hay bloques."""
    collector = _ThreadCollector()
    collector.feed(html)
    # Un listado vacío no trae artículos pero conserva otros bloques data-vue3
    # (paginación, etiquetas). Hay artículos sin bloque reconocible, o ningún
    # data-vue3, solo si la estructura de la página cambió.
    if not collector.threads and (collector.articles or not collector.payloads):
        raise SourceParseError(
            f"Chollómetro: no se encontró ningún bloque {_COMPONENT}"
        )
    offers: list[Offer] = []
    errors: list[SourceParseError] = []
    for thread in collector.threads:
        try:
            offer = _to_offer(thread)
        except SourceParseError as exc:
            log.warning("Chollómetro: se descarta una oferta: %s", exc)
            errors.append(exc)
            continue
        if offer is not None:
            offers.append(offer)
    if errors and not offers:
        raise SourceParseError(
            f"Chollómetro: ninguna oferta interpretable ({errors[0]})"
        ) from errors[0]
    return offers


class ChollometroSource:
    """Ofertas vigentes de iPhone 17 / 17 Pro 256 GB en Chollómetro."""

    name = "chollometro"

    def fetch(self, client: httpx.Client) -> list[Offer]:
        return parse_offers(get(client, SEARCH_URL))
