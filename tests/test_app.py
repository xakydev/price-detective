"""Tests de `run`: la pasada completa con fuentes y Telegram simulados."""

import json
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from conftest import ClientFactory

from price_detective.app import EXIT_NOTIFY_FAILED, EXIT_OK, run
from price_detective.config import Settings
from price_detective.history import History, KeyRecord

TOKEN = "123456:SECRET-TOKEN"
MADRID = ZoneInfo("Europe/Madrid")
OFF_HOUR = datetime(2026, 10, 17, 14, 0, tzinfo=MADRID)
SLOT_9 = datetime(2026, 10, 17, 9, 0, tzinfo=MADRID)


class FakeWorld:
    """Enruta Chollómetro, Apple y Telegram por URL y registra los mensajes."""

    def __init__(
        self,
        load_fixture: Callable[[str], str],
        *,
        chollometro: int = 200,
        apple: int = 200,
        telegram: int = 200,
    ) -> None:
        self._load = load_fixture
        self.status = {
            "chollometro": chollometro,
            "apple": apple,
            "telegram": telegram,
        }
        self.messages: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "api.telegram.org":
            if self.status["telegram"] != 200:
                return httpx.Response(self.status["telegram"], json={"ok": False})
            self.messages.append(json.loads(request.content)["text"])
            return httpx.Response(200, json={"ok": True})
        name = "chollometro" if "chollometro" in host else "apple"
        if self.status[name] != 200:
            return httpx.Response(self.status[name], text="error")
        fixture = (
            "chollometro_search.html"
            if name == "chollometro"
            else "apple_es_iphone.html"
        )
        return httpx.Response(200, text=self._load(fixture))


@pytest.fixture
def settings() -> Settings:
    return Settings(telegram_token=TOKEN, telegram_chat_id="42", summary_hours=(9, 21))


@pytest.fixture
def world(load_fixture: Callable[[str], str]) -> FakeWorld:
    return FakeWorld(load_fixture)


def _seed(path: Path, **mins: str) -> None:
    """Histórico con mínimos para las claves dadas (`iphone_17` -> 17:256)."""
    history = History()
    for name, price in mins.items():
        key = name.replace("_pro", "-pro").replace("iphone_17", "iphone-17") + ":256"
        history.keys[key] = KeyRecord(Decimal(price), ["old"])
    history.save(path)


class TestNormalRun:
    def test_normal_run_exits_zero_and_persists(
        self,
        make_client: ClientFactory,
        world: FakeWorld,
        settings: Settings,
        history_path: Path,
    ) -> None:
        code = run(settings, make_client(world), OFF_HOUR, False, history_path)

        assert code == EXIT_OK
        assert History.load(history_path).keys

    def test_baseline_run_sends_nothing_and_populates_history(
        self,
        make_client: ClientFactory,
        world: FakeWorld,
        settings: Settings,
        history_path: Path,
    ) -> None:
        run(settings, make_client(world), OFF_HOUR, False, history_path)

        assert world.messages == []
        keys = History.load(history_path).keys
        assert keys["iphone-17:256"].min_price == Decimal("879.0")
        assert keys["iphone-17-pro:256"].min_price == Decimal("1092.1")

    def test_apple_offers_never_enter_history(
        self,
        make_client: ClientFactory,
        world: FakeWorld,
        settings: Settings,
        history_path: Path,
    ) -> None:
        run(settings, make_client(world), OFF_HOUR, False, history_path)

        seen = [i for r in History.load(history_path).keys.values() for i in r.seen_ids]
        assert seen and not any(i.startswith("apple:") for i in seen)

    def test_unchanged_history_is_not_rewritten(
        self,
        make_client: ClientFactory,
        world: FakeWorld,
        settings: Settings,
        history_path: Path,
    ) -> None:
        run(settings, make_client(world), OFF_HOUR, False, history_path)
        history_path.chmod(0o444)
        history_path.parent.chmod(0o555)
        try:
            code = run(settings, make_client(world), OFF_HOUR, False, history_path)
        finally:
            history_path.parent.chmod(0o755)

        # Si intentara guardar, fallaría por falta de permisos de escritura.
        assert code == EXIT_OK


class TestAlerts:
    def test_drop_off_summary_hour_sends_alert_only(
        self,
        make_client: ClientFactory,
        world: FakeWorld,
        settings: Settings,
        history_path: Path,
    ) -> None:
        _seed(history_path, iphone_17="900.00")

        run(settings, make_client(world), OFF_HOUR, False, history_path)

        assert len(world.messages) == 1
        assert "Bajada de precio" in world.messages[0]
        assert "Resumen" not in world.messages[0]

    def test_alert_shows_previous_min_not_updated_one(
        self,
        make_client: ClientFactory,
        world: FakeWorld,
        settings: Settings,
        history_path: Path,
    ) -> None:
        _seed(history_path, iphone_17="900.00")

        run(settings, make_client(world), OFF_HOUR, False, history_path)

        assert "Mínimo anterior: 900,00 €" in world.messages[0]
        assert History.load(history_path).keys["iphone-17:256"].min_price == Decimal(
            "879.0"
        )

    def test_second_run_does_not_repeat_alert(
        self,
        make_client: ClientFactory,
        world: FakeWorld,
        settings: Settings,
        history_path: Path,
    ) -> None:
        _seed(history_path, iphone_17="900.00")
        run(settings, make_client(world), OFF_HOUR, False, history_path)
        world.messages.clear()

        run(settings, make_client(world), OFF_HOUR, False, history_path)

        assert world.messages == []


class TestSummary:
    def test_summary_sent_in_slot_and_slot_registered(
        self,
        make_client: ClientFactory,
        world: FakeWorld,
        settings: Settings,
        history_path: Path,
        now: datetime,
    ) -> None:
        run(settings, make_client(world), now, False, history_path)

        assert len(world.messages) == 1
        assert "Resumen" in world.messages[0]
        assert History.load(history_path).last_summary_slot == SLOT_9

    def test_summary_not_repeated_in_same_slot(
        self,
        make_client: ClientFactory,
        world: FakeWorld,
        settings: Settings,
        history_path: Path,
        now: datetime,
    ) -> None:
        run(settings, make_client(world), now, False, history_path)
        world.messages.clear()

        run(settings, make_client(world), now, False, history_path)

        assert world.messages == []

    def test_forced_summary_off_hour_is_sent_without_registering_slot(
        self,
        make_client: ClientFactory,
        world: FakeWorld,
        settings: Settings,
        history_path: Path,
    ) -> None:
        code = run(settings, make_client(world), OFF_HOUR, True, history_path)

        assert code == EXIT_OK
        assert len(world.messages) == 1
        assert "Resumen" in world.messages[0]
        assert History.load(history_path).last_summary_slot is None

    def test_forced_summary_in_due_slot_registers_that_slot(
        self,
        make_client: ClientFactory,
        world: FakeWorld,
        settings: Settings,
        history_path: Path,
        now: datetime,
    ) -> None:
        run(settings, make_client(world), now, True, history_path)
        world.messages.clear()

        run(settings, make_client(world), now, False, history_path)

        assert world.messages == []
        assert History.load(history_path).last_summary_slot == SLOT_9

    def test_forced_summary_resends_in_already_sent_slot(
        self,
        make_client: ClientFactory,
        world: FakeWorld,
        settings: Settings,
        history_path: Path,
        now: datetime,
    ) -> None:
        run(settings, make_client(world), now, False, history_path)
        world.messages.clear()

        run(settings, make_client(world), now, True, history_path)

        assert len(world.messages) == 1


class TestSourceFailures:
    def test_chollometro_down_exits_zero_and_summary_reports_it(
        self,
        make_client: ClientFactory,
        load_fixture: Callable[[str], str],
        settings: Settings,
        history_path: Path,
        now: datetime,
    ) -> None:
        world = FakeWorld(load_fixture, chollometro=503)

        code = run(settings, make_client(world), now, False, history_path)

        assert code == EXIT_OK
        assert "Chollómetro: no disponible" in world.messages[0]
        assert "1.109,00 €" in world.messages[0]

    def test_apple_down_still_processes_chollometro(
        self,
        make_client: ClientFactory,
        load_fixture: Callable[[str], str],
        settings: Settings,
        history_path: Path,
    ) -> None:
        world = FakeWorld(load_fixture, apple=503)

        code = run(settings, make_client(world), OFF_HOUR, False, history_path)

        assert code == EXIT_OK
        assert History.load(history_path).keys

    def test_both_down_exits_nonzero_and_leaves_history_untouched(
        self,
        make_client: ClientFactory,
        load_fixture: Callable[[str], str],
        settings: Settings,
        history_path: Path,
        now: datetime,
    ) -> None:
        world = FakeWorld(load_fixture, chollometro=503, apple=503)
        _seed(history_path, iphone_17="900.00")
        before = history_path.read_text(encoding="utf-8")

        code = run(settings, make_client(world), now, True, history_path)

        assert code != EXIT_OK
        assert history_path.read_text(encoding="utf-8") == before
        assert world.messages == []

    def test_unexpected_exception_in_source_is_not_swallowed(
        self,
        make_client: ClientFactory,
        settings: Settings,
        history_path: Path,
    ) -> None:
        def boom(request: httpx.Request) -> httpx.Response:
            raise RuntimeError("bug")

        with pytest.raises(RuntimeError, match="bug"):
            run(settings, make_client(boom), OFF_HOUR, False, history_path)


class TestNotifyFailure:
    def test_telegram_500_exits_nonzero_and_does_not_mark_seen(
        self,
        make_client: ClientFactory,
        load_fixture: Callable[[str], str],
        settings: Settings,
        history_path: Path,
    ) -> None:
        world = FakeWorld(load_fixture, telegram=500)
        _seed(history_path, iphone_17="900.00")
        before = history_path.read_text(encoding="utf-8")

        code = run(settings, make_client(world), OFF_HOUR, False, history_path)

        assert code == EXIT_NOTIFY_FAILED
        assert history_path.read_text(encoding="utf-8") == before

    def test_alert_is_repeated_on_next_run_after_failure(
        self,
        make_client: ClientFactory,
        load_fixture: Callable[[str], str],
        settings: Settings,
        history_path: Path,
    ) -> None:
        _seed(history_path, iphone_17="900.00")
        run(
            settings,
            make_client(FakeWorld(load_fixture, telegram=500)),
            OFF_HOUR,
            False,
            history_path,
        )
        world = FakeWorld(load_fixture)

        run(settings, make_client(world), OFF_HOUR, False, history_path)

        assert "Mínimo anterior: 900,00 €" in world.messages[0]

    def test_summary_failure_does_not_register_slot(
        self,
        make_client: ClientFactory,
        load_fixture: Callable[[str], str],
        settings: Settings,
        history_path: Path,
        now: datetime,
    ) -> None:
        world = FakeWorld(load_fixture, telegram=500)

        code = run(settings, make_client(world), now, False, history_path)

        assert code == EXIT_NOTIFY_FAILED
        assert not history_path.exists()


class TestCorruptHistory:
    def test_corrupt_history_exits_nonzero_without_overwriting(
        self,
        make_client: ClientFactory,
        world: FakeWorld,
        settings: Settings,
        history_path: Path,
        now: datetime,
    ) -> None:
        history_path.write_text("{not json", encoding="utf-8")

        code = run(settings, make_client(world), now, False, history_path)

        assert code != EXIT_OK
        assert history_path.read_text(encoding="utf-8") == "{not json"
        assert world.messages == []
