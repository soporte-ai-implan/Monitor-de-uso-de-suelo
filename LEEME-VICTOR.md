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
0 3 */3 * *   cd ~/monitor && git pull --quiet && ./.venv/bin/python main.py >> logs/corridas.log 2>&1
```

`mkdir ~/monitor/logs` antes, si no existe.

**Corre cada 3 días, a las 3 de la mañana.** `*/3` es día del mes, así que en
meses de 31 días el salto de fin de mes queda de un día en vez de tres. No
importa para esto.

### La cuenta del costo, con los números medidos

Apify cobra **por resultado entregado**, no por el tope que uno pide. Son cosas
distintas y conviene no confundirlas:

| | |
|---|---|
| `MAX_RESULTADOS_POR_FUENTE=200` | el **techo**. Nunca se alcanza; es una red |
| ~120 de Inmuebles24 + 5 de Pincali | lo que de verdad llega, medido el 27/08 |
| $0.005 por resultado | tarifa del Actor de Inmuebles24 en cuenta gratuita |

O sea **$0.60 por corrida**, no $1.00. El 200 solo se cobraría si el inventario
de terrenos en Torreón creciera a 200, y ahí ya tendríamos un problema más
interesante que la factura.

| Frecuencia | Corridas/mes | Costo | ¿Cabe en los $5 gratis? |
|---|---|---|---|
| Diario | 30 | ~$18 | No, se apaga a los 8 días |
| **Cada 3 días** | ~10 | **~$6** | **Se pasa ~$1** |
| Semanal | 4.3 | ~$2.60 | Sí, con holgura |

Cada 3 días **se pasa del crédito gratuito por poco**: alcanza para unas 8
corridas y las últimas 2 del mes no correrían. Es una decisión tomada a
sabiendas, porque da mejor resolución de altas y bajas (±3 días en vez de ±7).
Si al final de algún mes el tablero se queda quieto, es esto y no una falla:
`estado.json` deja de avanzar y el crédito de Apify aparece en cero. Se arregla
con un plan de pago barato, o volviendo a semanal (`0 3 * * 1`).

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

**El costo de Apify.** Acotado bajando el cron a cada 3 días: ~$6 al mes contra
$5 de crédito gratuito (ver la cuenta completa en la sección del cron). Se pasa
por poco y a sabiendas. Queda por decidir si se contrata un plan barato o si se
baja a semanal, que sí cabe holgado.

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

### El historial del 27/07 al 27/08 se perdió

Hay que decirlo con todas sus letras porque afecta cómo se lee el tablero. La
base que vivía en el volumen de Railway traía las altas, las bajas, los cambios
de precio y la `fecha_primera_vista` de ese mes. Railway se apagó antes de
exportarla y **no se puede reconstruir**: los portales no publican cuándo
apareció cada anuncio, así que ese dato no existe en ningún otro lado.

**La serie arranca de cero el 27/08/2026.** Consecuencias concretas:

- La primera corrida reportó los 111 terrenos como `nuevos` y 0 bajas. No es un
  error: es una base vacía viendo el inventario por primera vez. Se corrige sola
  a partir de la segunda corrida.
- **Los días en el mercado sí son correctos desde el día uno**, porque se
  calculan contra `fecha_publicacion`, que viene del portal y no de nuestra
  base. Por eso el tablero ya puede decir "60 días de mediana" sin haber
  observado esos 60 días.
- Lo que no se puede responder todavía es "cuántos terrenos se dieron de baja
  este mes" ni "a cuáles les bajaron el precio". Eso necesita corridas
  acumuladas y empieza a tener sentido después de varias.

No hay que hacer nada al respecto salvo no borrar `terrenos.db`. Por eso existen
los respaldos de arriba: para que esto no vuelva a pasar. Si alguien apaga o
migra algo que tenga la base adentro, **exportarla es el primer paso, no el
último**.

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
