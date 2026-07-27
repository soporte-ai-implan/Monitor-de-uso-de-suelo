# Desplegar en Railway

Objetivo: que el monitor corra solo una semana, sin nadie encendiendo nada, y
que cualquiera pueda ver el dashboard desde una URL.

La arquitectura para esto es **un solo servicio** que hace las tres cosas:

1. sirve el dashboard en `/`
2. sirve los datos en `/api/...`
3. corre el pipeline por dentro cada 24 h

## Por qué un solo servicio y no dos

Lo natural sería un servicio web y un cron aparte. No funciona con SQLite: en
Railway **un volumen persistente no se puede montar en dos servicios a la vez**,
y ambos necesitan la misma base. Un cron separado escribiría en su propia copia
efímera y el dashboard nunca vería esos datos.

Por eso la API trae el scheduler adentro (`SCHEDULER_EN_API=1`), en un hilo
aparte para no bloquear las peticiones mientras scrapea.

## Paso 1 — subir el repo

Railway despliega desde GitHub. El repo ya tiene lo necesario: `Procfile`
(comando de arranque), `.python-version` y `requirements.txt`.

> **Ojo con la versión de Python.** El proyecto se desarrolló en 3.14, que es muy
> nueva y puede que Railway todavía no la tenga. `.python-version` la fija en
> **3.12**, que tiene wheels precompilados para todo. Si el build falla por
> versión, ese es el archivo que hay que mover.

## Paso 2 — el volumen persistente (NO te lo saltes)

En el servicio → **Variables / Settings → Volumes** → agregar un volumen y
montarlo en `/data`.

Sin esto, cada redeploy borra `terrenos.db` y **se pierde el historial de altas
y bajas**. El monitor seguiría corriendo, pero cada corrida se vería como si
todos los terrenos fueran nuevos: se pierde exactamente lo que demuestra que
el sistema sirve.

También ahí vive el cache de geocoding. Sin él, cada corrida le vuelve a pedir
a Nominatim direcciones ya resueltas, a 1 petición por segundo — que es justo
el patrón de uso por el que bloquean.

## Paso 3 — variables de entorno

En Railway → **Variables**:

| Variable | Valor | Para qué |
|---|---|---|
| `APIFY_TOKEN` | tu token | **el único secreto** |
| `SCHEDULER_EN_API` | `1` | que la API corra el pipeline sola |
| `DATOS_DIR` | `/data` | apuntar al volumen del paso 2 |
| `INTERVALO_HORAS` | `24` | una corrida al día |
| `NOMINATIM_CONTACTO` | `soporte-ai@trcimplan.gob.mx` | requisito de OpenStreetMap |
| `MAX_RESULTADOS_POR_FUENTE` | `200` | holgura sobre los ~102 reales |

El `.env` **no se sube** (está en `.gitignore`); en el servidor las variables se
configuran en el panel.

`SCHEDULER_EN_API` va en `1` **solo aquí**. En tu máquina déjalo apagado, si no
cada vez que levantes la API local se pondría a scrapear y a gastar crédito.

## Paso 4 — verificar que quedó bien

Con la URL que te dé Railway:

| Revisar | Qué debe pasar |
|---|---|
| `https://TU-URL/` | carga el dashboard con el mapa |
| `https://TU-URL/salud` | `{"ok": true, ...}` |
| `https://TU-URL/api/corridas` | vacío al principio; **con una corrida tras la primera noche** |
| `https://TU-URL/api/monitor-terrenos` | `total` mayor a 0 después de esa corrida |

La primera corrida arranca ~30 segundos después de que el servicio levanta, y
luego cada 24 h.

Si `/` carga pero el mapa sale con los puntos de ejemplo, es que aún no hay
corridas o todas fallaron: checa `/api/corridas`.

## Cómo vigilarlo desde Cancún

Todo desde el celular, sin terminal:

- **`/api/corridas`** — la bitácora. Cada renglón trae `estatus` (`ok`,
  `parcial`, `error`), cuántos anuncios entraron, altas y bajas, y el desglose
  por fuente. Si el último es `error`, ahí dice por qué.
- **`estatus: "parcial"`** significa que una de las dos fuentes falló. No es
  grave —la otra siguió— pero si se repite varios días, ese portal cambió algo.
- **Consola de Apify → Runs** — el gasto por corrida y si algún Actor tronó.
- **Logs de Railway** — si el servicio se cayó del todo.

## Qué pasa si algo falla mientras no estás

El sistema está hecho para degradar sin romperse:

- **Una corrida truena** → queda registrada como `error`, el servicio sigue
  arriba y reintenta en 24 h. El dashboard mantiene los últimos datos buenos.
- **Una fuente truena** → la otra sigue, y los anuncios de la fuente caída
  **no** se dan de baja (blindaje 2 en `database.py`). No aparecen bajas falsas.
- **Ninguna fuente responde** → no se toca la base. El dashboard queda
  congelado en los últimos datos válidos, que es mejor que vaciarse.
- **Se acaba el crédito de Apify** → las corridas fallan y quedan como `error`,
  pero el dashboard sigue sirviendo los últimos datos. Vale la pena revisar el
  saldo a mitad de semana.

Lo que **no** se recupera solo: si Railway tira el servicio por falta de
recursos o el build falla en un redeploy. Por eso conviene no tocar el repo
durante la semana de prueba — cada push dispara un redeploy.

## Estimación de costo de Apify

El plan gratuito da $5 USD al mes. Una corrida de prueba con 25 resultados
consumió centavos; la corrida completa pide ~102 (84 de Inmuebles24 + 18 de
Pincali), o sea 4-5 veces más.

Siete corridas diarias deberían caber en los $5, pero es apretado y no está
medido. **Después de la primera corrida completa, checa el costo exacto en
Apify → Runs y multiplícalo por 7.** Si no cabe, baja
`MAX_RESULTADOS_POR_FUENTE` o pon `INTERVALO_HORAS=48`.
