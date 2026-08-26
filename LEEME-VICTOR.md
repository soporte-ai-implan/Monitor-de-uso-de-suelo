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
cd ~/monitor && python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
```

El clone es por SSH porque el cron tiene que poder hacer `git pull` solo, sin
que nadie teclee una contraseña. Requiere una llave de despliegue: genera una
en el servidor con `ssh-keygen -t ed25519 -C "cpanel-implan"` (sin
passphrase, si no el cron se atora pidiéndola) y sube la pública en el repo,
Settings -> Deploy keys, sin permiso de escritura. Comprueba con
`ssh -T git@github.com` antes de seguir.

Sin dependencias binarias a propósito: el point-in-polygon está a mano en
`zonas.py` justo para no arrastrar shapely/GDAL.

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
0 3 * * *   cd ~/monitor && git pull --quiet && ./.venv/bin/python main.py >> logs/corridas.log 2>&1
```

`mkdir ~/monitor/logs` antes, si no existe.

El `git pull` es a propósito: así los arreglos suben por GitHub y no hace falta
que nadie entre al servidor a desplegar. Todo lo que se empuja pasa antes por
las 4 suites de `tests/`. Si prefieres que no jale solo, quítalo y lo corres tú
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

## Dos cosas que conviene que sepas

**1. Pincali está caído desde el 29/07.** El Actor termina `SUCCEEDED` y
devuelve 0 items. El monitor lleva ~4 días corriendo con una sola fuente
(Inmuebles24, ~120 crudos → 98 publicados).

Eso destapó un bug que ya está arreglado: el pipeline contaba "terminó bien" como
"la fuente respondió", así que `fuentes_ok` incluía a Pincali y el blindaje de
bajas de `database.py` archivaba su inventario completo como si se hubiera
vendido. Ahora una fuente que devuelve cero se marca `vacia`, queda fuera de
`fuentes_ok`, la corrida se reporta `parcial` y el tablero lo dice en pantalla.
Está cubierto en `tests/test_scraper.py`.

Queda pendiente ver si el Actor de Pincali se rompió o si Pincali les cambió el
HTML. Es independiente de la migración.

**2. Railway trae código viejo** (commit `577e02b`), o sea el bug sigue vivo
ahí. Cuando cPanel quede probado, se apaga Railway y ya. Mientras tanto conviene
no dejar los dos escribiendo.

## Si el hosting no deja correr el cron

Entonces `web/` se publica igual como estático y el pipeline corre en otro lado;
alguien sube `datos.js` después de cada corrida. Funciona, pero deja de ser
desatendido. `docs/despliegue_cpanel.md` tiene los tres caminos con sus
concesiones.
