"""Tests del envío por Telegram sobre `httpx.MockTransport`."""

import json
from typing import Any

import httpx
import pytest

from price_detective.config import Settings
from price_detective.errors import NotifyError
from price_detective.telegram import MAX_MESSAGE_LEN, TelegramNotifier, split_text
from tests.conftest import ClientFactory

TOKEN = "123456:SENTINEL-token_XYZ"


def _settings() -> Settings:
    return Settings(
        telegram_token=TOKEN, telegram_chat_id="-1001", summary_hours=(9, 21)
    )


class TestSend:
    def test_send_posts_chat_and_text(self, make_client: ClientFactory) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"ok": True})

        TelegramNotifier(make_client(handler), _settings()).send("hola <b>x</b>")

        assert len(seen) == 1
        assert seen[0].method == "POST"
        assert seen[0].url.path == f"/bot{TOKEN}/sendMessage"
        assert seen[0].url.host == "api.telegram.org"
        body: dict[str, Any] = json.loads(seen[0].content)
        assert body["chat_id"] == "-1001"
        assert body["text"] == "hola <b>x</b>"
        assert body["parse_mode"] == "HTML"

    @pytest.mark.parametrize("status", [401, 400, 500, 503])
    def test_send_http_error_raises_without_token(
        self, make_client: ClientFactory, status: int
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, json={"ok": False, "description": "no"})

        notifier = TelegramNotifier(make_client(handler), _settings())
        with pytest.raises(NotifyError, match=str(status)) as info:
            notifier.send("hola")
        assert TOKEN not in str(info.value)
        assert TOKEN not in repr(info.value)
        assert TOKEN not in repr(notifier)

    @pytest.mark.parametrize(
        "error",
        [
            httpx.ConnectError("fallo con https://x/bot" + TOKEN),
            httpx.ReadTimeout("timeout en " + TOKEN),
        ],
    )
    def test_send_network_error_raises_without_token(
        self, make_client: ClientFactory, error: httpx.HTTPError
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise error

        notifier = TelegramNotifier(make_client(handler), _settings())
        with pytest.raises(NotifyError) as info:
            notifier.send("hola")
        assert TOKEN not in str(info.value)
        assert TOKEN not in repr(info.value)
        assert info.value.__cause__ is None or TOKEN not in str(info.value.__cause__)

    def test_send_sets_explicit_timeouts(self, make_client: ClientFactory) -> None:
        timeouts: list[Any] = []

        def handler(request: httpx.Request) -> httpx.Response:
            timeouts.append(request.extensions["timeout"])
            return httpx.Response(200, json={"ok": True})

        TelegramNotifier(make_client(handler), _settings()).send("hola")
        assert timeouts == [{"connect": 5.0, "read": 10.0, "write": 10.0, "pool": 10.0}]

    def test_send_long_text_is_split_in_several_requests(
        self, make_client: ClientFactory
    ) -> None:
        texts: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            texts.append(json.loads(request.content)["text"])
            return httpx.Response(200, json={"ok": True})

        text = "\n".join(f"<b>línea {i}</b> " + "x" * 90 for i in range(100))
        TelegramNotifier(make_client(handler), _settings()).send(text)

        assert len(texts) > 1
        assert all(len(part) <= MAX_MESSAGE_LEN for part in texts)
        assert "\n".join(texts) == text


class TestSplitText:
    def test_split_short_text_returns_single_part(self) -> None:
        assert split_text("hola") == ["hola"]

    def test_split_cuts_on_line_boundaries(self) -> None:
        lines = ["a" * 3000, "b" * 3000]
        assert split_text("\n".join(lines)) == lines

    def test_split_line_longer_than_limit_is_cut_hard(self) -> None:
        parts = split_text("z" * (MAX_MESSAGE_LEN * 2 + 5))
        assert [len(p) for p in parts] == [MAX_MESSAGE_LEN, MAX_MESSAGE_LEN, 5]
