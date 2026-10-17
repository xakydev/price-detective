"""Pruebas contra las fuentes reales; excluidas por defecto (`-m network`)."""

from collections.abc import Iterator

import httpx
import pytest

from price_detective.sources.apple import AppleSource
from price_detective.sources.chollometro import ChollometroSource

pytestmark = pytest.mark.network


@pytest.fixture
def live_client() -> Iterator[httpx.Client]:
    with httpx.Client() as client:
        yield client


class TestLiveSources:
    def test_chollometro_returns_parseable_offers(
        self, live_client: httpx.Client
    ) -> None:
        offers = ChollometroSource().fetch(live_client)

        assert all(offer.price_eur > 0 for offer in offers)

    def test_apple_returns_reference_prices(self, live_client: httpx.Client) -> None:
        offers = AppleSource().fetch(live_client)

        assert offers
        assert all(offer.storage_gb == 256 for offer in offers)
