"""Tests del filtro de identidad por título."""

import pytest

from price_detective.matching import classify
from price_detective.models import PhoneModel


class TestClassifyAccepted:
    @pytest.mark.parametrize(
        ("title", "model"),
        [
            ("iPhone 17 256GB Negro", PhoneModel.IPHONE_17),
            ("iPhone 17 256GB Blanco", PhoneModel.IPHONE_17),
            ("Apple iPhone 17 Pro 256 GB Azul oscuro", PhoneModel.IPHONE_17_PRO),
            ("iphone 17 pro 256gb", PhoneModel.IPHONE_17_PRO),
            ("iPhone 17 Pro 256GB Azul oscuro", PhoneModel.IPHONE_17_PRO),
            ("IPHONE 17 PRO 256GB", PhoneModel.IPHONE_17_PRO),
        ],
    )
    def test_classify_valid_title_returns_model_and_capacity(
        self, title: str, model: PhoneModel
    ) -> None:
        assert classify(title) == (model, 256)


class TestClassifyRejected:
    @pytest.mark.parametrize(
        "title",
        ["iPhone 17 512GB", "iPhone 17 Pro 1TB", "iPhone 17 128GB", "iPhone 17 1 TB"],
    )
    def test_classify_other_capacity_returns_none(self, title: str) -> None:
        assert classify(title) is None

    @pytest.mark.parametrize("title", ["iPhone 17 Pro Azul", "iPhone 17"])
    def test_classify_without_capacity_returns_none(self, title: str) -> None:
        assert classify(title) is None

    @pytest.mark.parametrize(
        "title",
        [
            "iPhone 17 Pro Max 256GB",
            "IPHONE 17 PRO MAX 256GB",
            "iPhone 17 Pro Max 256GB Naranja cósmico",
            "iPhone Air 256GB",
            "iPhone 17e 256GB",
            "iPhone 16 256GB",
            "Funda para iPhone 17 256GB",
            "Protector de pantalla iPhone 17 Pro",
            "Cristal templado iPhone 17 Pro 256GB",
            "Apple - Funda Siena Tech Woven para iPhone 17 Pro",
            "Apple - Funda de silicona color vainilla para iPhone 17 Pro",
            "Beats – Funda MagSafe para iPhone 17 Pro (Rosa Cuarzo)",
            "Funda beats iphone 17 pro max",
            (
                "Phelinta Cartera Magnética Compatible con MagSafe Wallet para "
                "iPhone 18 Pro Max/18 Pro/17/Air/16/15/14/13/12 Serie, 256GB"
            ),
        ],
    )
    def test_classify_denylisted_returns_none(self, title: str) -> None:
        assert classify(title) is None

    @pytest.mark.parametrize(
        "title",
        [
            "iPhone 17 256GB reacondicionado",
            "iPhone 17 Pro 256GB refurbished",
            "iPhone 17 256GB Renewed",
            "iPhone 17 256GB segunda mano",
            "iPhone 17 256GB Reacondicionado Premium",
        ],
    )
    def test_classify_used_returns_none(self, title: str) -> None:
        assert classify(title) is None

    def test_classify_numeric_prefix_returns_none(self) -> None:
        assert classify("iPhone 170 256GB") is None


class TestClassifyRam:
    @pytest.mark.parametrize(
        "capacities",
        [
            "256gb 8gb ram",
            "256gb (8gb ram)",
            "256 gb 8 gb de ram",
            "256gb + 8gb",
            "8gb/256gb",
            "256gb 256gb",
        ],
    )
    def test_classify_ram_or_small_capacity_is_ignored(self, capacities: str) -> None:
        assert classify(f"iPhone 17 {capacities}") == (PhoneModel.IPHONE_17, 256)

    @pytest.mark.parametrize(
        "title",
        [
            "iphone 17 16gb",
            "iphone 17 8gb ram",
            "iphone 17 512gb 8gb ram",
            "iphone 17 256gb 32gb",
            "iphone 17 256gb ram",
            "iphone 17 256gb 1tb",
            "iPhone 17 Pro Max 256GB 12GB RAM",
        ],
    )
    def test_classify_non_target_storage_with_ram_returns_none(
        self, title: str
    ) -> None:
        assert classify(title) is None
