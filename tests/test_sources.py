"""Tests de las fuentes de precios: contrato, red, Chollómetro y Apple."""

from collections.abc import Callable
from decimal import Decimal

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
