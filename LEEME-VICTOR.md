# Monitor de Suelo — migración de Railway a cPanel

Víctor: esto es el pipeline que arrancó de tu código base, ya con las fuentes
reales conectadas. Corre en Railway desde el 27/07 y se va a mover al hosting
de IMPLAN. El repo completo está en
`github.com/soporte-ai-implan/Monitor-de-uso-de-suelo`.
(El repo `Monitor-Terrenos-Demo` era la demo; ya no se usa.)

## Qué es cada cosa

```
monitor/            el proyecto completo, va en ~/monitor (fuera de public_html)
  main.py           orquesta: scraper -> geocoding -> compuertas -> sqlite
  web/              ESTO es lo que se publica. El pipeline reescribe web/datos.js
  data/*.geojson    zonas y límite municipal
  docs/             una nota por módulo con el porqué de cada decisión
  tests/            4 suites, corren sin token y sin red

Monitor de Suelo - IMPLAN Torreon.html
                    el mismo tablero en un archivo autocontenido, por si hay
                    que enseñarlo sin servidor. No es lo que se publica.

geojson/            los polígonos sueltos, por si los quieren en otro sistema
```

Arquitectura: **no hay API en producción**. Los datos cambian una vez al día, así
que el tablero es estático y lee `web/datos.js` como `<script src>`. Sin
procesos encendidos, sin puertos, sin CORS. `api.py` existe y funciona, pero
para cPanel no hace falta.

## Instalación (una sola vez)

```bash
cd ~ && git clone git@github.com:soporte-ai-implan/Monitor-de-uso-de-suelo.git monitor
cd ~/monitor && bash tools/instalar_cpanel.sh
```

El clone es por SSH porque el cron hace `git pull` solo, sin nadie enfrente.
Requiere una llave de despliegue: genérala en el servidor con
`ssh-keygen -t ed25519 -C "cpanel-implan"` **sin passphrase** (con passphrase
el cron se atora pidiéndola) y sube la pública en el repo, Settings -> Deploy
keys, sin permiso de escritura. Comprueba con `ssh -T git@github.com` antes de
seguir.

El script comprueba el terreno **antes** de tocar nada —versión de Python,
salida a internet hacia Apify y Nominatim, permisos de escritura— y se detiene
con el motivo si algo falta, en vez de instalar a medias y fallar tres pasos
después. Si pasa, crea el venv, instala dependencias, corre las 5 suites y te
imprime la línea de cron y el symlink ya con tus rutas.

La comprobación de salida a internet es la que más se pasa por alto: muchos
hostings compartidos la bloquean, y sin ella el pipeline no puede llamar a
Apify aunque Python funcione. Si eso falla, el camino es otro (el C de
`docs/despliegue_cpanel.md`) y conviene saberlo en el minuto uno.

Si prefieres a mano, es lo de siempre:

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
```

El código compila desde **Python 3.8**, aunque el objetivo es 3.9 o mayor. Sin
dependencias binarias a propósito.

El point-in-polygon está escrito a mano en `zonas.py` justo para no arrastrar
shapely ni GDAL, que en hosting compartido son la principal fuente de dolor.

### El `.env`

No viene en el paquete. El token sale de la cuenta de Apify de
`soporte-ai-implan`, a la que ya tienes acceso: Settings → Integrations → API
tokens. Créalo en `~/monitor/.env`:

```
APIFY_TOKEN=<el token>
NOMINATIM_CONTACTO=soporte-ai@trcimplan.gob.mx
MAX_RESULTADOS_POR_FUENTE=200
```

### Publicar

El subdominio `monitor.trcimplan.gob.mx` apuntando a `~/monitor/web`, o bien:

```bash
ln -s ~/monitor/web ~/public_html/monitor
```

Lo importante es que la carpeta publicada **sea** `~/monitor/web`, no una copia:
así el cron escribe directo sobre lo que se sirve y nadie tiene que mover
archivos.

### El cron

Una línea, una vez. A partir de ahí se actualiza solo:

```
0 3 * * 1   cd ~/monitor && git pull --quiet && ./.venv/bin/python main.py >> logs/corridas.log 2>&1
```

`mkdir ~/monitor/logs` antes, si no existe.

**Corre semanal, los lunes a las 3, y es a propósito.** El Actor de Inmuebles24
cobra $0.005 por resultado y devuelve ~120 por corrida: $0.60 cada vez. A diario
son ~$18 al mes contra $5 de crédito gratuito, o sea que se apaga solo a los
ocho días y va a parecer que se rompió. Semanal son ~$2.60 al mes y cabe con
holgura.

No se pierde casi nada: los anuncios de suelo duran semanas publicados. Lo
único que baja es la resolución de las altas y bajas, que pasa a ±7 días. Si más
adelante se contrata plan de Apify, se sube a diario cambiando el `1` final por
un `*`.

**Lo que NO hay que hacer es bajar `MAX_RESULTADOS_POR_FUENTE`.** Es tentador
—"si son 120, que traiga 15"— pero rompe el monitor en silencio: los 105 que no
llegaron se leen como desaparecidos y el blindaje de `database.py` no alcanza a
protegerlos, porque solo detecta fuentes que devuelven cero, no fuentes que
devuelven de menos. La primera corrida reportaría ~105 bajas falsas y el
tablero diría que se vendió el 85% del suelo de Torreón en un día. El tope tiene
que quedar por encima del inventario real; la frecuencia es la perilla del
costo, no el volumen.

El `git pull` es a propósito: así los arreglos suben por GitHub y no hace falta
que nadie entre al servidor a desplegar. Todo lo que se empuja pasa antes por
las 5 suites de `tests/`. Si prefieres que no jale solo, quítalo y lo corres tú
cuando te avise.

### Cómo saber si corrió, sin entrar al servidor

Cada corrida escribe `web/estado.json`, que queda publicado junto al tablero:

```
monitor.trcimplan.gob.mx/estado.json
```

Trae la fecha de la última corrida, el estatus, cuántos terrenos se publicaron
y cómo respondió cada portal. Se escribe también cuando la corrida falla, con el
motivo — si solo se escribiera al terminar bien, una corrida rota se vería igual
que un cron que nunca se disparó, y son problemas distintos. Si la fecha se
queda atrás varios días, entonces sí el cron no está corriendo.

Con eso yo puedo revisar el estado desde el navegador y no molestarte para
leer el log.

### Probar antes de dejarlo solo

```bash
cd ~/monitor && ./.venv/bin/python main.py --seco --max 20
```

`--seco` no escribe en la base ni gasta de más. Si eso corre, quita `--seco`,
verifica que se haya reescrito `web/datos.js` y abre el tablero.

## Qué cambió desde que se escribió esta nota

Todo esto ya está en la rama `claude/monitor-implan-railway-jhwtju` y pasa las
5 suites de `tests/`.

**El pipeline ahora cierra el ciclo solo.** `main.py` no se limita a reescribir
`web/datos.js`: también reclasifica zonas y vuelve a armar el HTML
autocontenido. Antes había que empaquetarlo a mano, así que el archivo que se
mandaba por correo decía "actualizado el 1 de agosto" con el cron corriendo al
día.

**Las zonas se reclasifican en cada corrida** (`database.reclasificar_zonas()`).
La zona se asignaba solo al dar de alta un anuncio, nunca después, así que la
base acumulaba reglas de distintas épocas: había una fila guardada como "Zona 2
/ borde" cuyas coordenadas caen fuera del municipio según las reglas de hoy. El
tablero la descartaba y la base la seguía contando — de ahí que la pantalla
mostrara 97 y 98 a la vez. No borra nada: lo que cae fuera conserva su motivo.

**Pincali sí sirve, y el problema era nuestro.** Se corrió el Actor a mano con
la URL y el input de producción. Dos hallazgos distintos:

- El tope de ~5 anuncios lo pone el Actor por ser cuenta gratuita, con este
  mensaje suyo: *"free accounts have limited data extraction"*. La URL y el
  input estaban bien.
- `areaM2` viene `null` en todos, pero la superficie **sí** llega, en
  `features` como texto (`"601.15 m² de terreno"`). `normalizar_pincali()` solo
  miraba `areaM2`, así que se tiraba la superficie de anuncios ya pagados. Lo
  resuelve `_m2_pincali()`; ojo al tocarlo, porque en `features` conviven
  renglones de largo y frente que no son superficie.

**El tablero se refresca solo también en estático.** Preguntaba cada hora a
`/api/monitor-terrenos`, lo cual solo sirve donde hay API. Ahora además consulta
`estado.json` y, si trae una corrida más nueva, recarga para tomar los archivos
regenerados. Una sola recarga por corrida, para no quedarse en círculo.

## Lo que hay que decidir antes de dejarlo solo

**El costo de Apify.** Resuelto bajando el cron a semanal (ver la sección del
cron, arriba): ~$2.60 al mes contra $5 de crédito gratuito. Queda pendiente
decidir si se contrata plan para volver a diario, pero ya no es urgente y el
monitor no se va a apagar solo a mitad de mes.

### `terrenos.db`: dónde vive y cómo no perderla

La base se crea sola en la primera corrida, así que el pipeline arranca sin
problema. Vive en `~/monitor/terrenos.db`, junto al código, y como el cron corre
ahí mismo no hay volumen que montar ni nada que configurar. (`DATOS_DIR` la
mueve a otro lado si algún día hace falta; era indispensable en Railway, donde
el disco se borraba en cada redeploy, y en cPanel no lo es.)

**Cada corrida deja una copia antes de tocarla**, en `~/monitor/respaldos/`, y
se conservan las últimas 7. Se hace con la API `backup()` de sqlite y no
copiando el archivo, porque copiar a mano durante una escritura deja una base
corrupta y el punto es tener a qué volver. Si una corrida ensucia los datos:

```bash
cp ~/monitor/respaldos/terrenos-AAAA-MM-DD.db ~/monitor/terrenos.db
```

**La base de Railway trae el historial real** —altas, bajas, cambios de precio y
`fecha_primera_vista` desde el 27/07— y **no se puede reconstruir**, porque los
portales no publican cuándo apareció cada anuncio. Cuando aparezca, va así:

```bash
# con el cron detenido, para que no escriba a media copia
cp ~/monitor/terrenos.db ~/monitor/respaldos/antes-de-railway.db   # por si acaso
cp /donde/hayas/bajado/terrenos.db ~/monitor/terrenos.db
cd ~/monitor && ./.venv/bin/python main.py --seco --max 20         # que abra bien
```

Los días en el mercado no dependen de ella (se calculan contra
`fecha_publicacion`, que viene del portal), pero las altas, las bajas y los
cambios de precio sí: sin base previa, la primera corrida reporta todo como
nuevo.

**La serie histórica todavía se reconstruye.** Las tablas `corridas` e
`historial_precios` existen pero el payload no las publica, así que la gráfica
de tendencia se arma con la mediana por mes de publicación de la oferta
vigente. No es un índice de precios y el tablero no lo presenta como tal. En
cuanto se acumulen corridas diarias reales, basta publicar la serie como
`DATOS_MONITOR.serie` y el frontend la toma sola, sin tocar nada.

**Railway trae código viejo** (commit `577e02b`). Cuando cPanel quede probado se
apaga. Mientras tanto conviene no dejar los dos escribiendo sobre lo mismo.

## Si el hosting no deja correr el cron

Entonces `web/` se publica igual como estático y el pipeline corre en otro lado;
alguien sube `datos.js` después de cada corrida. Funciona, pero deja de ser
desatendido. `docs/despliegue_cpanel.md` tiene los tres caminos con sus
concesiones.
