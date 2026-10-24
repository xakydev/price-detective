"""Tests de `run`: la pasada completa con fuentes y Telegram simulados."""

import json
import logging
from collections.abc import Callable, Iterator
from datetime import datetime
from decimal import Decimal
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from conftest import ClientFactory

from price_detective.app import EXIT_NOTIFY_FAILED, EXIT_OK, run
from price_detective.config import Settings
from price_detective.history import History, KeyRecord
from price_detective.sources.chollometro import parse_offers

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
        chollometro_html: str | None = None,
    ) -> None:
        self._load = load_fixture
        self._chollometro_html = chollometro_html
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
        if name == "chollometro" and self._chollometro_html is not None:
            return httpx.Response(200, text=self._chollometro_html)
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


def _seed(path: Path, last_slot: datetime | None = None, **mins: str) -> None:
    """Histórico con mínimos para las claves dadas (`iphone_17` -> 17:256).

    `last_slot` es el último resumen enviado; con OFF_HOUR hace falta SLOT_9
    para que no haya un slot pendiente.
    """
    history = History()
    history.last_summary_slot = last_slot
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
        _seed(history_path, SLOT_9)

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
        _seed(history_path, SLOT_9, iphone_17="900.00")

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
        _seed(history_path, SLOT_9, iphone_17="900.00")

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
        _seed(history_path, SLOT_9, iphone_17="900.00")
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

    def test_forced_summary_off_hour_is_sent_without_changing_sent_slot(
        self,
        make_client: ClientFactory,
        world: FakeWorld,
        settings: Settings,
        history_path: Path,
    ) -> None:
        _seed(history_path, SLOT_9)

        code = run(settings, make_client(world), OFF_HOUR, True, history_path)

        assert code == EXIT_OK
        assert len(world.messages) == 1
        assert "Resumen" in world.messages[0]
        assert History.load(history_path).last_summary_slot == SLOT_9

    def test_late_cron_sends_pending_slot_and_registers_it(
        self,
        make_client: ClientFactory,
        world: FakeWorld,
        settings: Settings,
        history_path: Path,
    ) -> None:
        run(settings, make_client(world), OFF_HOUR, False, history_path)

        assert len(world.messages) == 1
        assert "Resumen" in world.messages[0]
        assert History.load(history_path).last_summary_slot == SLOT_9

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

    @pytest.mark.parametrize(
        "extra",
        [
            {"price": 850},
            {"price": "1.099,00", "shareableLink": "https://x.test/1"},
            {"price": -5, "shareableLink": "https://x.test/1"},
        ],
    )
    def test_chollometro_malformed_data_exits_zero_and_summary_reports_it(
        self,
        make_client: ClientFactory,
        load_fixture: Callable[[str], str],
        settings: Settings,
        history_path: Path,
        now: datetime,
        extra: dict[str, object],
    ) -> None:
        thread = {"threadId": 1, "title": "iPhone 17 256GB", **extra}
        payload = {
            "name": "ThreadMainListItemNormalizer",
            "props": {"thread": thread},
        }
        html = (
            f'<article id="thread_1"><div data-vue3="{escape(json.dumps(payload))}">'
            "</div></article>"
        )
        world = FakeWorld(load_fixture, chollometro_html=html)

        code = run(settings, make_client(world), now, False, history_path)

        assert code == EXIT_OK
        assert "Chollómetro: no disponible" in world.messages[0]
        assert "1.109,00 €" in world.messages[0]

    def test_chollometro_props_not_an_object_exits_zero_and_summary_reports_it(
        self,
        make_client: ClientFactory,
        load_fixture: Callable[[str], str],
        settings: Settings,
        history_path: Path,
        now: datetime,
    ) -> None:
        payload = {"name": "ThreadMainListItemNormalizer", "props": []}
        html = (
            f'<article id="thread_1"><div data-vue3="{escape(json.dumps(payload))}">'
            "</div></article>"
        )
        world = FakeWorld(load_fixture, chollometro_html=html)

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
        _seed(history_path, SLOT_9, iphone_17="900.00")
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
        _seed(history_path, SLOT_9, iphone_17="900.00")
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
        _seed(history_path, SLOT_9, iphone_17="900.00")
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


@pytest.fixture
def httpx_quiet() -> Iterator[None]:
    """Reproduce `__main__`: httpx en WARNING, pues su INFO lleva la URL con token."""
    logger = logging.getLogger("httpx")
    previous = logger.level
    logger.setLevel(logging.WARNING)
    yield
    logger.setLevel(previous)


def _broken_page(valid_title: str, broken_title: str) -> str:
    """Página con un hilo válido y otro roto (sin `shareableLink`)."""
    threads = [
        {
            "threadId": 1,
            "title": valid_title,
            "price": 850.0,
            "shareableLink": "https://x.test/1",
        },
        {"threadId": 2, "title": broken_title, "price": 850.0},
    ]
    blocks = []
    for index, thread in enumerate(threads):
        payload = {"name": "ThreadMainListItemNormalizer", "props": {"thread": thread}}
        blocks.append(
            f'<article id="thread_{index}">'
            f'<div data-vue3="{escape(json.dumps(payload))}"></div></article>'
        )
    return "<html><body>" + "".join(blocks) + "</body></html>"


def _assert_no_sensitive(
    caplog: pytest.LogCaptureFixture, forbidden: list[str]
) -> None:
    """Ni el texto formateado ni los argumentos de ningún registro filtran datos."""
    forbidden = [TOKEN, "SECRET-TOKEN", "api.telegram.org", *forbidden]
    assert caplog.records
    for record in caplog.records:
        haystack = " ".join([record.getMessage(), str(record.msg), str(record.args)])
        for secret in forbidden:
            assert secret not in haystack, (secret, haystack)
    for secret in forbidden:
        assert secret not in caplog.text


@pytest.mark.usefixtures("httpx_quiet")
class TestRunLogging:
    def test_run_logs_one_info_line_per_source_with_count(
        self,
        make_client: ClientFactory,
        world: FakeWorld,
        settings: Settings,
        history_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.INFO)

        run(settings, make_client(world), OFF_HOUR, False, history_path)

        messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
        assert any(m.startswith("Fuente chollometro: ") for m in messages)
        assert any(m.startswith("Fuente apple: ") for m in messages)
        assert any(m == "Alertas: 0" for m in messages)
        assert any(m.startswith("Resumen: slot=") for m in messages)
        assert "Histórico guardado" in messages

    def test_run_logs_source_with_zero_offers(
        self,
        make_client: ClientFactory,
        load_fixture: Callable[[str], str],
        settings: Settings,
        history_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.INFO)
        html = '<html><body><div data-vue3="{}"></div></body></html>'
        world = FakeWorld(load_fixture, chollometro_html=html)

        run(settings, make_client(world), OFF_HOUR, False, history_path)

        messages = [r.getMessage() for r in caplog.records]
        assert "Fuente chollometro: 0 ofertas" in messages

    def test_run_logs_alert_count_and_summary_decision(
        self,
        make_client: ClientFactory,
        world: FakeWorld,
        settings: Settings,
        history_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.INFO)
        _seed(history_path, SLOT_9, iphone_17="900.00")

        run(settings, make_client(world), OFF_HOUR, False, history_path)

        messages = [r.getMessage() for r in caplog.records]
        assert "Alertas: 1" in messages
        assert "Resumen: slot=ninguno forzado=False enviar=False" in messages

    def test_run_logs_unchanged_history(
        self,
        make_client: ClientFactory,
        world: FakeWorld,
        settings: Settings,
        history_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        run(settings, make_client(world), OFF_HOUR, False, history_path)
        caplog.clear()
        caplog.set_level(logging.INFO)

        run(settings, make_client(world), OFF_HOUR, False, history_path)

        messages = [r.getMessage() for r in caplog.records]
        assert "Histórico sin cambios; no se guarda" in messages


@pytest.mark.usefixtures("httpx_quiet")
class TestNoSensitiveLogging:
    def test_normal_run_logs_no_secrets_titles_or_messages(
        self,
        make_client: ClientFactory,
        world: FakeWorld,
        load_fixture: Callable[[str], str],
        settings: Settings,
        history_path: Path,
        now: datetime,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.DEBUG)
        titles = [
            o.title for o in parse_offers(load_fixture("chollometro_search.html"))
        ]
        _seed(history_path, None, iphone_17="900.00")

        run(settings, make_client(world), now, False, history_path)

        assert len(world.messages) == 2  # una alerta y el resumen
        _assert_no_sensitive(caplog, [*titles, "42", *world.messages])

    def test_send_failure_logs_no_secrets(
        self,
        make_client: ClientFactory,
        load_fixture: Callable[[str], str],
        settings: Settings,
        history_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.DEBUG)
        world = FakeWorld(load_fixture, telegram=500)
        titles = [
            o.title for o in parse_offers(load_fixture("chollometro_search.html"))
        ]
        _seed(history_path, SLOT_9, iphone_17="900.00")

        code = run(settings, make_client(world), OFF_HOUR, False, history_path)

        assert code == EXIT_NOTIFY_FAILED
        _assert_no_sensitive(caplog, [*titles, "42"])

    def test_discarded_offer_logs_thread_id_not_title(
        self,
        make_client: ClientFactory,
        load_fixture: Callable[[str], str],
        settings: Settings,
        history_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.DEBUG)
        html = _broken_page(
            "iPhone 17 256GB TITULOVALIDO", "iPhone 17 256GB TITULOROTO"
        )
        world = FakeWorld(load_fixture, chollometro_html=html)

        code = run(settings, make_client(world), OFF_HOUR, False, history_path)

        assert code == EXIT_OK
        assert any("se descarta" in r.getMessage() for r in caplog.records)
        _assert_no_sensitive(caplog, ["TITULOVALIDO", "TITULOROTO", "42"])
        assert any(
            "2" in r.getMessage()
            for r in caplog.records
            if "descarta" in r.getMessage()
        )

    def test_source_failure_after_discard_logs_no_title(
        self,
        make_client: ClientFactory,
        load_fixture: Callable[[str], str],
        settings: Settings,
        history_path: Path,
        now: datetime,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.DEBUG)
        thread = {"threadId": 7, "title": "iPhone 17 256GB TITULOROTO", "price": 850}
        payload = {"name": "ThreadMainListItemNormalizer", "props": {"thread": thread}}
        html = (
            f'<article id="thread_1"><div data-vue3="{escape(json.dumps(payload))}">'
            "</div></article>"
        )
        world = FakeWorld(load_fixture, chollometro_html=html)

        run(settings, make_client(world), now, False, history_path)

        _assert_no_sensitive(caplog, ["TITULOROTO", "42"])


class TestFutureSummarySlot:
    def test_future_last_slot_sends_summary_and_warns(
        self,
        make_client: ClientFactory,
        world: FakeWorld,
        settings: Settings,
        history_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.INFO)
        _seed(history_path, datetime(2099, 1, 1, 9, 0, tzinfo=MADRID))

        run(settings, make_client(world), OFF_HOUR, False, history_path)

        assert len(world.messages) == 1
        assert "Resumen" in world.messages[0]
        assert History.load(history_path).last_summary_slot == SLOT_9
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("es posterior a ahora" in r.getMessage() for r in warnings)

    def test_current_last_slot_sends_nothing_and_does_not_warn(
        self,
        make_client: ClientFactory,
        world: FakeWorld,
        settings: Settings,
        history_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        caplog.set_level(logging.INFO)
        _seed(history_path, SLOT_9)

        run(settings, make_client(world), OFF_HOUR, False, history_path)

        assert world.messages == []
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
