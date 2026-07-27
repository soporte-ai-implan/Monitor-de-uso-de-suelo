# Prompt para Claude Code — Monitor de Suelo IMPLAN Torreón

## Contexto del proyecto
Estoy construyendo el "Monitor de Suelo" para IMPLAN Torreón: un dashboard público que muestra la oferta actual de terrenos en venta en la ciudad, alimentado por scraping automatizado. Este mensaje trae TODO el contexto validado hoy — no reinventes lo que ya está probado, constrúyelo directamente.

## Archivos que te estoy dando en esta carpeta
- `muestra_codigo_pipeline.py` — código base de Víctor (schema.sql, scraper.py, database.py, api.py, main.py en un solo archivo, hay que separarlos)
- `Monitor de Suelo.dc.html` (o el nombre que tenga el HTML de Claude Design) — el diseño visual ya aprobado por el Director General, con sintaxis propia del editor (`sc-raw-table`, `data-dc-script`) que hay que limpiar a HTML/JS estándar
- `torreon_zonas_final.geojson` — 5 polígonos fusionados (uno por zona, ya sin las líneas internas de colonias individuales) de Torreón (fuente: SEPOMEX vía repo open-mexico/mexico-geojson), ya limpiados de ruido geográfico y de colonias aisladas. Usa esto directamente para el fondo del mapa (capa de zonas), NO generes tus propios polígonos ni intentes trazar zonas desde cero. IMPORTANTE: dibuja SOLO el contorno exterior de cada zona (fill: false), sin líneas internas — Abraham (Director General) pidió explícitamente que no se vean las divisiones internas entre colonias, solo el borde externo de cada una de las 5 zonas.
- `puntos_prueba_demo.json` — 18 puntos de ejemplo (lat/lon reales dentro de cada zona, con precio y m² simulados) para mostrarle a Abraham cómo se ven las ofertas en el mapa ANTES de conectar los datos reales de Apify. Úsalos como placeholder inicial en el mapa (reemplázalos después por los puntos reales del pipeline).
- `zonas_contorno_externo_puntos.png` — vista previa de cómo deben verse las 5 zonas (solo contorno externo, sin líneas internas) junto con los puntos de prueba

## Actores de Apify — YA VALIDADOS, usa exactamente estos
1. **Inmuebles24**: `benthepythondev/inmuebles24-scraper`
   - Input: `{"maxResultsPerSearch": N, "searchUrls": [{"url": "https://www.inmuebles24.com/terrenos-en-venta-en-torreon.html"}]}`
   - Confirmado: 84 resultados reales, 14/15 en muestra fueron terrenos correctos en Torreón, trae lat/lon, precio, m², URL.
   - IMPORTANTE: pasar la URL de búsqueda YA ARMADA, no reconstruir con parámetros sueltos (otro actor con parámetros sueltos, `fatihtahta/inmuebles24-scraper`, tiene un bug confirmado: combinar location+property_type regresa 0 resultados para Torreón).

2. **Pincali**: `azzouzana/pincali-com-scraper-by-search-url`
   - Input: `{"maxItems": N, "startUrl": "https://www.pincali.com/inmuebles/terrenos-en-venta-en-torreon-coahuila"}`
   - Confirmado: 5/5 resultados fueron terrenos reales en Torreón. Volumen bajo (~18 terrenos totales en Pincali), pero fuente viva.

3. **Vivanuncios: DESCARTADO.** Los 2 únicos actores disponibles (`stealth_mode/vivanuncios-property-search-scraper` y `jungle_synthesizer/mexico-inmuebles24-metroscubicos-scraper`) fallaron en pruebas reales (uno crashea en 1 segundo, el otro fallo tras 66s probablemente por bloqueo Cloudflare). No los uses. El monitor arranca con 2 fuentes, no 3 — esto debe reflejarse honestamente en el texto de limitaciones del propio dashboard.

## Pipeline técnico a construir
1. `schema.sql` — igual al de Víctor, pero agrega campos: `zona` (de las 5 zonas del geojson), `nombre_colonia` (texto, del geocoding), `fecha_publicacion`.
2. `scraper.py` — llama ambos Actores de Apify (Inmuebles24 + Pincali) con las URLs de arriba.
3. `geocoding.py` (nuevo) — para cada anuncio, si trae dirección en texto (ej. `location.full_address` de Inmuebles24), usa Nominatim (OpenStreetMap, gratis, sin API key) para obtener lat/lng real + nombre de colonia. Si el geocoding falla o la dirección es muy vaga, cae a un punto aleatorio DENTRO del polígono de la zona correspondiente (usa `torreon_zonas_final.geojson` para esto) — nunca random en todo el mapa.
4. `database.py` — igual que el de Víctor (detección de altas/bajas con `activo`), pero:
   - BLINDAR el bug: si `anuncios` llega vacío, no ejecutar el UPDATE de "marcar inactivos" con placeholder vacío (eso marcaría todo como inactivo por error).
   - Filtrar `property_type` del lado del código (no confiar en el filtro del Actor).
5. `api.py` — igual que el de Víctor, pero:
   - Agregar CORS explícito (`fastapi.middleware.cors`) porque el HTML va a hacer fetch() desde otro dominio.
   - Exponer también el geojson de zonas como endpoint estático.
6. `main.py` — orquesta todo: scraper → geocoding → database → (la API ya queda corriendo aparte).
7. **HTML final**: toma el HTML de Claude Design como base, límpialo a HTML/JS estándar, y:
   - Conecta el mapa de calor (Leaflet.heat) a los puntos reales que vengan de la API, no al array de ejemplo.
   - Usa `torreon_zonas_final.geojson` como capa de fondo (solo contorno de línea de color por zona, sin relleno — ve la imagen de referencia).
   - Cada punto de oferta individual debe tener un popup con: nombre de colonia (del geocoding), precio, m², fecha de publicación, y botón/link al anuncio original.
   - Anima SOLO los puntos del mapa (pulso sutil, ciclo de ~1.8s), no el resto del dashboard.

## READMEs
Sigue la convención ya acordada: cada archivo nuevo (scraper.py, database.py, api.py, geocoding.py) debe traer su propio README.md corto explicando qué hace y por qué se tomaron las decisiones técnicas mencionadas arriba (especialmente el descarte de Vivanuncios y el bug del Actor de parámetros sueltos — esto es historial útil si alguien pregunta después por qué no está esa fuente).

## Al final
Cuando todo esté escrito y probado localmente, haz `git add .`, `git commit -m "Pipeline completo: Apify + geocoding + mapa de zonas real"`, y `git push` al repo (ya debería estar configurado como remote si cloné correctamente).
