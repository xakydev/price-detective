"""Calendario de resúmenes: decide qué slot horario toca enviar."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

__all__ = ["RECOVERY_WINDOW", "TIMEZONE", "due_summary_slot"]

TIMEZONE = ZoneInfo("Europe/Madrid")
RECOVERY_WINDOW = timedelta(hours=2)


def due_summary_slot(
    now: datetime, hours: Sequence[int], last: datetime | None
) -> datetime | None:
    """Devuelve el slot de resumen pendiente, o None si no toca enviar.

    Un slot está pendiente si es el último con hora <= `now` (en Europe/Madrid),
    tiene como mucho 2 h de antigüedad y no coincide con `last`. Las
    comparaciones se hacen en UTC para no depender de la aritmética de reloj
    de pared en los cambios de horario.
    """
    if now.tzinfo is None:
        raise ValueError("now debe llevar zona horaria")
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
    if now_utc - slot_utc > RECOVERY_WINDOW:
        return None
    if last is not None and last.astimezone(UTC) >= slot_utc:
        return None
    return slot
