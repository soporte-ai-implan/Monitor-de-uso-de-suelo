# geocoding.py

Completa coordenadas y colonia, y asigna zona. Es el módulo que decide **dónde**
se dibuja cada punto, así que es el que más cuidado necesita.

## Orden de preferencia para las coordenadas

De más confiable a menos. El origen se guarda en la columna `coords_origen`, para
poder distinguir después un punto medido de uno inferido.

| Origen | Cómo se obtiene |
|---|---|
| `portal` | lat/lon que ya trae el anuncio (lo más común y lo más confiable) |
| `nominatim` | geocoding de la dirección en texto vía OpenStreetMap |
| `centroide_zona` | punto **dentro** del polígono de la zona deducida del texto |

El paso 3 **nunca** es aleatorio en todo el mapa: `zonas.punto_aleatorio_en_zona()`
hace rechazo por muestreo hasta caer dentro del polígono, y
`tests/test_zonas.py` verifica 100 intentos por zona (500/500 dentro).

Es **determinista por id de anuncio** (`random.Random(str(semilla))`): el mismo
predio no puede brincar de lugar entre corridas. Un punto que se mueve solo entre
dos visitas al dashboard destruye la confianza en el mapa.

## Reglas de Nominatim (obligatorias)

Es gratis y sin API key, pero su política de uso es estricta y bloquean por IP:

- **Máximo 1 petición por segundo** — `ESPERA_SEG = 1.1` con control de tiempo real
  entre llamadas, no un `sleep` fijo.
- **User-Agent identificable con contacto** — se arma con `NOMINATIM_CONTACTO`
  del `.env`. Si se deja el valor por omisión y se abusa, bloquean la IP.
- **Cachear** — `data/cache_geocoding.json`. La misma dirección no se pregunta
  dos veces, ni en esta corrida ni en las siguientes. Con ~100 anuncios y
  direcciones repetidas, esto baja una corrida de minutos a segundos.

La consulta se acota a Torreón (`", Torreón, Coahuila, México"` + `countrycodes=mx`)
salvo que la dirección ya lo mencione. Sin eso, Nominatim regresa calles con el
mismo nombre en otras ciudades del país — y ahí sí aparecen puntos en Sonora.

Nominatim también sirve de **segunda opinión sobre el municipio**: si el portal no
declaró ciudad, se usa la que devuelve el geocoder para alimentar el guardián de
`zonas.py`.

## Fallback por texto

`PISTAS_ZONA` mapea palabras de la dirección a una zona (`"zona norte"` →
`Zona 2 - Zona Norte`). Se revisan **en orden**, de más específica a más general:
`"centro historico"` antes que `"centro"`, `"sur oriente"` antes que `"sur"`. Si
se invierte el orden, todo lo del centro histórico cae en Centro-Norte.

Este fallback **solo aplica si el anuncio es de Torreón**. Si declara otro
municipio no se le inventa una ubicación: se descarta. Ver [mapa.md](mapa.md).

## Prueba rápida

```bash
python geocoding.py
```

Corre tres casos: una dirección real que sí geocodifica, una vaga que cae al
fallback por texto, y una de Gómez Palacio que debe quedar descartada.
