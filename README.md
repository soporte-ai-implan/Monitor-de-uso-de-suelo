# Monitor de Suelo — IMPLAN Torreón

Dashboard público de la oferta de terrenos en venta en Torreón, alimentado por
scraping automatizado de portales inmobiliarios.

## Arranque rápido

```bash
pip install -r requirements.txt
```

Configurar el token de Apify:

```bash
copy .env.example .env
```

Ver el dashboard sin necesidad de pipeline ni servidor (usa los 19 puntos de
ejemplo) — abre `web/index.html` con doble clic.

Correr el pipeline en modo seco, sin escribir en la base:

```bash
python main.py --seco --max 20
```

Corrida real:

```bash
python main.py
```

Levantar la API:

```bash
uvicorn api:app --reload --port 8000
```

Programarlo en automático: ver [docs/scheduler.md](docs/scheduler.md).

## Estructura

```
main.py         orquesta: scraper -> geocoding -> database
scraper.py      Actores de Apify (Inmuebles24 + Pincali)
geocoding.py    Nominatim + fallback dentro del polígono de zona
zonas.py        point-in-polygon y asignación de zona (espejo de web/geo.js)
database.py     altas/bajas, historial de precios, filtros
api.py          FastAPI con CORS
scheduler.py    scheduler en proceso (alternativa a Task Scheduler)
schema.sql      esquema SQLite

web/
  index.html    dashboard con el mapa
  geo.js        lógica geoespacial del cliente
  zonas.js      geojson de zonas, generado
  puntos_demo.js  puntos de ejemplo, generado

data/
  torreon_zonas_final.geojson   5 zonas (SEPOMEX, fusionadas)
  puntos_prueba_demo.json       19 puntos de ejemplo

tests/
  test_zonas.py     paridad Python/JS + validación geográfica
  test_database.py  blindajes contra bajas falsas + filtros
  test_scraper.py   normalizadores + compatibilidad de apify-client
  test_api.py       endpoints + encabezados CORS

tools/
  generar_assets_web.py  data/*.json -> web/*.js
```

## Documentación por módulo

Cada módulo tiene su documento con las decisiones técnicas y por qué se tomaron:

- **[docs/mapa.md](docs/mapa.md)** — qué estaba mal en el mapa y cómo se corrigió.
  **Empieza por aquí.**
- [docs/scraper.md](docs/scraper.md) — Actores validados, schemas reales, por qué
  se descartó Vivanuncios.
- [docs/geocoding.md](docs/geocoding.md) — orden de preferencia de coordenadas,
  reglas de Nominatim.
- [docs/database.md](docs/database.md) — los dos blindajes contra bajas falsas.
- [docs/api.md](docs/api.md) — endpoints y CORS.
- [docs/scheduler.md](docs/scheduler.md) — cómo ponerlo en automático.

## Pruebas

Las cuatro corren **sin token de Apify** y sin red:

```bash
python tests/test_zonas.py
```

```bash
python tests/test_database.py
```

```bash
python tests/test_scraper.py
```

```bash
python tests/test_api.py
```

- `test_zonas` — que `zonas.py` (pipeline) y `web/geo.js` (mapa) den el mismo
  resultado; si divergen, la base y el dashboard se contradicen.
- `test_database` — que un fallo del scraper no vacíe el monitor.
- `test_scraper` — los normalizadores contra los schemas reales, y que el
  lector de campos funcione con las dos formas de respuesta de `apify-client`
  (ver [docs/scraper.md](docs/scraper.md)).
- `test_api` — que los endpoints respondan y que salgan los encabezados CORS.

## Fuentes de datos

| Fuente | Estado | Volumen |
|---|---|---|
| Inmuebles24 | activa | ~84 terrenos |
| Pincali | activa | ~18 terrenos |
| Vivanuncios | **descartada** | los 2 actores disponibles fallaron en pruebas reales |

El monitor arranca con **2 fuentes, no 3**. El dashboard lo declara con
Vivanuncios tachado; no se esconde la limitación.

## Cosas que conviene saber

**Las 5 zonas no cubren el municipio completo.** Son la unión de colonias
SEPOMEX, así que las áreas ejidales y rústicas quedan como huecos. Un terreno
real de Torreón a más de 1.5 km de toda zona se descarta. Se cierra del todo
con el polígono oficial del municipio (Marco Geoestadístico del INEGI) — ver
[docs/mapa.md](docs/mapa.md).

**No se usa shapely ni geopandas a propósito.** El point-in-polygon está
implementado a mano (~60 líneas en `zonas.py`) para que el pipeline instale sin
dependencias binarias ni GDAL, que en Windows son la principal fuente de dolor
al desplegar.

**Nunca se mueven las coordenadas de un anuncio real.** Si cae fuera de las
zonas, se etiqueta y se cuenta en el panel de validación del dashboard. Mover un
punto real para que "se vea bien" es falsear el dato — y fue justo el bug del
diseño original.
