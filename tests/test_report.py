"""Tests de la composición del resumen y la alerta en HTML de Telegram."""

from decimal import Decimal

import pytest

from price_detective.models import Offer, PhoneModel, SourceResult
from price_detective.report import compose_alert, compose_summary, format_eur


def _offer(
    model: PhoneModel,
    price: str,
    *,
    source: str = "chollometro",
    offer_id: str = "1",
    title: str = "iPhone",
    store: str = "Amazon",
    url: str = "https://example.com/x",
    launch: bool = False,
) -> Offer:
    return Offer(
        source=source,
        offer_id=f"{source}:{offer_id}",
        model=model,
        storage_gb=256,
        price_eur=Decimal(price),
        title=title,
        store=store,
        url=url,
        launch_price=launch,
    )


def _apple(*, pro_launch: bool = False) -> SourceResult:
    return SourceResult(
        source="apple",
        offers=(
            _offer(
                PhoneModel.IPHONE_17,
                "1109.00",
                source="apple",
                store="Apple",
                url="https://apple.example/17",
            ),
            _offer(
                PhoneModel.IPHONE_17_PRO,
                "1319.00",
                source="apple",
                store="Apple",
                url="https://apple.example/17",
                launch=pro_launch,
            ),
        ),
    )


class TestFormatEur:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("850", "850,00 €"),
            ("1092.1", "1.092,10 €"),
            ("1319.00", "1.319,00 €"),
            ("1234567.89", "1.234.567,89 €"),
        ],
    )
    def test_format_eur_uses_spanish_style(self, value: str, expected: str) -> None:
        assert format_eur(Decimal(value)) == expected


class TestSummary:
    def test_summary_shows_best_deal_and_reference(self) -> None:
        cholo = SourceResult(
            source="chollometro",
            offers=(
                _offer(PhoneModel.IPHONE_17, "900.00", offer_id="1", store="PcComp"),
                _offer(
                    PhoneModel.IPHONE_17,
                    "850.00",
                    offer_id="2",
                    store="Amazon",
                    url="https://example.com/best",
                ),
            ),
        )
        text = compose_summary([cholo, _apple()])
        assert "850,00 €" in text
        assert "Amazon" in text
        assert "https://example.com/best" in text
        assert "900,00 €" not in text
        assert "referencia" in text
        assert "1.109,00 €" in text

    def test_summary_shows_saving_against_reference(self) -> None:
        cholo = SourceResult(
            source="chollometro",
            offers=(_offer(PhoneModel.IPHONE_17, "850.00"),),
        )
        text = compose_summary([cholo, _apple()])
        assert "259,00 €" in text
        assert "23%" in text

    def test_summary_without_deal_says_so_and_keeps_reference(self) -> None:
        cholo = SourceResult(
            source="chollometro",
            offers=(_offer(PhoneModel.IPHONE_17, "850.00"),),
        )
        text = compose_summary([cholo, _apple()])
        assert "Sin chollo vigente" in text
        assert "iPhone 17 Pro" in text
        assert "1.319,00 €" in text

    def test_summary_labels_launch_price_by_flag(self) -> None:
        cholo = SourceResult(source="chollometro")
        text = compose_summary([cholo, _apple(pro_launch=True)])
        assert "precio de lanzamiento" in text
        assert text.count("referencia") == 1

    def test_summary_label_ignores_title(self) -> None:
        apple = SourceResult(
            source="apple",
            offers=(
                _offer(
                    PhoneModel.IPHONE_17,
                    "1109.00",
                    source="apple",
                    title="precio de lanzamiento",
                ),
            ),
        )
        text = compose_summary([SourceResult(source="chollometro"), apple])
        assert "precio de lanzamiento" not in text

    def test_summary_failed_source_reports_reason_and_keeps_apple(self) -> None:
        cholo = SourceResult(source="chollometro", error="HTTP 403")
        text = compose_summary([cholo, _apple()])
        assert "Chollómetro: no disponible (HTTP 403)" in text
        assert "1.109,00 €" in text

    def test_summary_failed_apple_keeps_deals(self) -> None:
        cholo = SourceResult(
            source="chollometro",
            offers=(_offer(PhoneModel.IPHONE_17, "850.00"),),
        )
        apple = SourceResult(source="apple", error="timeout")
        text = compose_summary([cholo, apple])
        assert "Apple: no disponible (timeout)" in text
        assert "850,00 €" in text

    def test_summary_both_failed_reports_both_and_no_prices(self) -> None:
        text = compose_summary(
            [
                SourceResult(source="chollometro", error="HTTP 500"),
                SourceResult(source="apple", error="timeout"),
            ]
        )
        assert "Chollómetro: no disponible (HTTP 500)" in text
        assert "Apple: no disponible (timeout)" in text
        assert "€" not in text

    def test_summary_escapes_html_in_titles_stores_and_reasons(self) -> None:
        cholo = SourceResult(
            source="chollometro",
            offers=(
                _offer(
                    PhoneModel.IPHONE_17,
                    "850.00",
                    title="A&B <b>",
                    store="R&<Co>",
                    url="https://example.com/?a=1&b=2",
                ),
            ),
        )
        apple = SourceResult(source="apple", error="<oops> & más")
        text = compose_summary([cholo, apple])
        assert "R&amp;&lt;Co&gt;" in text
        assert "a=1&amp;b=2" in text
        assert "&lt;oops&gt; &amp; más" in text
        assert "<Co>" not in text

    def test_summary_keeps_underscore_readable(self) -> None:
        cholo = SourceResult(
            source="chollometro",
            offers=(_offer(PhoneModel.IPHONE_17, "850.00", store="tienda_x"),),
        )
        assert "tienda_x" in compose_summary([cholo, _apple()])


class TestAlert:
    def test_alert_includes_price_previous_min_store_and_url(self) -> None:
        offer = _offer(
            PhoneModel.IPHONE_17,
            "850.00",
            store="Amazon",
            url="https://example.com/best",
        )
        text = compose_alert(offer, Decimal("900.00"))
        assert "iPhone 17" in text
        assert "850,00 €" in text
        assert "900,00 €" in text
        assert "Amazon" in text
        assert "https://example.com/best" in text

    def test_alert_escapes_special_characters(self) -> None:
        offer = _offer(
            PhoneModel.IPHONE_17_PRO,
            "1000.00",
            title="x <y> & z_w",
            store="A&B",
            url="https://example.com/?a=1&b=2",
        )
        text = compose_alert(offer, Decimal("1100.00"))
        assert "A&amp;B" in text
        assert "a=1&amp;b=2" in text
        assert "A&B" not in text
