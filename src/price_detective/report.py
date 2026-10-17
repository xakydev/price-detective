"""Composición del resumen y la alerta en HTML de Telegram (`parse_mode=HTML`)."""

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from html import escape

from price_detective.models import Offer, PhoneModel, SourceResult

__all__ = ["compose_alert", "compose_summary", "format_eur"]

_SOURCE_LABELS = {"chollometro": "Chollómetro", "apple": "Apple"}
_MODEL_LABELS = {
    PhoneModel.IPHONE_17: "iPhone 17",
    PhoneModel.IPHONE_17_PRO: "iPhone 17 Pro",
}
_CENT = Decimal("0.01")


def format_eur(amount: Decimal) -> str:
    """Formatea un importe al estilo español: `1.092,10 €`."""
    text = f"{amount.quantize(_CENT, rounding=ROUND_HALF_UP):,.2f}"
    return text.replace(",", "\0").replace(".", ",").replace("\0", ".") + " €"


def _link(offer: Offer) -> str:
    return f'<a href="{escape(offer.url, quote=True)}">ver oferta</a>'


def _source_label(source: str) -> str:
    return _SOURCE_LABELS.get(source, source)


def _best_deal(results: Sequence[SourceResult], model: PhoneModel) -> Offer | None:
    deals = [
        offer
        for result in results
        if result.source == "chollometro" and result.ok
        for offer in result.offers
        if offer.model is model
    ]
    return min(deals, key=lambda offer: offer.price_eur, default=None)


def _reference(results: Sequence[SourceResult], model: PhoneModel) -> Offer | None:
    for result in results:
        if result.source == "apple" and result.ok:
            for offer in result.offers:
                if offer.model is model:
                    return offer
    return None


def _saving(deal: Offer, reference: Offer) -> str:
    amount = reference.price_eur - deal.price_eur
    if amount <= 0:
        return ""
    percent = (amount / reference.price_eur * 100).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return f" (ahorras {format_eur(amount)}, -{percent}%)"


def _model_block(results: Sequence[SourceResult], model: PhoneModel) -> list[str]:
    lines = [f"<b>{_MODEL_LABELS[model]} 256 GB</b>"]
    deal = _best_deal(results, model)
    reference = _reference(results, model)
    if deal is not None:
        saving = _saving(deal, reference) if reference is not None else ""
        lines.append(
            f"Chollo: {format_eur(deal.price_eur)} en {escape(deal.store)}"
            f"{saving} - {_link(deal)}"
        )
    elif all(r.ok for r in results if r.source == "chollometro"):
        lines.append(f"Sin chollo vigente para {_MODEL_LABELS[model]}")
    if reference is not None:
        label = "precio de lanzamiento" if reference.launch_price else "referencia"
        lines.append(f"Apple: {format_eur(reference.price_eur)} ({label})")
    return lines


def compose_summary(results: Sequence[SourceResult]) -> str:
    """Resumen con el mejor chollo y la referencia de cada modelo."""
    lines = ["<b>Resumen de precios iPhone</b>"]
    for model in PhoneModel:
        block = _model_block(results, model)
        if len(block) > 1:
            lines.append("")
            lines.extend(block)
    failures = [r for r in results if not r.ok]
    if failures:
        lines.append("")
        for result in failures:
            lines.append(
                f"{_source_label(result.source)}: no disponible "
                f"({escape(result.error or '')})"
            )
    return "\n".join(lines)


def compose_alert(offer: Offer, previous_min: Decimal) -> str:
    """Alerta de bajada de precio frente al mínimo anterior."""
    return "\n".join(
        [
            f"<b>Bajada de precio: {_MODEL_LABELS[offer.model]} "
            f"{offer.storage_gb} GB</b>",
            f"Ahora: {format_eur(offer.price_eur)} en {escape(offer.store)}",
            f"Mínimo anterior: {format_eur(previous_min)}",
            _link(offer),
        ]
    )
