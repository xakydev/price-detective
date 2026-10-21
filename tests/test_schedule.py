"""Tests de la decisión de enviar el resumen (slots en Europe/Madrid)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from price_detective.schedule import due_summary_slot

MADRID = ZoneInfo("Europe/Madrid")
HOURS = (9, 21)


def madrid(y: int, mo: int, d: int, h: int, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=MADRID)


class TestDueSummarySlot:
    def test_just_after_slot_returns_slot(self) -> None:
        now = madrid(2026, 10, 17, 9, 5)

        assert due_summary_slot(now, HOURS, None) == madrid(2026, 10, 17, 9)

    def test_exactly_on_slot_returns_slot(self) -> None:
        now = madrid(2026, 10, 17, 21, 0)

        assert due_summary_slot(now, HOURS, None) == madrid(2026, 10, 17, 21)

    def test_midafternoon_with_slot_sent_returns_none(self) -> None:
        now = madrid(2026, 10, 17, 14)

        assert due_summary_slot(now, HOURS, madrid(2026, 10, 17, 9)) is None

    def test_already_sent_slot_returns_none(self) -> None:
        now = madrid(2026, 10, 17, 9, 30)
        last = madrid(2026, 10, 17, 9)

        assert due_summary_slot(now, HOURS, last) is None

    def test_previous_slot_sent_returns_new_slot(self) -> None:
        now = madrid(2026, 10, 17, 9, 5)
        last = madrid(2026, 10, 16, 21)

        assert due_summary_slot(now, HOURS, last) == madrid(2026, 10, 17, 9)

    @pytest.mark.parametrize(
        ("now", "hours", "expected"),
        [
            (madrid(2026, 10, 17, 10, 59), HOURS, madrid(2026, 10, 17, 9)),
            (madrid(2026, 10, 17, 11, 1), HOURS, madrid(2026, 10, 17, 9)),
            (madrid(2026, 10, 17, 13, 44), (9, 15, 21), madrid(2026, 10, 17, 9)),
            (madrid(2026, 10, 17, 20, 59), HOURS, madrid(2026, 10, 17, 9)),
        ],
    )
    def test_pending_slot_has_no_age_limit_until_next_slot(
        self, now: datetime, hours: tuple[int, ...], expected: datetime
    ) -> None:
        assert due_summary_slot(now, hours, None) == expected

    def test_skipped_slot_returns_only_most_recent(self) -> None:
        now = madrid(2026, 10, 17, 22)
        last = madrid(2026, 10, 17, 9)

        slot = due_summary_slot(now, (9, 15, 21), last)

        assert slot == madrid(2026, 10, 17, 21)

    def test_previous_evening_slot_pending_in_early_morning(self) -> None:
        now = madrid(2026, 10, 17, 2)
        last = madrid(2026, 10, 16, 9)

        assert due_summary_slot(now, HOURS, last) == madrid(2026, 10, 16, 21)

    def test_previous_evening_slot_sent_returns_none_in_early_morning(self) -> None:
        now = madrid(2026, 10, 17, 2)
        last = madrid(2026, 10, 16, 21)

        assert due_summary_slot(now, HOURS, last) is None

    def test_late_slot_pending_after_midnight(self) -> None:
        now = madrid(2026, 10, 17, 0, 30)

        assert due_summary_slot(now, (23,), None) == madrid(2026, 10, 16, 23)

    def test_utc_now_is_converted_to_madrid(self) -> None:
        now = datetime(2026, 10, 17, 7, 5, tzinfo=UTC)  # 09:05 CEST

        assert due_summary_slot(now, HOURS, None) == madrid(2026, 10, 17, 9)

    def test_naive_now_raises(self) -> None:
        with pytest.raises(ValueError, match="zona horaria"):
            due_summary_slot(datetime(2026, 10, 17, 9, 5), HOURS, None)

    def test_empty_hours_returns_none(self) -> None:
        assert due_summary_slot(madrid(2026, 10, 17, 9, 5), (), None) is None


class TestDaylightSaving:
    def test_before_autumn_change_slot_is_cest(self) -> None:
        slot = due_summary_slot(madrid(2026, 10, 24, 21, 30), HOURS, None)

        assert slot is not None
        assert slot.isoformat() == "2026-10-24T21:00:00+02:00"

    def test_after_autumn_change_slot_is_cet(self) -> None:
        slot = due_summary_slot(madrid(2026, 10, 25, 9, 5), HOURS, None)

        assert slot is not None
        assert slot.isoformat() == "2026-10-25T09:00:00+01:00"

    def test_evening_after_autumn_change_slot_is_cet(self) -> None:
        slot = due_summary_slot(madrid(2026, 10, 25, 21, 5), HOURS, None)

        assert slot is not None
        assert slot.isoformat() == "2026-10-25T21:00:00+01:00"

    def test_sent_before_change_does_not_block_next_morning(self) -> None:
        last = madrid(2026, 10, 24, 21)

        slot = due_summary_slot(madrid(2026, 10, 25, 9, 5), HOURS, last)

        assert slot == madrid(2026, 10, 25, 9)

    def test_ambiguous_hour_uses_first_occurrence_window(self) -> None:
        # 02:30 CEST (primera pasada de las 02:xx el día del cambio)
        now = datetime(2026, 10, 25, 2, 30, tzinfo=MADRID, fold=0)

        slot = due_summary_slot(now, (2,), None)

        assert slot is not None
        assert slot.isoformat() == "2026-10-25T02:00:00+02:00"

    def test_after_spring_change_slot_is_cest(self) -> None:
        slot = due_summary_slot(madrid(2026, 3, 29, 9, 5), HOURS, None)

        assert slot is not None
        assert slot.isoformat() == "2026-03-29T09:00:00+02:00"

    def test_morning_after_autumn_change_keeps_evening_slot_pending(self) -> None:
        # 21:00 CEST = 19:00 UTC; 08:59 CET = 07:59 UTC: sigue el de las 21.
        slot = due_summary_slot(madrid(2026, 10, 25, 8, 59), HOURS, None)

        assert slot == madrid(2026, 10, 24, 21)

    def test_morning_after_autumn_change_sent_slot_returns_none(self) -> None:
        last = madrid(2026, 10, 24, 21)

        assert due_summary_slot(madrid(2026, 10, 25, 8, 59), HOURS, last) is None
