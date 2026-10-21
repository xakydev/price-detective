"""Tests del histórico de ofertas vistas y mínimos."""

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from price_detective.errors import HistoryError
from price_detective.history import History, detect_drops, offer_key
from price_detective.models import Offer, PhoneModel


def make_offer(
    offer_id: str = "a",
    price: str = "900.00",
    model: PhoneModel = PhoneModel.IPHONE_17,
) -> Offer:
    return Offer(
        source="chollometro",
        offer_id=offer_id,
        model=model,
        storage_gb=256,
        price_eur=Decimal(price),
        title="iPhone 256GB",
        store="Tienda",
        url="https://example.com/x",
    )


def seeded_history() -> History:
    history = History()
    detect_drops(history, [make_offer("base", "900.00")])
    history.changed = False
    return history


class TestPersistence:
    def test_save_load_roundtrip_is_identical(self, tmp_path: Path) -> None:
        history = History()
        detect_drops(
            history,
            [
                make_offer("a", "900.00"),
                make_offer("b", "1100.00", PhoneModel.IPHONE_17_PRO),
            ],
        )
        history.last_summary_slot = datetime(
            2026, 10, 17, 9, 0, tzinfo=ZoneInfo("Europe/Madrid")
        )
        path = tmp_path / "history.json"

        history.save(path)

        assert History.load(path) == history

    def test_to_json_uses_documented_format(self) -> None:
        history = History()
        detect_drops(history, [make_offer("a", "899.00")])
        history.last_summary_slot = datetime(
            2026, 10, 17, 9, 0, tzinfo=ZoneInfo("Europe/Madrid")
        )

        data = json.loads(history.to_json())

        assert data == {
            "schema_version": 1,
            "keys": {"iphone-17:256": {"min_price": "899.00", "seen_ids": ["a"]}},
            "last_summary_slot": "2026-10-17T09:00:00+02:00",
        }

    def test_load_missing_file_returns_empty_history(self, tmp_path: Path) -> None:
        history = History.load(tmp_path / "nope.json")

        assert history.keys == {}
        assert history.last_summary_slot is None
        assert history.is_empty

    def test_load_corrupt_file_raises_and_keeps_file(self, tmp_path: Path) -> None:
        path = tmp_path / "history.json"
        path.write_text("{no es json", encoding="utf-8")

        with pytest.raises(HistoryError, match="history.json"):
            History.load(path)

        assert path.read_text(encoding="utf-8") == "{no es json"

    @pytest.mark.parametrize(
        "content",
        [
            "[]",
            '{"schema_version": 2, "keys": {}}',
            '{"schema_version": 1, "keys": {"iphone-17:256": {"min_price": "x"}}}',
            '{"schema_version": 1, "keys": [], "last_summary_slot": null}',
        ],
    )
    def test_from_json_invalid_structure_raises(self, content: str) -> None:
        with pytest.raises(HistoryError):
            History.from_json(content)

    def test_save_leaves_no_temporary_files(self, tmp_path: Path) -> None:
        History().save(tmp_path / "history.json")

        assert [p.name for p in tmp_path.iterdir()] == ["history.json"]

    def test_seen_ids_trimmed_to_last_500(self) -> None:
        history = History()
        detect_drops(history, [make_offer("base", "900.00")])
        for i in range(600):
            detect_drops(history, [make_offer(f"id{i}", "950.00")])

        seen = history.keys["iphone-17:256"].seen_ids

        assert len(seen) == 500
        assert seen[-1] == "id599"
        assert "base" not in seen


class TestDetectDrops:
    def test_cheaper_new_offer_is_drop_and_lowers_minimum(self) -> None:
        history = seeded_history()

        drops = detect_drops(history, [make_offer("new", "850.00")])

        assert [o.offer_id for o in drops] == ["new"]
        assert history.keys["iphone-17:256"].min_price == Decimal("850.00")

    @pytest.mark.parametrize("prices", [("880.00", "850.00"), ("850.00", "880.00")])
    def test_several_new_offers_of_same_key_give_one_drop_the_cheapest(
        self, prices: tuple[str, str]
    ) -> None:
        history = seeded_history()
        offers = [make_offer(f"o{price}", price) for price in prices]

        drops = detect_drops(history, offers)

        assert [o.offer_id for o in drops] == ["o850.00"]
        record = history.keys["iphone-17:256"]
        assert record.min_price == Decimal("850.00")
        assert {"o880.00", "o850.00"} <= set(record.seen_ids)

    def test_seen_offer_is_not_drop(self) -> None:
        history = seeded_history()
        detect_drops(history, [make_offer("new", "850.00")])
        history.changed = False

        drops = detect_drops(history, [make_offer("new", "850.00")])

        assert drops == []

    def test_seen_id_at_lower_price_is_not_drop(self) -> None:
        history = seeded_history()

        drops = detect_drops(history, [make_offer("base", "700.00")])

        assert drops == []

    @pytest.mark.parametrize("price", ["900.00", "950.00"])
    def test_equal_or_higher_price_is_not_drop_but_seen(self, price: str) -> None:
        history = seeded_history()

        drops = detect_drops(history, [make_offer("new", price)])

        assert drops == []
        assert "new" in history.keys["iphone-17:256"].seen_ids
        assert history.keys["iphone-17:256"].min_price == Decimal("900.00")

    def test_models_are_independent(self) -> None:
        history = History()
        detect_drops(
            history,
            [
                make_offer("a", "900.00"),
                make_offer("b", "1100.00", PhoneModel.IPHONE_17_PRO),
            ],
        )

        drops = detect_drops(
            history, [make_offer("c", "1000.00", PhoneModel.IPHONE_17_PRO)]
        )

        assert [o.offer_id for o in drops] == ["c"]
        assert history.keys["iphone-17:256"].min_price == Decimal("900.00")
        assert history.keys["iphone-17-pro:256"].min_price == Decimal("1000.00")


class TestBaseline:
    def test_empty_history_sets_baseline_without_alerts(self) -> None:
        history = History()
        offers = [
            make_offer("a", "900.00"),
            make_offer("b", "850.00"),
            make_offer("c", "1100.00", PhoneModel.IPHONE_17_PRO),
        ]

        drops = detect_drops(history, offers)

        assert drops == []
        assert history.keys["iphone-17:256"].min_price == Decimal("850.00")
        assert history.keys["iphone-17:256"].seen_ids == ["a", "b"]
        assert history.keys["iphone-17-pro:256"].min_price == Decimal("1100.00")

    def test_key_without_minimum_sets_baseline_without_alert(self) -> None:
        history = seeded_history()

        drops = detect_drops(
            history, [make_offer("p", "1000.00", PhoneModel.IPHONE_17_PRO)]
        )

        assert drops == []
        assert history.keys["iphone-17-pro:256"].min_price == Decimal("1000.00")


class TestChanged:
    def test_known_offers_report_no_change(self) -> None:
        history = seeded_history()

        detect_drops(history, [make_offer("base", "900.00")])

        assert history.changed is False

    def test_new_offer_reports_change(self) -> None:
        history = seeded_history()

        detect_drops(history, [make_offer("new", "950.00")])

        assert history.changed is True

    def test_load_starts_unchanged(self, tmp_path: Path) -> None:
        path = tmp_path / "history.json"
        seeded_history().save(path)

        assert History.load(path).changed is False

    def test_mark_summary_sent_reports_change(self) -> None:
        history = seeded_history()
        slot = datetime(2026, 10, 17, 9, 0, tzinfo=ZoneInfo("Europe/Madrid"))

        history.mark_summary_sent(slot)

        assert history.last_summary_slot == slot
        assert history.changed is True


class TestOfferKey:
    def test_offer_key_combines_model_and_storage(self) -> None:
        offer = make_offer(model=PhoneModel.IPHONE_17_PRO)

        assert offer_key(offer) == "iphone-17-pro:256"

    def test_offer_key_matches_history_keys(self) -> None:
        history = History()
        offer = make_offer()

        detect_drops(history, [offer])

        assert offer_key(offer) in history.keys
