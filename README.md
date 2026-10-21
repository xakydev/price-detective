# price-detective

Vigila el precio del iPhone en España y avisa por Telegram cuando baja.

- **Fuentes**: Chollómetro (ofertas) y Apple ES (precio oficial de referencia).
- **Detección**: reconoce el modelo y la capacidad de cada oferta y la compara con el histórico.
- **Histórico**: un `history.json` en la rama `data`, que gestiona el workflow.
- **Avisos**: alertas de bajada y un resumen a las horas de `SUMMARY_HOURS`.
- **Ejecución**: GitHub Actions cada 30 minutos, sin servidor propio.

Para ponerlo en marcha (bot de Telegram, secrets y primera ejecución) sigue la
[guía de Telegram](docs/telegram-setup.md).
