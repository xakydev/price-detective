# Fixtures de HTML

Grabadas el 2026-10-17 con `curl` desde IP residencial (una petición por URL,
User-Agent de Chrome, `Accept-Language: es-ES`). Los tests no usan red.

## Ficheros

| Fichero | Origen | Edición manual |
|---|---|---|
| `chollometro_search.html` | `https://www.chollometro.com/search?q=iphone%2017&hide_expired=true` (200, 81 698 B) | Se añadieron 3 artículos (ver abajo) tras el último `<article>`, precedidos de un comentario `FIXTURE`. El resto es el HTML real sin tocar |
| `apple_es_iphone.html` | `https://www.apple.com/es/shop/buy-iphone/iphone-17` (200, 497 392 B) | Ninguna |
| `chollometro_empty.html` | Derivada de `chollometro_search.html` | Eliminados todos los `<article>` (listado sin ofertas) |
| `chollometro_broken.html` | Derivada de `chollometro_search.html` | `data-vue3=` renombrado a `data-vue-x=` y `ThreadMainListItemNormalizer` a `ThreadMainListItemX` (estructura irreconocible) |
| `apple_missing_pro.html` | Derivada de `apple_es_iphone.html` | Recortada a los dos `<script>` con JSON de precios (offsets 23460-26857 y 384477-438907), JSON intacto. No contiene ningún iPhone 17 Pro (ver hallazgo) |

### Artículos de Chollómetro añadidos a mano

Copia de la estructura del artículo real 2016054 cambiando `threadId`,
`title`, `titleSlug`, `price` e `isExpired`. Todos con IDs 9000001+ (ficticios):

| threadId | title | price | isExpired |
|---|---|---|---|
| 9000001 | iPhone 17 Pro Max 256GB Naranja cósmico | 1299 | false |
| 9000002 | iPhone 17 256GB Negro | 879.0 | false |
| 9000003 | iPhone 17 256GB Blanco | 799.0 | **true** |

Contenido real (sin editar): 2016054 "iPhone 17 Pro 256GB Azul oscuro" 1092.1 EUR
(ShopDutyFree.es); fundas 2015381 (51.9), 2015382 (39.99), 2014985 (10, "Funda
beats iphone 17 pro max"), 2009752 (10.72); cartera MagSafe 2015996 (15.19).
Total real: 6 artículos, solo 1 es un móvil.

## Chollómetro: dónde está el JSON

- Cada oferta es un `<article id="thread_<id>" class="thread ...">`.
- Dentro hay varios `<div ... data-handler="vue3" data-vue3='{...}'>`. El que
  interesa es el de `"name":"ThreadMainListItemNormalizer"`.
- El atributo `data-vue3` va entre **comillas simples** y su contenido es JSON
  directo (con `"`; los acentos como `ó`). `HTMLParser` lo entrega ya
  desescapado, listo para `json.loads`. Hay otros `data-vue3` (botones,
  comentarios) y algunos `data-vue3` fuera de los artículos: filtrar por
  `name == "ThreadMainListItemNormalizer"`.
- La oferta está en `["props"]["thread"]`. Claves útiles:
  `threadId` (str), `title`, `titleSlug`, `price` (float, sin símbolo; `0`/
  ausente posible si es un cupón), `isExpired` (bool), `status`
  (`"Activated"`), `merchant.merchantName`, `publishedAt` (epoch s),
  `temperature`, `shareableLink` (`https://www.chollometro.com/share-deal/<id>`).
- No hay URL canónica de la oferta como tal: `link` viene vacío. Opciones:
  `shareableLink`, o `https://www.chollometro.com/ofertas/<titleSlug>-<threadId>`
  (no verificada).
- Con `hide_expired=true` no deberían llegar expiradas, pero hay que filtrar
  `isExpired` igualmente.

## Apple ES: precios por capacidad

La página de producto de Apple **es una por modelo**:
`/es/shop/buy-iphone/iphone-17` contiene solo iPhone 17.

Bloques con JSON de precios en `apple_es_iphone.html`:

1. Analytics (~offset 24 700): `"products":[{"sku":"MG6L4","partNumber":"MG6L4QL/A","price":{"fullPrice":1109.00},"category":"iphone","name":"iPhone 17 256GB Mist Blue"}, ...]`.
   Aquí `fullPrice` es **numérico** y está dentro de `price`; el `name`
   incluye modelo y capacidad. Hay **un producto por capacidad y color**
   (10 entradas: 5 colores x 2 capacidades).
2. Bloque de precios (~offset 389 000+): `"prices":{"mg6p4ql_a":{... "fullPrice-short":"1.359,00 €", ... "fullPrice":"Desde 1.359,00 €"}}` (aquí `fullPrice` es **texto** "Desde ..."; no usarlo) y
   `"products":[{"partNumber":..., "dimensionCapacity":"256gb","dimensionColor":"mistblue", "fullPrice":"mg6l4ql_a"}]`
   (aquí `fullPrice` es una clave de referencia a `prices`).

**Precio de 256 GB del iPhone 17: 1109.00 EUR** (los 5 colores, SKUs
MG6L4, MG6M4, MG6J4, MG6K4, MG6N4). **512 GB: 1359.00 EUR**. No hay 128 GB.
Recomendado: regex sobre el bloque 1, `"fullPrice":(\d+\.\d+)}[^{}]*"name":"iPhone 17 256GB`, o `json.loads` del array `products` y filtrar por `name`.

**iPhone 17 Pro: sin precio.** `/es/shop/buy-iphone/iphone-17-pro` responde
`301` a `/es/shop/buy-iphone`, y ese índice solo enlaza a iphone-16,
iphone-17, iphone-17e, iphone-18-pro, iphone-air e iphone-duo. Apple ya no
vende el 17 Pro en la tienda. Por eso `apple_missing_pro.html` es, de hecho,
el estado real de hoy. La afirmación de `explore.md` de que 1359.00 era el 17
Pro es incorrecta: es el iPhone 17 de 512 GB.

## Resultado del probe desde Actions

2026-10-17, runner `ubuntu-24.04` (IP de datacenter de GitHub), run 39038145284:

| Fuente | HTTP | Bytes | Página de desafío | Datos |
|---|---|---|---|---|
| Chollómetro (búsqueda) | 200 | 81 698 | no | sí (`ThreadMainListItemNormalizer`) |
| Apple ES iPhone 17 | 200 | 497 227 | no | sí (`"fullPrice":`) |

Ninguna fuente bloquea desde el runner. El tamaño coincide con el de la petición
residencial. La URL del iPhone 17 Pro devolvió 301 en el primer run (39038081835):
Apple ya no lo vende, y el probe dejó de consultarla.

El primer run marcó Chollómetro como "anti-bot" por un falso positivo: la página
normal incluye la config de `recaptcha`. El probe ahora solo detecta páginas de
desafío y comprueba que llegan los datos que se parsean.

## Anonimización (2026-10-24)

Antes de hacer público el repositorio, en `chollometro_search.html` y `chollometro_broken.html` se sustituyeron los nombres de usuario de quienes publicaron las ofertas por `usuario_1` … `usuario_5` y sus `userId` (también en las rutas de avatar) por `9000101` … `9000105`. El parser no usa esos campos.
