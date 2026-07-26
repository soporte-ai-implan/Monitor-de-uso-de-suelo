# Poner el monitor en automático

Hay dos caminos. **Para IMPLAN recomiendo el programador del sistema operativo**,
no el scheduler en proceso: sobrevive reinicios sin configurar un servicio, y si
una corrida truena no se lleva al proceso entero.

## Qué tan seguido conviene correrlo

El inventario real es de ~100 terrenos entre los dos portales, y una oferta de
suelo no cambia por hora: los anuncios duran semanas o meses publicados.

**Recomendación: 1 vez al día, de madrugada.** Diario detecta altas y bajas con
buena resolución sin gastar crédito de Apify de más ni presionar a los portales.
Correrlo cada hora no daría información nueva y multiplicaría el costo por 24.

Si Abraham quiere que el dashboard diga "tiempo real", vale la pena aclarar que
lo honesto es **"actualizado diariamente"** — el sello de fecha del dashboard ya
muestra la fecha de la última corrida, así que nadie se confunde.

## Opción A — Programador de tareas de Windows (recomendada)

Registrar la tarea, corriendo diario a las 3:00 AM:

```bash
schtasks /create /tn "Monitor Suelo IMPLAN" /tr "cmd /c cd /d \"C:\ruta\al\repo\" && python main.py >> logs\corridas.log 2>&1" /sc daily /st 03:00 /rl highest
```

Verificar que quedó registrada:

```bash
schtasks /query /tn "Monitor Suelo IMPLAN" /v /fo list
```

Dispararla a mano para probar, sin esperar a las 3 AM:

```bash
schtasks /run /tn "Monitor Suelo IMPLAN"
```

Borrarla:

```bash
schtasks /delete /tn "Monitor Suelo IMPLAN" /f
```

Notas:
- La ruta del repo debe ir completa; la tarea no arranca en el directorio del
  proyecto por su cuenta (de ahí el `cd /d`).
- Si el servidor usa un entorno virtual, apunta al Python del venv:
  `.venv\Scripts\python.exe main.py`.
- La tarea necesita correr con un usuario que tenga permiso de escribir la base
  y el log.

## Opción B — cron (si el monitor va a un servidor Linux)

```bash
0 3 * * * cd /opt/monitor-suelo && /opt/monitor-suelo/.venv/bin/python main.py >> logs/corridas.log 2>&1
```

## Opción C — scheduler en proceso

Ya está escrito en `scheduler.py`, para el caso en que se pueda dejar un servicio
corriendo:

```bash
python scheduler.py --horas 24 --ahora
```

Usa APScheduler con tres protecciones que vale la pena conocer:

- `max_instances=1` — nunca dos corridas encimadas.
- `coalesce=True` — si el proceso estuvo dormido y se acumularon disparos, corre
  una sola vez al despertar, no seis.
- `misfire_grace_time=3600` — tolera una hora de atraso antes de saltarse el turno.

Si una corrida truena, el error se registra y **el scheduler sigue vivo** para
intentar la siguiente.

Desventaja frente a la opción A: si el servidor se reinicia, hay que volver a
levantar el proceso a mano (o envolverlo en un servicio de Windows / unidad
systemd, que es más trabajo que la tarea programada).

## Cómo saber si está funcionando

La tabla `corridas` es la bitácora. Desde la API:

```bash
curl http://localhost:8000/api/corridas?limite=7
```

Cada renglón trae `estatus` (`ok`, `parcial`, `error`), cuántos anuncios crudos
llegaron, altas, bajas, y un JSON con el desglose por fuente.

**`estatus = 'parcial'` significa que una de las dos fuentes falló.** Vale la pena
revisarlo: si Inmuebles24 empieza a fallar seguido, probablemente cambió su HTML
y hay que revisar el Actor.

Y `GET /salud` da la respuesta corta de si la API vive y cuándo fue la última
corrida — sirve para un uptime check externo.

## Antes de programarla

Probar la corrida completa una vez a mano, en modo seco (no escribe en la base):

```bash
python main.py --seco --max 20
```

Si eso pasa, quitar `--seco` y programarla.
