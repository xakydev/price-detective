# Guía de puesta en marcha con Telegram

Esta guía asume que nunca has creado un bot de Telegram. Al final tendrás el
workflow `price-detective` enviándote avisos y resúmenes.

## 1. Crear el bot con @BotFather

1. En Telegram, busca **@BotFather** (la cuenta verificada) y abre el chat.
2. Envía `/newbot`.
3. Elige un nombre visible (por ejemplo, `Price Detective`) y un usuario que
   termine en `bot` (por ejemplo, `mi_price_detective_bot`).
4. BotFather responde con el **token**, algo como `123456789:AAH...`.

> El token da control total sobre el bot. Guárdalo en un gestor de contraseñas
> y no lo compartas, no lo subas al repositorio ni lo pegues en issues o chats.
> Si se filtra, envía `/revoke` a BotFather para generar uno nuevo.

## 2. Obtener el `chat_id`

1. Abre el chat con tu bot y pulsa **Iniciar** (o escríbele cualquier mensaje).
   Si prefieres un grupo, crea el grupo, añade al bot y escribe un mensaje en él.
2. Abre en el navegador, sustituyendo `<TOKEN>` por tu token:

   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```

3. Busca en la respuesta `"chat":{"id":...}`. Ese número es el `chat_id`.
   En un chat privado es positivo; en un **grupo es negativo** (por ejemplo,
   `-1001234567890`). Si la respuesta sale vacía (`"result":[]`), escribe otro
   mensaje al bot y recarga.

> Esa URL contiene tu token. No la pegues en sitios públicos ni la compartas.

## 3. Cargar los secrets y la variable en GitHub

Con la CLI `gh` (desde la raíz del repositorio):

```bash
gh secret set TELEGRAM_BOT_TOKEN      # pega el token cuando lo pida
gh secret set TELEGRAM_CHAT_ID        # pega el chat_id cuando lo pida
gh variable set SUMMARY_HOURS --body "9,21"
```

Por la web: **Settings > Secrets and variables > Actions**.

- Pestaña **Secrets** > *New repository secret*: `TELEGRAM_BOT_TOKEN` y
  `TELEGRAM_CHAT_ID`.
- Pestaña **Variables** > *New repository variable*: `SUMMARY_HOURS` con el
  valor `9,21`.

`SUMMARY_HOURS` son las horas del resumen diario en horario de Madrid. Es
opcional: si no existe, se usa `9,21`. Si falta un secret, el workflow falla
al principio nombrando el que falta.

## 4. Primera ejecución

```bash
gh workflow run price-detective.yml -f force_summary=true
gh run watch
```

Qué esperar:

- Se crea la rama `data` con `history.json`.
- La primera ejecución fija la **línea base**: no envía alertas de bajada,
  porque aún no hay precios con los que comparar.
- Sí llega a Telegram el **resumen**, porque lo has forzado.
- El resumen del job en Actions muestra el código de salida.

Desde entonces corre sola cada 30 minutos (minutos 17 y 47 de cada hora), aunque GitHub puede retrasar o saltarse ejecuciones.

## 5. Códigos de salida

| Código | Significado | Qué hacer |
|---|---|---|
| 0 | Correcto | Nada. |
| 1 | Error inesperado | Revisa el log del job; si se repite, abre un issue con el traceback. |
| 2 | Configuración | Falta o es inválido un secret o `SUMMARY_HOURS` (formato `9,21`). Revisa el paso 3. |
| 3 | Fallan las dos fuentes | Chollómetro y Apple no responden o han cambiado su formato. Reintenta más tarde; si persiste, revisa los parsers. |
| 4 | Histórico | `history.json` está corrupto o tiene una versión desconocida. Corrige o borra el fichero en la rama `data`. |
| 5 | Telegram | Token o `chat_id` incorrectos, o el bot no tiene permiso en el chat. No se guarda nada, así que la siguiente ejecución reintenta. |

Con cualquier código distinto de 0 el job acaba en rojo y no se guarda el
histórico.

## 6. Calidad en local

```bash
uv sync
uv run pytest               # sin red (excluye los tests marcados network)
uv run ruff check
uv run ruff format --check
uv run mypy src
```

Los tests que hacen peticiones reales a las webs están excluidos por defecto:

```bash
uv run pytest -m network
```

## 7. Cambiar la frecuencia

Edita la línea `cron` de `.github/workflows/price-detective.yml` (por defecto
`17,47 * * * *`, cada 30 minutos en los minutos 17 y 47). GitHub **no permite leer el cron de
una variable**, así que el cambio se hace en el fichero. Evita el minuto 0:
es cuando más workflows arrancan a la vez y Actions retrasa las ejecuciones.
Las horas del resumen no dependen del cron, sino de `SUMMARY_HOURS`. Si una
ejecución se retrasa, el resumen de un slot sigue pendiente hasta que empieza el
siguiente slot, así que se envía en la primera ejecución que llegue; si se salta
un slot entero, solo se envía el más reciente.
