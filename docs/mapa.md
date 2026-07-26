# El mapa: qué estaba mal y cómo quedó

Este es el documento más importante del repo, porque el mapa era el cuello de
botella: los puntos "se iban hasta Gómez Palacio" y las zonas no delimitaban bien.

## Diagnóstico

Los datos **nunca estuvieron mal**. Se validaron los 19 puntos de
`data/puntos_prueba_demo.json` contra `data/torreon_zonas_final.geojson` con
point-in-polygon real: **19 de 19 caen dentro de la zona que declaran**
(3 / 4 / 4 / 3 / 5 por zona). El problema estaba entero en el HTML del diseño.

### Causa 1 — el HTML no usaba el geojson

El diseño aprobado traía **5 polígonos dibujados a mano** con otros nombres
(`Centro`, `Norte`, `Sur`, `Este`, `Oeste`) y 8–10 vértices cada uno:

```js
// diseño original
{ nombre: 'Centro', coords: [[25.549,-103.422],[25.552,-103.408], ...] }
```

Las zonas reales son otras cosa: `Zona 1 - Poniente y Centro Histórico`,
`Zona 2 - Zona Norte`, `Zona 3 - Centro-Norte`, `Zona 4 - Oriente`,
`Zona 5 - Sur Oriente`, con **178 a 289 vértices** cada una, y dos de ellas son
MultiPolygon (Zona 2 y Zona 3 tienen 2 polígonos cada una).

Resultado: un punto cuya zona decía `Zona 2 - Zona Norte` **no tenía ningún
polígono que le correspondiera** en el mapa. Nunca iba a coincidir.

### Causa 2 — el clamp a un rectángulo (el que mandaba puntos a Gómez)

```js
// diseño original
const LIMITES = { latMin: 25.483, latMax: 25.579, lngMin: -103.463, lngMax: -103.356 };
const enLimite = (lat, lng) => [clamp(lat, ...), clamp(lng, ...)];
```

`clamp` no descarta un punto fuera de rango: lo **empuja al borde del
rectángulo**. Y ese rectángulo es más chico que Torreón:

| Dirección | Zonas reales llegan a | El clamp cortaba en | Territorio recortado |
|---|---|---|---|
| Norte | lat 25.6257 | 25.579 | ~5.2 km |
| Oeste | lon −103.4944 | −103.463 | ~3.1 km |
| Este  | lon −103.3057 | −103.356 | ~5.0 km |

De los 19 puntos demo, **5 caían fuera de ese rectángulo** y el clamp los movía
de lugar, apilándolos sobre la línea del borde. Eso es lo que se veía como
"puntos que se van a otro lado".

Un rectángulo alineado a los ejes tampoco puede representar a Torreón: el límite
poniente/norte es el Río Nazas, que corre en diagonal. Cualquier rectángulo o se
come pedazos de Gómez Palacio o recorta Torreón real. Aquí hacía las dos cosas.

## La corrección

`web/geo.js` (y su espejo `zonas.py`) reemplaza el clamp por:

1. **Guardián de municipio primero.** Si el anuncio declara ciudad y no es
   Torreón, se descarta sin importar la geometría.
2. **Point-in-polygon real** contra el geojson (ray casting, con soporte de
   MultiPolygon y huecos) para asignar zona.
3. **Zona más cercana** si cae fuera de todo pero a ≤ 1.5 km (caso rural/ejidal
   legítimo dentro de Torreón), marcado visualmente distinto.
4. **Descarte** más allá de eso.

**Nunca se mueven las coordenadas de un anuncio real.** Si cae fuera, se
etiqueta y se cuenta en el panel de validación; no se reubica. Mover un punto
real es falsear el dato.

### Por qué el guardián de municipio es indispensable

Medido contra este mismo geojson:

| Punto | Distancia al borde de una zona |
|---|---|
| Gómez Palacio, col. Filadelfia (Durango) | **0.25 km** |
| Torreón, zona industrial oriente (legítimo) | **2.29 km** |
| Gómez Palacio centro (Durango) | 2.43 km |

Hay puntos de Durango **más cerca** que puntos válidos de Torreón. Los rangos se
traslapan, así que **ningún umbral de distancia separa las dos ciudades** — son
contiguas por el río. Por eso el filtro de municipio (atributo `city` del portal)
es el guardián principal y la distancia solo resuelve el caso rural.

Ambos actores traen el campo: Inmuebles24 da `city` y `province`, Pincali da
`city` y `state`.

## Limitaciones que quedan (honestas)

1. **Anuncio sin campo de ciudad y a menos de 1.5 km del borde poniente**: se
   dibujaría aunque fuera de Gómez Palacio. Mitigado porque ambos portales sí
   traen ciudad; Nominatim da una segunda opinión cuando no.
2. **Falso negativo rural**: un terreno real de Torreón a más de 1.5 km de toda
   zona se descarta (las 5 zonas son unión de colonias SEPOMEX, no cubren el
   municipio completo — las áreas ejidales quedan como huecos).

Las dos se cierran del todo con **el polígono oficial del municipio de Torreón**
(Marco Geoestadístico del INEGI) como máscara: dentro del municipio se acepta,
fuera se descarta, y las zonas solo clasifican. Si consiguen ese archivo, se
conecta en `zonas.py` sin tocar el resto.

## Lo que pediste del mapa, y dónde está

| Petición | Implementación |
|---|---|
| Puntos reales animados | `.capa-pulso`, dos anillos desfasados 900 ms, ciclo 1.8 s |
| Info al acercar el cursor | `bindTooltip(..., {sticky:true})` — zona, $/m², m², total, portal, fecha |
| Mapa de calor | `L.heatLayer` alimentado por los puntos **reales**, peso por $/m² |
| Líneas trazadas de las zonas | `L.geoJSON` con `fill:false` — solo contorno exterior |

El diseño original alimentaba el heatmap con puntos jitteados inventados
alrededor del centro de cada zona para "dar textura de densidad". Eso se quitó:
la mancha de calor ahora refleja únicamente anuncios reales, si no el mapa miente
sobre dónde hay oferta.

## Cómo verificarlo

```bash
python tests/test_zonas.py
```

Comprueba que `zonas.py` y `web/geo.js` dan el mismo resultado, que los 19 puntos
demo caen en su zona, que el conteo coincide con la leyenda del mapa, y que el
fallback de punto aleatorio cae 500/500 dentro del polígono.
