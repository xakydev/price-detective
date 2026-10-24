from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from price_detective.errors import PriceDetectiveError
from price_detective.models import Offer, PhoneModel, SourceResult


def make_offer(price: Decimal = Decimal("899.00")) -> Offer:
    return Offer(
        source="chollometro",
        offer_id="123",
        model=PhoneModel.IPHONE_17,
        storage_gb=256,
        price_eur=price,
        title="iPhone 17 256GB",
        store="Amazon",
        url="https://example.com/123",
    )


class TestOffer:
    def test_build_without_color_is_valid(self) -> None:
        offer = make_offer()
        assert offer.price_eur == Decimal("899.00")
        assert offer.model is PhoneModel.IPHONE_17

    @pytest.mark.parametrize("price", [Decimal(0), Decimal("-1.50")])
    def test_build_non_positive_price_raises(self, price: Decimal) -> None:
        with pytest.raises(PriceDetectiveError, match="precio"):
            make_offer(price)

    @pytest.mark.parametrize(
        "price", [Decimal("Infinity"), Decimal("-Infinity"), Decimal("NaN")]
    )
    def test_build_non_finite_price_raises_domain_error(self, price: Decimal) -> None:
        with pytest.raises(PriceDetectiveError, match="precio"):
            make_offer(price)

    def test_offer_is_frozen(self) -> None:
        offer = make_offer()
        with pytest.raises(FrozenInstanceError):
            offer.store = "otra"  # type: ignore[misc]


class TestSourceResult:
    def test_ok_result_has_no_error(self) -> None:
        result = SourceResult(source="chollometro", offers=(make_offer(),))
        assert result.error is None
        assert result.ok

    def test_failed_result_keeps_reason(self) -> None:
        result = SourceResult(source="apple", error="HTTP 403")
        assert not result.ok
        assert result.offers == ()
