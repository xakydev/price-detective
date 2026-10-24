"""Calendario de resúmenes: decide qué slot horario toca enviar."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

__all__ = ["TIMEZONE", "due_summary_slot", "summary_slot_in_future"]

TIMEZONE = ZoneInfo("Europe/Madrid")


def summary_slot_in_future(last: datetime | None, now: datetime) -> bool:
    """Indica si el último slot enviado es posterior a `now` (reloj o datos rotos)."""
    return last is not None and last.astimezone(UTC) > now.astimezone(UTC)


def due_summary_slot(
    now: datetime, hours: Sequence[int], last: datetime | None
) -> datetime | None:
    """Devuelve el slot de resumen pendiente, o None si no toca enviar.

    Un slot está pendiente si es el último con hora <= `now` (en Europe/Madrid)
    y no coincide con `last`. Sigue vigente, sin límite de antigüedad, hasta
    que empieza el siguiente slot; si se salta uno entero, solo cuenta el más
    reciente. Un `last` posterior a `now` se ignora (se trata como `None`).
    Las comparaciones se hacen en UTC para no depender de la aritmética de reloj
    de pared en los cambios de horario.
    """
    if now.tzinfo is None:
        raise ValueError("now debe llevar zona horaria")
    if summary_slot_in_future(last, now):
        last = None
    local_now = now.astimezone(TIMEZONE)
    now_utc = now.astimezone(UTC)

    slots = [
        datetime(day.year, day.month, day.day, hour, tzinfo=TIMEZONE)
        for day in (local_now.date() - timedelta(days=1), local_now.date())
        for hour in hours
    ]
    reached = [slot for slot in slots if slot.astimezone(UTC) <= now_utc]
    if not reached:
        return None
    slot = max(reached, key=lambda s: s.astimezone(UTC))
    slot_utc = slot.astimezone(UTC)
    if last is not None and last.astimezone(UTC) >= slot_utc:
        return None
    return slot
