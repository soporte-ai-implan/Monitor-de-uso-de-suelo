# Desplegar en el hosting de IMPLAN (cPanel)

El correo `soporte-ai@trcimplan.gob.mx` vive en un cPanel — el mismo servidor de
`trcimplan.gob.mx`. Eso significa que IMPLAN **ya tiene dónde alojar el
monitor**, pagado y con dominio institucional. Dos ventajas sobre Railway:

- ya está pagado (el trial de Railway es 30 días o $5)
- `monitor.trcimplan.gob.mx` pesa distinto ante un consejo que una URL de Railway

## Paso 0 — averiguar qué permite el hosting

Todo depende de esto. Entra a cPanel y busca en el menú:

| Buscar | Dónde suele estar | Para qué |
|---|---|---|
| **Setup Python App** (o *Python Selector*, *Application Manager*) | Software | correr la API completa |
| **Cron Jobs** | Advanced | la corrida diaria |
| **Terminal** o acceso SSH | Advanced | instalar dependencias |
| **Subdominios** | Domains | `monitor.trcimplan.gob.mx` |

Según lo que haya, hay tres caminos. **El B es el recomendado** aunque tengas
Python App disponible: es el más simple y el que menos se rompe solo.

---

## Camino B (recomendado) — dashboard estático + cron diario

**Requiere:** Cron Jobs y `python3` en el servidor. No requiere Setup Python App.

La idea: como los datos cambian una vez al día, **el dashboard no necesita una
API viva**. La corrida diaria escribe `web/datos.js` y el HTML lo lee como
archivo estático. Sin procesos encendidos, sin puertos, sin CORS.

### 1. Subir el proyecto

Por Git desde Terminal de cPanel:

```bash
cd ~ && git clone https://github.com/soporte-ai-implan/Monitor-Terrenos-Demo.git monitor
```

O por File Manager, subiendo un ZIP del repo y descomprimiéndolo en `~/monitor`.

### 2. Instalar dependencias

```bash
cd ~/monitor && python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
```

Si el hosting no deja crear entornos virtuales, prueba con `pip3 install --user`.

### 3. El archivo `.env`

Créalo en `~/monitor/.env` con el token. **Nunca por Git.**

```
APIFY_TOKEN=el_token_de_apify
NOMINATIM_CONTACTO=soporte-ai@trcimplan.gob.mx
MAX_RESULTADOS_POR_FUENTE=200
```

No hace falta `SCHEDULER_EN_API` ni `DATOS_DIR`: aquí el cron manda y el disco
es persistente de por sí.

### 4. Publicar el dashboard

Crea el subdominio `monitor.trcimplan.gob.mx` apuntando a `~/monitor/web`, o si
prefieres una subcarpeta del sitio actual, enlaza:

```bash
ln -s ~/monitor/web ~/public_html/monitor
```

Con eso el dashboard queda en `trcimplan.gob.mx/monitor`.

### 5. La corrida diaria

En **Cron Jobs**, una tarea a las 3:00 AM (`0 3 * * *`):

```bash
cd ~/monitor && ./.venv/bin/python main.py >> logs/corridas.log 2>&1
```

Cada corrida regenera `web/datos.js`, y el dashboard sirve datos nuevos sin que
nadie toque nada.

### 6. Probar antes de dejarlo solo

```bash
cd ~/monitor && ./.venv/bin/python main.py --seco --max 20
```

Si eso corre, quita `--seco`, verifica que aparezca `web/datos.js`, y abre el
dashboard en el navegador.

---

## Camino A — la API completa (si hay Setup Python App)

Solo vale la pena si más adelante quieren datos en vivo o que otros sistemas de
IMPLAN consuman la API.

1. **Setup Python App** → Python 3.9+, raíz de la aplicación `monitor`, URL
   `monitor` (o el subdominio), *Application startup file* `passenger_wsgi.py`.
2. Instalar dependencias desde la misma pantalla o por Terminal.
3. Crear `passenger_wsgi.py` en la raíz del proyecto:

   ```python
   from api import app as application
   ```

4. Variables de entorno en la misma pantalla de Setup Python App: las del
   Camino B más `SCHEDULER_EN_API=1` si quieres que la API corra el pipeline
   sola, o déjalo apagado y usa un cron como en el Camino B (más confiable en
   hosting compartido, donde Passenger duerme los procesos inactivos).

> **Ojo:** en shared hosting Passenger apaga la aplicación cuando no recibe
> peticiones. Un scheduler dentro del proceso puede no dispararse nunca. Por eso
> aun teniendo Camino A conviene la corrida por cron.

---

## Camino C — solo archivos estáticos, sin Python

Si el hosting no corre Python de ninguna forma:

1. El pipeline corre en otro lado (tu máquina o Railway).
2. Después de cada corrida, subes `web/datos.js` por FTP o File Manager.
3. El dashboard vive en cPanel como archivos estáticos.

Funciona, pero alguien tiene que subir el archivo. No sirve para una semana
desatendida.

---

## Qué subir en cualquier caso

La carpeta `web/` completa: `index.html`, `geo.js`, `zonas.js`,
`puntos_demo.js` y `datos.js` (este último lo genera el pipeline; si aún no
existe, el dashboard muestra los puntos de ejemplo y lo dice en pantalla).

## Recomendación de secuencia

Como quedan pocos días antes del viaje:

1. **Deja Railway funcionando primero.** Es el respaldo que ya sirve.
2. Prueba cPanel en paralelo, sin prisa.
3. Si cPanel queda listo y probado, apaga Railway. Si no, la semana corre en
   Railway y la migración se hace al regreso.

Lo que no conviene es quedarse sin ninguno de los dos a media semana.
