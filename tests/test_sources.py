"""Tests de las fuentes de precios: contrato, red, Chollómetro y Apple."""

import json
import math
from collections.abc import Callable
from decimal import Decimal
from html import escape
from typing import Any

import httpx
import pytest
from conftest import ClientFactory

from price_detective.config import LAUNCH_REFERENCE_PRICES
from price_detective.errors import SourceFetchError, SourceParseError
from price_detective.models import Offer, PhoneModel
from price_detective.sources import PriceSource, get
from price_detective.sources.apple import AppleSource
from price_detective.sources.chollometro import ChollometroSource

URL = "https://example.test/page"


def _ok(body: str) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(200, text=body)


def _thread(**overrides: Any) -> dict[str, Any]:
    """Hilo de Chollómetro válido (iPhone 17 256GB) con campos sobrescritos."""
    thread: dict[str, Any] = {
        "threadId": 1,
        "title": "iPhone 17 256GB Negro",
        "price": 850.0,
        "isExpired": False,
        "shareableLink": "https://www.chollometro.com/share-deal/1",
        "merchant": {"merchantName": "Tienda"},
    }
    thread.update(overrides)
    return {k: v for k, v in thread.items() if v is not _MISSING}


_MISSING = object()


def _page(*threads: Any) -> str:
    """HTML mínimo con un bloque `data-vue3` por hilo."""
    blocks = []
    for index, thread in enumerate(threads):
        payload = {
            "name": "ThreadMainListItemNormalizer",
            "props": {"thread": thread},
        }
        blocks.append(
            f'<article id="thread_{index}">'
            f'<div data-vue3="{escape(json.dumps(payload))}"></div></article>'
        )
    return "<html><body>" + "".join(blocks) + "</body></html>"


class _FakeSource:
    name = "fake"

    def fetch(self, client: httpx.Client) -> list[Offer]:
        return [
            Offer(
                source=self.name,
                offer_id="fake:1",
                model=PhoneModel.IPHONE_17,
                storage_gb=256,
                price_eur=Decimal("900.00"),
                title="iPhone 17 256GB",
                store="Tienda",
                url="https://example.test/1",
            )
        ]


class TestPriceSourceContract:
    def test_fake_source_satisfies_protocol(self, make_client: ClientFactory) -> None:
        source: PriceSource = _FakeSource()
        offers = source.fetch(make_client(_ok("")))
        assert [o.offer_id for o in offers] == ["fake:1"]

    def test_real_sources_satisfy_protocol(self) -> None:
        sources: list[PriceSource] = [ChollometroSource(), AppleSource()]
        assert [s.name for s in sources] == ["chollometro", "apple"]


class TestGet:
    def test_ok_returns_body(self, make_client: ClientFactory) -> None:
        assert get(make_client(_ok("hola")), URL) == "hola"

    @pytest.mark.parametrize("status", [403, 429, 500, 503])
    def test_error_status_raises_with_code(
        self, make_client: ClientFactory, status: int
    ) -> None:
        client = make_client(lambda request: httpx.Response(status))
        with pytest.raises(SourceFetchError, match=str(status)):
            get(client, URL)

    def test_timeout_raises_with_kind(self, make_client: ClientFactory) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("lento", request=request)

        with pytest.raises(SourceFetchError, match="timeout"):
            get(make_client(handler), URL)

    def test_network_error_raises_with_type(self, make_client: ClientFactory) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("sin ruta", request=request)

        with pytest.raises(SourceFetchError, match="ConnectError"):
            get(make_client(handler), URL)

    def test_sets_explicit_timeouts(self, make_client: ClientFactory) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(request.extensions["timeout"])
            return httpx.Response(200, text="")

        get(make_client(handler), URL)
        assert seen["connect"] == 5.0
        assert seen["read"] == 10.0


class TestChollometroSource:
    def test_mixed_page_returns_only_valid_live_offers(
        self, make_client: ClientFactory, load_fixture: Callable[[str], str]
    ) -> None:
        client = make_client(_ok(load_fixture("chollometro_search.html")))
        offers = ChollometroSource().fetch(client)
        by_id = {o.offer_id: o for o in offers}
        assert set(by_id) == {"chollometro:2016054", "chollometro:9000002"}
        pro = by_id["chollometro:2016054"]
        assert pro.model is PhoneModel.IPHONE_17_PRO
        assert pro.storage_gb == 256
        assert pro.price_eur == Decimal("1092.1")
        assert pro.store == "ShopDutyFree.es"
        assert pro.source == "chollometro"
        assert pro.url == "https://www.chollometro.com/share-deal/2016054"
        assert by_id["chollometro:9000002"].model is PhoneModel.IPHONE_17

    def test_expired_offer_is_discarded(
        self, make_client: ClientFactory, load_fixture: Callable[[str], str]
    ) -> None:
        client = make_client(_ok(load_fixture("chollometro_search.html")))
        ids = {o.offer_id for o in ChollometroSource().fetch(client)}
        assert "chollometro:9000003" not in ids

    def test_empty_page_returns_empty_list(
        self, make_client: ClientFactory, load_fixture: Callable[[str], str]
    ) -> None:
        client = make_client(_ok(load_fixture("chollometro_empty.html")))
        assert ChollometroSource().fetch(client) == []

    def test_unrecognizable_page_raises_parse_error(
        self, make_client: ClientFactory, load_fixture: Callable[[str], str]
    ) -> None:
        client = make_client(_ok(load_fixture("chollometro_broken.html")))
        with pytest.raises(SourceParseError, match="Chollómetro"):
            ChollometroSource().fetch(client)

    def test_http_error_propagates_as_fetch_error(
        self, make_client: ClientFactory
    ) -> None:
        client = make_client(lambda request: httpx.Response(403))
        with pytest.raises(SourceFetchError, match="403"):
            ChollometroSource().fetch(client)


_BROKEN: list[dict[str, Any]] = [
    {"shareableLink": _MISSING},
    {"threadId": _MISSING},
    {"price": "1.099,00"},
    {"price": -5},
    {"merchant": "Tienda"},
]


class TestChollometroMalformed:
    """Datos con forma inesperada: nunca escapa un error que no sea `SourceError`."""

    @pytest.mark.parametrize("broken", _BROKEN)
    def test_only_broken_offer_raises_parse_error(
        self, make_client: ClientFactory, broken: dict[str, Any]
    ) -> None:
        client = make_client(_ok(_page(_thread(**broken))))
        with pytest.raises(SourceParseError, match="Chollómetro"):
            ChollometroSource().fetch(client)

    @pytest.mark.parametrize("broken", _BROKEN)
    def test_broken_offer_is_discarded_when_others_are_valid(
        self,
        make_client: ClientFactory,
        broken: dict[str, Any],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        html = _page(_thread(**{"threadId": 1, **broken}), _thread(threadId=2))
        with caplog.at_level("WARNING"):
            offers = ChollometroSource().fetch(make_client(_ok(html)))
        assert [o.offer_id for o in offers] == ["chollometro:2"]
        assert "descarta" in caplog.text

    @pytest.mark.parametrize("price", [math.inf, -math.inf, math.nan])
    def test_non_finite_price_is_discarded_without_title_in_logs(
        self,
        make_client: ClientFactory,
        caplog: pytest.LogCaptureFixture,
        price: float,
    ) -> None:
        title = "iPhone 17 256GB TituloSecreto"
        html = _page(
            _thread(threadId=1, title=title, price=price),
            _thread(threadId=2),
        )
        with caplog.at_level("DEBUG"):
            offers = ChollometroSource().fetch(make_client(_ok(html)))
        assert [o.offer_id for o in offers] == ["chollometro:2"]
        assert "descarta" in caplog.text
        assert "threadId 1" in caplog.text
        assert "TituloSecreto" not in caplog.text
        assert all("TituloSecreto" not in r.getMessage() for r in caplog.records)

    @pytest.mark.parametrize("price", [math.inf, -math.inf, math.nan])
    def test_all_non_finite_prices_raise_parse_error(
        self,
        make_client: ClientFactory,
        caplog: pytest.LogCaptureFixture,
        price: float,
    ) -> None:
        html = _page(_thread(title="iPhone 17 256GB TituloSecreto", price=price))
        with caplog.at_level("DEBUG"), pytest.raises(SourceParseError) as info:
            ChollometroSource().fetch(make_client(_ok(html)))
        assert "TituloSecreto" not in str(info.value)
        assert "TituloSecreto" not in caplog.text

    @pytest.mark.parametrize("props", [[], "x", 3, None])
    def test_props_that_is_not_an_object_raises_parse_error(
        self, make_client: ClientFactory, props: Any
    ) -> None:
        payload = {"name": "ThreadMainListItemNormalizer", "props": props}
        html = (
            f'<article id="thread_1"><div data-vue3="{escape(json.dumps(payload))}">'
            "</div></article>"
        )
        with pytest.raises(SourceParseError, match="Chollómetro"):
            ChollometroSource().fetch(make_client(_ok(html)))

    def test_irrelevant_broken_thread_does_not_fail_source(
        self, make_client: ClientFactory
    ) -> None:
        # Una funda sin `shareableLink` no pasa el filtro de identidad: se ignora.
        html = _page(
            _thread(title="Funda iPhone 17", shareableLink=_MISSING),
            _thread(threadId=2),
        )
        offers = ChollometroSource().fetch(make_client(_ok(html)))
        assert [o.offer_id for o in offers] == ["chollometro:2"]


class TestAppleMalformed:
    @staticmethod
    def _html(product: Any) -> str:
        return f'<script>{{"products":{json.dumps([product])}}}</script>'

    @pytest.mark.parametrize(
        "price",
        ["1.109,00", ["x"], 3],
    )
    def test_price_that_is_not_an_object_raises_parse_error(
        self, make_client: ClientFactory, price: Any
    ) -> None:
        html = self._html({"name": "iPhone 17 256GB", "price": price})
        with pytest.raises(SourceParseError, match="Apple: bloque `price` inválido"):
            AppleSource().fetch(make_client(_ok(html)))

    @pytest.mark.parametrize("full_price", [0.0, -1109.0])
    def test_non_positive_price_raises_parse_error(
        self, make_client: ClientFactory, full_price: float
    ) -> None:
        html = self._html(
            {"name": "iPhone 17 256GB", "price": {"fullPrice": full_price}}
        )
        with pytest.raises(SourceParseError, match="Apple: .*precio.*inválido"):
            AppleSource().fetch(make_client(_ok(html)))

    @pytest.mark.parametrize("full_price", [math.inf, math.nan])
    def test_non_finite_price_is_ignored_as_before(
        self, make_client: ClientFactory, full_price: float
    ) -> None:
        # json.dumps emite Infinity/NaN, que json lee como float: se ignoran.
        html = self._html(
            {"name": "iPhone 17 256GB", "price": {"fullPrice": full_price}}
        )
        with pytest.raises(SourceParseError, match="iphone-17"):
            AppleSource().fetch(make_client(_ok(html)))


class TestAppleSource:
    def test_iphone_17_256_is_1109_not_512_price(
        self, make_client: ClientFactory, load_fixture: Callable[[str], str]
    ) -> None:
        client = make_client(_ok(load_fixture("apple_es_iphone.html")))
        offers = {o.model: o for o in AppleSource().fetch(client)}
        offer = offers[PhoneModel.IPHONE_17]
        assert offer.price_eur == Decimal("1109.00")
        assert offer.offer_id == "apple:iphone-17"
        assert offer.storage_gb == 256
        assert offer.source == "apple"
        assert not offer.launch_price

    def test_retired_pro_uses_launch_price_without_failure(
        self, make_client: ClientFactory, load_fixture: Callable[[str], str]
    ) -> None:
        client = make_client(_ok(load_fixture("apple_missing_pro.html")))
        offers = {o.model: o for o in AppleSource().fetch(client)}
        pro = offers[PhoneModel.IPHONE_17_PRO]
        assert pro.price_eur == Decimal("1319.00")
        assert pro.offer_id == "apple:iphone-17-pro"
        assert pro.launch_price
        assert not offers[PhoneModel.IPHONE_17].launch_price

    def test_uses_configured_reference_prices(
        self, make_client: ClientFactory, load_fixture: Callable[[str], str]
    ) -> None:
        client = make_client(_ok(load_fixture("apple_es_iphone.html")))
        prices = {**LAUNCH_REFERENCE_PRICES, PhoneModel.IPHONE_17_PRO: Decimal(1)}
        offers = {o.model: o for o in AppleSource(prices).fetch(client)}
        assert offers[PhoneModel.IPHONE_17_PRO].price_eur == Decimal(1)

    def test_missing_model_without_fixed_price_raises_naming_model(
        self, make_client: ClientFactory, load_fixture: Callable[[str], str]
    ) -> None:
        client = make_client(_ok(load_fixture("apple_missing_pro.html")))
        with pytest.raises(SourceParseError, match="iphone-17-pro"):
            AppleSource({}).fetch(client)

    def test_page_without_prices_raises_parse_error(
        self, make_client: ClientFactory
    ) -> None:
        client = make_client(_ok("<html></html>"))
        with pytest.raises(SourceParseError, match="iphone-17"):
            AppleSource().fetch(client)

    def test_makes_a_single_request(
        self, make_client: ClientFactory, load_fixture: Callable[[str], str]
    ) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(200, text=load_fixture("apple_es_iphone.html"))

        AppleSource().fetch(make_client(handler))
        assert len(calls) == 1
