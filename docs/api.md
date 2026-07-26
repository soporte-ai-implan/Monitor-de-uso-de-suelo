# api.py

FastAPI. Sirve los datos al dashboard.

```bash
uvicorn api:app --reload --port 8000
```

Documentación interactiva en `http://localhost:8000/docs`.

## Endpoints

| Ruta | Qué da |
|---|---|
| `GET /api/monitor-terrenos` | anuncios activos — es lo que consume el mapa |
| `GET /api/zonas` | el GeoJSON de las 5 zonas |
| `GET /api/resumen` | agregados por zona: total, $/m² promedio/min/máx, m² mediana |
| `GET /api/corridas` | bitácora de ejecuciones |
| `GET /salud` | si la API responde y cuándo fue la última corrida |

## CORS explícito

Sin encabezados CORS el navegador bloquea el `fetch()` **sin decir por qué** — se
ve como si la API estuviera caída. El HTML va a vivir en otro dominio
(`trcimplan.gob.mx`) y durante las demos se abre desde `file://`, así que hace
falta en los dos casos.

Configurable con `CORS_ORIGENES` en `.env`. En producción conviene acotarlo:

```
CORS_ORIGENES=https://trcimplan.gob.mx,https://www.trcimplan.gob.mx
```

`allow_credentials=False` a propósito: son datos públicos, no hay sesión, y con
`*` los navegadores rechazan la combinación con credenciales.

## Por qué `/api/zonas`

El dashboard podría traer el geojson por su cuenta, pero entonces habría dos
copias del archivo que pueden desincronizarse. Exponerlo desde la API garantiza
que el mapa dibuja exactamente los mismos polígonos con los que el pipeline
clasificó los puntos.

Durante las demos `web/index.html` usa `web/zonas.js` (generado por
`tools/generar_assets_web.py`) porque `fetch()` no funciona en `file://`, pero en
producción conviene apuntar al endpoint.

## `precio_m2` viene precalculado

Se guarda en la tabla, no se calcula en cada petición. El mapa de calor pondera
por $/m² y los KPIs lo promedian; calcularlo por request para ~100 anuncios es
barato, pero tenerlo en columna permite ordenar e indexar en SQL.
