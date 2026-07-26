# scraper.py

Trae los anuncios de los Actores de Apify y los normaliza a un formato común.

## Actores en uso

### Inmuebles24 — `benthepythondev/inmuebles24-scraper`

```python
{"maxResultsPerSearch": 200, "searchUrls": [{"url": "https://www.inmuebles24.com/terrenos-en-venta-en-torreon.html"}]}
```

Confirmado: 84 resultados reales, 14/15 de la muestra eran terrenos correctos en
Torreón. Trae lat/lon, precio, m², URL.

**La URL de búsqueda va ya armada, a propósito.** El otro actor disponible,
`fatihtahta/inmuebles24-scraper`, construye la búsqueda con parámetros sueltos y
tiene un bug confirmado: combinar `location` + `property_type` regresa **0
resultados** para Torreón. No usarlo.

### Pincali — `azzouzana/pincali-com-scraper-by-search-url`

```python
{"maxItems": 200, "startUrl": "https://www.pincali.com/inmuebles/terrenos-en-venta-en-torreon-coahuila"}
```

Confirmado: 5/5 resultados fueron terrenos reales en Torreón. Volumen bajo
(~18 terrenos totales en el portal), pero es fuente viva.

### Vivanuncios — DESCARTADO

Los 2 únicos actores disponibles fallaron en pruebas reales:

| Actor | Falla |
|---|---|
| `stealth_mode/vivanuncios-property-search-scraper` | crashea en ~1 segundo |
| `jungle_synthesizer/mexico-inmuebles24-metroscubicos-scraper` | muere a los 66 s, probable bloqueo de Cloudflare |

**El monitor arranca con 2 fuentes, no 3.** Esto se declara en el dashboard con
Vivanuncios tachado, no se esconde. Si alguien pregunta después por qué no está
esa fuente, la respuesta está aquí.

## Los schemas reales no eran los que asumía el prompt

Se consultó el output schema de cada Actor antes de escribir el normalizador.
El prompt original asumía `location.full_address` para Inmuebles24; **ese campo
no existe**. Los campos reales son planos.

**Inmuebles24:** `id`, `title`, `generated_title`, `price`, `currency`,
`land_area_m2`, `covered_area_m2`, `total_area_m2`, `address`, `neighborhood`,
`city`, `province`, `latitude`, `longitude`, `url`, `property_type`,
`operation`, `modified_at`.

Para terrenos el campo de superficie útil es **`land_area_m2`**, no
`covered_area_m2` (que es construcción) ni `total_area_m2` (que viene null).

**Pincali:** `listingId`, `propertyId`, `price`, `currency`, `areaM2`,
`fullAddress`, `locationText`, `neighborhood`, `city`, `state`, `latitude`,
`longitude`, `url`, `canonicalUrl`, `propertyType`, `operationType`,
`publishedAt`.

Ojo: **`title` en Pincali viene siempre `null`**, así que el título se arma con
`{propertyType} en {locationText}`.

## Compatibilidad con versiones de `apify-client`

Ojo con esto, porque rompe el pipeline en silencio. La librería cambió la forma
de la respuesta entre versiones mayores:

| Versión | Qué regresa `actor().call()` |
|---|---|
| 1.x / 2.x | un `dict` con llaves camelCase — `run["defaultDatasetId"]` |
| 3.x | un modelo Pydantic con atributos snake_case — `run.default_dataset_id` |

El código de muestra original usaba `run.get("status")` y
`run["defaultDatasetId"]`, que en 3.x truenan con `AttributeError`. Al instalar
`requirements.txt` hoy entra la **3.1.0**, así que era un fallo garantizado en la
primera corrida real.

`_campo(obj, *nombres)` resuelve las dos formas: prueba acceso por llave si es
dict y por atributo si no, con los dos nombres posibles. También normaliza el
estatus, que en 3.x puede llegar como enum en vez de texto.

Se hizo así en vez de fijar la versión porque el servidor de IMPLAN puede tener
cualquiera de las dos y nadie va a revisar esto antes de actualizar. Está
cubierto en `tests/test_scraper.py` con objetos falsos de las dos formas, así que
no hace falta token de Apify para verificarlo.

## Decisiones

- **Los ids llevan prefijo de fuente** (`i24-`, `pin-`). Sin eso, un id numérico
  que coincida entre portales colapsaría dos anuncios distintos en uno.
- **Si una fuente truena, la otra sigue.** El monitor prefiere datos parciales
  con la falla anotada a no publicar nada. Qué fuente falló queda en la tabla
  `corridas`, y `database.py` usa esa lista para no dar de baja anuncios de una
  fuente que no respondió.
- **Los anuncios sin id se descartan**: sin id no hay forma de detectar altas
  y bajas entre corridas, que es la razón de ser del monitor.
