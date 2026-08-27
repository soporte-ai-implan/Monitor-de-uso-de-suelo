# El cron, paso a paso

Para Víctor. Va en orden; cada paso se verifica antes de seguir al siguiente.

---

## Primero: no hay `index.py`, y eso cambia la pregunta

La duda era "cómo corro el cron en el `index.py`, o el `index.py` en el cron".
La respuesta corta es que ese archivo no existe, y no por olvido.

En un sitio de PHP hay un `index.php` que **se ejecuta cada vez que alguien
entra**. Aquí no pasa eso. Este proyecto tiene dos mitades que **nunca se
tocan**:

```
  main.py                          web/index.html
  ───────                          ──────────────
  el pipeline                      el tablero
  lo dispara el cron               lo abre el visitante
  corre cada 3 días, 40 seg        es HTML, no ejecuta nada
  escribe web/datos.js             lee web/datos.js
```

El único punto de unión es el archivo `web/datos.js`. `main.py` lo **escribe**
al terminar; `index.html` lo **lee** cuando alguien abre la página. No hay
proceso encendido, ni puerto, ni servicio que reiniciar. Apache sirve archivos
estáticos y ya.

Entonces la respuesta es: **el cron corre `main.py`, y nada más.** El tablero se
entera solo, porque el archivo que lee ya cambió.

> Existe `api.py`, que sí es un servidor. **En cPanel no se usa.** Está por si
> algún día hay que servirle los datos a otro sistema. No lo levantes: no hace
> falta y consume un proceso.

---

## Paso 1 — Confirmar que el proyecto corre a mano

Antes de automatizar nada, que funcione tecleándolo. En seco, que no escribe en
la base ni gasta crédito de Apify:

```bash
cd ~/monitor && ./.venv/bin/python main.py --seco --max 20
```

**Qué debe salir:** las tres etapas, `[1/3] Extrayendo de Apify...`,
`[2/3] Geocoding...`, `[3/3] Filtrando y guardando...`, y al final
`(modo seco) No se escribió nada.`

**Si falla aquí, no sigas.** Los errores más comunes:

| Lo que dice | Qué es |
|---|---|
| `APIFY_TOKEN` vacío o inválido | falta el `.env`, o el token está mal |
| `Field input.maxItems must be >= 10` | usaste `--max` menor a 10; el Actor de Pincali no lo acepta |
| `ModuleNotFoundError` | el venv no se creó o no se instalaron los requirements |

---

## Paso 2 — Una corrida de verdad

Ya sin `--seco`. Tarda unos 40-50 segundos:

```bash
cd ~/monitor && ./.venv/bin/python main.py
```

**Qué debe salir al final:**

```
  Dashboard estático actualizado: datos.js (111 terrenos)
  datos_back/: 111 anuncios (anuncios-AAAA-MM-DD.csv, anuncios-AAAA-MM-DD.json)
=== Corrida 'ok' en 47.4s ===
```

Verifica que los archivos se hayan reescrito:

```bash
ls -l ~/monitor/web/datos.js ~/monitor/web/estado.json
```

La fecha de modificación tiene que ser de hace un minuto. Si no cambió, el
pipeline corrió pero no escribió: revisa permisos de escritura sobre `web/`.

Y abre el tablero en el navegador. El sello de arriba debe decir la fecha de
hoy y la etiqueta **"hoy"**, no "hace N días · sin actualizar".

---

## Paso 3 — La carpeta de logs

El cron va a escribir ahí. Si no existe, la línea falla en silencio:

```bash
mkdir -p ~/monitor/logs
```

---

## Paso 4 — Dar de alta el cron

**Por SSH:**

```bash
crontab -e
```

Y agregas esta línea, tal cual, en un renglón:

```
0 3 */3 * * cd ~/monitor && git pull --quiet && ./.venv/bin/python main.py >> logs/corridas.log 2>&1
```

**O por el panel de cPanel:** *Cron Jobs* → *Add New Cron Job*. En el horario
pones `0 3 */3 * *` y en el comando lo que va después del horario.

### Qué dice esa línea, pedazo por pedazo

| Pedazo | Qué hace |
|---|---|
| `0 3 */3 * *` | minuto 0, hora 3, cada 3 días del mes |
| `cd ~/monitor` | el pipeline usa rutas relativas; sin esto no encuentra nada |
| `git pull --quiet` | trae los arreglos que se hayan subido a GitHub |
| `./.venv/bin/python` | el python del venv, **no** el del sistema |
| `>> logs/corridas.log` | acumula la salida en el log |
| `2>&1` | manda también los errores al log, no solo lo normal |

Ese `2>&1` importa: sin él, los errores se van al correo del sistema o a la
basura, y una corrida rota se ve igual que una que nunca corrió.

### Por qué cada 3 días y no diario

Apify cobra **$0.005 por resultado entregado**, y llegan ~125 por corrida
(~120 de Inmuebles24 + 5 de Pincali). Son **$0.60 cada vez**.

| Frecuencia | Corridas/mes | Costo | ¿Cabe en los $5 gratis? |
|---|---|---|---|
| Diario | 30 | ~$18 | No, se apaga al día 8 |
| **Cada 3 días** | ~10 | **~$6** | Se pasa ~$1 |
| Semanal (`0 3 * * 1`) | 4.3 | ~$2.60 | Sí, holgado |

Cada 3 días se pasa del crédito gratuito por poco: alcanza para unas 8 corridas
y las últimas 2 del mes no correrían. **Si a fin de mes el tablero se queda
quieto, es esto, no una falla.**

> **No bajes `MAX_RESULTADOS_POR_FUENTE` para gastar menos.** Ese número es un
> techo de seguridad, no un pedido: Apify cobra por lo que entrega, no por lo
> que pides, así que bajarlo casi no ahorra. Y rompe el monitor en silencio —
> los anuncios que quedan fuera del tope no llegan, y lo que no llega se lee
> como desaparecido. La corrida reportaría decenas de bajas falsas y el tablero
> diría que se vendió medio Torreón en un día. **La perilla del costo es la
> frecuencia de esta línea.**

---

## Paso 5 — Comprobar que quedó

```bash
crontab -l
```

Debe aparecer tu línea. Si no, no se guardó.

---

## Paso 6 — Probar sin esperar 3 días

No te esperes al día 3 para descubrir que estaba mal. Pon una línea temporal
que corra en 2 minutos, míralo, y bórrala:

```bash
crontab -e
# agrega, ajustando la hora a "dentro de 2 minutos":
#   35 14 * * * cd ~/monitor && ./.venv/bin/python main.py >> logs/prueba.log 2>&1
```

Espera, y luego:

```bash
cat ~/monitor/logs/prueba.log
```

Si ves las tres etapas y `Corrida 'ok'`, el cron funciona. **Borra esa línea de
prueba** y quédate con la de cada 3 días.

Este paso es el que más problemas destapa, porque el cron corre con un entorno
distinto al de tu sesión de SSH: otro `PATH`, otro directorio inicial, a veces
otro shell. Un comando que funciona tecleado puede fallar en cron por eso, y
`2>&1` es lo que te lo deja ver.

---

## Cómo saber después si está corriendo

**Sin entrar al servidor**, desde cualquier navegador:

```
monitor.trcimplan.gob.mx/estado.json
```

Trae la fecha de la última corrida, el estatus y cómo respondió cada portal. Se
escribe también cuando la corrida **falla**, con el motivo — si solo se
escribiera al terminar bien, una corrida rota se vería igual que un cron que
nunca se disparó, y son problemas distintos.

**Desde el servidor**, las últimas líneas del log:

```bash
tail -40 ~/monitor/logs/corridas.log
```

---

## Si algo sale mal

| Síntoma | Causa probable |
|---|---|
| El log está vacío | el cron no se disparó; revisa `crontab -l` |
| `python: command not found` | falta el `./.venv/bin/` en la ruta del comando |
| `No such file or directory` | falta el `cd ~/monitor &&` al principio |
| Corre pero `datos.js` no cambia | permisos de escritura sobre `web/` |
| `estatus: parcial` | un portal no respondió. **No es error**: el monitor sigue con el otro y no da de baja lo del portal caído |
| El tablero dice "sin actualizar" | el cron no está corriendo, o se acabó el crédito de Apify |

Para volver atrás una corrida que ensució los datos, hay copias de las últimas 7
en `~/monitor/respaldos/`:

```bash
cp ~/monitor/respaldos/terrenos-AAAA-MM-DD.db ~/monitor/terrenos.db
```
