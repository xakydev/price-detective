"""Tests del entrypoint: argumentos, entorno, códigos de salida y log sin token."""

import logging
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from price_detective import __main__ as entrypoint
from price_detective.app import EXIT_CONFIG_ERROR, EXIT_OK, EXIT_UNEXPECTED
from price_detective.config import Settings

TOKEN = "123456:SECRET-TOKEN"


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    return {
        "TELEGRAM_BOT_TOKEN": TOKEN,
        "TELEGRAM_CHAT_ID": "42",
        "HISTORY_PATH": str(tmp_path / "data" / "history.json"),
        **extra,
    }


class _Spy:
    """Sustituye a `run` y recuerda con qué se le llamó."""

    def __init__(self, result: int = EXIT_OK) -> None:
        self.result = result
        self.calls: list[tuple[Settings, bool, Path, datetime]] = []

    def __call__(
        self,
        settings: Settings,
        client: httpx.Client,
        now: datetime,
        force_summary: bool,
        history_path: Path,
    ) -> int:
        assert isinstance(client, httpx.Client)
        self.calls.append((settings, force_summary, history_path, now))
        return self.result


class TestMain:
    def test_missing_token_exits_with_config_error_and_no_run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        spy = _Spy()
        monkeypatch.setattr(entrypoint, "run", spy)

        code = entrypoint.main([], {"TELEGRAM_CHAT_ID": "42"})

        assert code == EXIT_CONFIG_ERROR
        assert spy.calls == []
        assert "TELEGRAM_BOT_TOKEN" in caplog.text

    def test_force_summary_flag_is_passed_to_run(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        spy = _Spy()
        monkeypatch.setattr(entrypoint, "run", spy)

        code = entrypoint.main(["--force-summary"], _env(tmp_path))

        assert code == EXIT_OK
        assert spy.calls[0][1] is True

    def test_force_summary_defaults_to_false(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        spy = _Spy()
        monkeypatch.setattr(entrypoint, "run", spy)

        entrypoint.main([], _env(tmp_path))

        assert spy.calls[0][1] is False

    def test_history_path_comes_from_env_and_parent_is_created(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        spy = _Spy()
        monkeypatch.setattr(entrypoint, "run", spy)

        entrypoint.main([], _env(tmp_path))

        assert spy.calls[0][2] == tmp_path / "data" / "history.json"
        assert (tmp_path / "data").is_dir()

    def test_history_path_has_default_when_unset(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        spy = _Spy()
        monkeypatch.setattr(entrypoint, "run", spy)
        monkeypatch.chdir(tmp_path)
        env = _env(tmp_path)
        del env["HISTORY_PATH"]

        entrypoint.main([], env)

        assert spy.calls[0][2] == Path(entrypoint.DEFAULT_HISTORY_PATH)

    def test_now_is_timezone_aware(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        spy = _Spy()
        monkeypatch.setattr(entrypoint, "run", spy)

        entrypoint.main([], _env(tmp_path))

        assert spy.calls[0][3].tzinfo is not None

    def test_run_exit_code_is_propagated(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(entrypoint, "run", _Spy(result=5))

        assert entrypoint.main([], _env(tmp_path)) == 5

    def test_unexpected_exception_is_logged_without_token_and_exits_nonzero(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        def boom(*args: object, **kwargs: object) -> int:
            raise RuntimeError("fallo inesperado")

        monkeypatch.setattr(entrypoint, "run", boom)

        code = entrypoint.main([], _env(tmp_path))

        assert code == EXIT_UNEXPECTED
        assert "fallo inesperado" in caplog.text
        assert "Traceback" in caplog.text
        assert TOKEN not in caplog.text

    def test_httpx_logger_is_silenced_because_it_logs_urls_with_token(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(entrypoint, "run", _Spy())

        entrypoint.main([], _env(tmp_path))

        assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
