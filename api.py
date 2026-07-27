"""
api.py — sirve los datos al dashboard.

CORS explícito porque el HTML se sirve desde otro dominio (trcimplan.gob.mx)
o desde file:// durante las demos, y sin encabezados el navegador bloquea el
fetch() sin decir por qué.

Arrancar:  uvicorn api:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import pathlib
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import database
import zonas

load_dotenv()

RAIZ = pathlib.Path(__file__).resolve().parent
WEB = RAIZ / "web"

log = logging.getLogger("monitor.api")

# En un contenedor (Railway) conviene un solo servicio con la API y el
# scheduler adentro: un volumen persistente no se puede compartir entre dos
# servicios, y la base tiene que ser la misma para ambos.
SCHEDULER_EN_API = os.getenv("SCHEDULER_EN_API", "0") == "1"
INTERVALO_HORAS = float(os.getenv("INTERVALO_HORAS", "24"))


@contextlib.asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    tarea = None
    if SCHEDULER_EN_API:
        tarea = asyncio.create_task(_bucle_corridas())
        log.info("scheduler integrado activo: cada %s horas", INTERVALO_HORAS)
    else:
        log.info("scheduler integrado apagado (SCHEDULER_EN_API != 1)")
    try:
        yield
    finally:
        if tarea:
            tarea.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await tarea


def _horas_desde_ultima_corrida() -> float | None:
    """Horas transcurridas desde la última corrida que terminó. None si no hay."""
    corrida = database.ultima_corrida()
    if not corrida or not corrida.get("fin"):
        return None
    try:
        fin = datetime.fromisoformat(corrida["fin"])
    except (ValueError, TypeError):
        return None
    return (datetime.now() - fin).total_seconds() / 3600


def _toca_correr() -> bool:
    """
    Decide si toca corrida, mirando la bitácora en vez de confiar en el reloj
    del proceso.

    Sin esto, cada reinicio del contenedor dispararía una corrida nueva: veinte
    reinicios, veinte llamadas a Apify. Es la forma más fácil de vaciar el
    crédito en un día sin que nadie lo note, y de que la prueba muera sola.
    """
    horas = _horas_desde_ultima_corrida()
    if horas is None:
        log.info("no hay corridas previas: toca correr")
        return True
    if horas >= INTERVALO_HORAS:
        log.info("última corrida hace %.1f h (>= %.1f): toca correr", horas, INTERVALO_HORAS)
        return True
    log.info(
        "última corrida hace %.1f h (< %.1f): se omite, probablemente un reinicio",
        horas, INTERVALO_HORAS,
    )
    return False


async def _bucle_corridas() -> None:
    """
    Corre el pipeline cada INTERVALO_HORAS sin tumbar la API si algo falla.

    Se ejecuta en un hilo aparte porque el pipeline es bloqueante (red, SQLite)
    y si corriera en el bucle de eventos dejaria la API sin responder por
    minutos, justo mientras alguien mira el dashboard.
    """
    import main as pipeline

    # Espera inicial: que la API quede lista antes de la primera corrida.
    await asyncio.sleep(30)
    while True:
        try:
            if _toca_correr():
                log.info("disparando corrida programada")
                r = await asyncio.to_thread(pipeline.correr_monitor)
                log.info("corrida '%s' terminada", r.get("estatus"))
        except asyncio.CancelledError:
            raise
        except Exception:
            # Una corrida fallida no debe tumbar el servicio: queda registrada
            # en la tabla `corridas` y se reintenta en el siguiente turno.
            log.exception("la corrida falló; el servicio sigue arriba")

        # Se revisa cada hora, pero _toca_correr() decide si de verdad procede.
        # Asi el intervalo lo manda la bitacora persistente, no el proceso.
        await asyncio.sleep(min(3600, INTERVALO_HORAS * 3600))


app = FastAPI(
    title="API Monitor de Suelo — IMPLAN Torreón",
    description="Oferta de terrenos en venta en Torreón, vía Inmuebles24 y Pincali.",
    version="1.0.0",
    lifespan=ciclo_de_vida,
)

# En produccion conviene acotar a los dominios reales; se deja configurable.
# '*' con allow_credentials=False es valido y es lo que necesita el dashboard.
origenes = os.getenv("CORS_ORIGENES", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in origenes],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api")
def indice_api():
    return {
        "servicio": "Monitor de Suelo IMPLAN Torreón",
        "endpoints": [
            "/api/monitor-terrenos",
            "/api/zonas",
            "/api/resumen",
            "/api/corridas",
            "/salud",
        ],
    }


@app.get("/salud")
def salud():
    """Para que el scheduler o un uptime check sepan si la API responde."""
    corrida = database.ultima_corrida()
    return {
        "ok": True,
        "ultima_corrida": corrida["fin"] if corrida else None,
        "estatus_ultima_corrida": corrida["estatus"] if corrida else "sin corridas",
    }


@app.get("/api/monitor-terrenos")
def obtener_terrenos():
    """Anuncios activos. Es lo que consume el mapa del dashboard."""
    filas = database.obtener_activos()
    corrida = database.ultima_corrida()
    return {
        "total": len(filas),
        "ultima_actualizacion": (corrida or {}).get("fin"),
        "fuentes": {"activas": ["inmuebles24", "pincali"], "descartadas": ["vivanuncios"]},
        "terrenos": filas,
    }


@app.get("/api/zonas")
def obtener_zonas():
    """
    GeoJSON de las 5 zonas. Se expone para que el dashboard no tenga que
    traer el archivo por separado ni quedar desincronizado de la base.
    """
    ruta = RAIZ / "data" / "torreon_zonas_final.geojson"
    if not ruta.exists():
        raise HTTPException(status_code=404, detail="No se encontró el geojson de zonas.")
    return JSONResponse(content=json.loads(ruta.read_text(encoding="utf-8")))


def _mediana(valores: list[float]) -> float | None:
    if not valores:
        return None
    v = sorted(valores)
    n = len(v)
    if n % 2:
        return round(v[n // 2], 2)
    return round((v[n // 2 - 1] + v[n // 2]) / 2, 2)


# Segmentos por superficie. Una sola mediana para toda la oferta le miente a los
# dos extremos: medido sobre los 101 terrenos de la primera corrida, el lote
# urbano chico vale 3.2 veces mas por m2 que el predio grande ($4,819 contra
# $1,504). Un ejidatario que lea "$4,614/m2" creeria que su hectarea vale 46
# millones.
#
# Los cortes son provisionales: deberian ser los que IMPLAN ya usa por
# normativa o por tipo de uso de suelo, no los que se deducen de los datos.
SEGMENTOS = [
    ("Lote chico",     "menos de 300 m²",        0,       300),
    ("Lote medio",     "300 a 600 m²",           300,     600),
    ("Lote grande",    "600 a 1,500 m²",         600,     1_500),
    ("Predio",         "1,500 a 10,000 m²",      1_500,   10_000),
    ("Rústico/ejidal", "más de 10,000 m²",       10_000,  float("inf")),
]


@app.get("/api/resumen")
def resumen():
    """
    Agregados por zona: lo que alimenta los KPIs y la gráfica de $/m².

    El indicador principal es la MEDIANA, no el promedio. En la primera corrida
    real, un anuncio con error de captura ($8/m², cuando el resto anda en miles)
    bastaba para mover el promedio de toda la ciudad. La mediana no se inmuta
    con un dato extremo, y en precios de suelo —donde conviven lotes urbanos
    chicos con predios rurales grandes— describe mejor lo típico.

    El promedio se sigue publicando para quien lo quiera comparar, pero
    calculado solo sobre precios dentro de un rango sensato.
    """
    filas = database.obtener_activos()

    por_zona: dict[str, dict] = {}
    for f in filas:
        z = f.get("zona") or "(sin zona)"
        d = por_zona.setdefault(z, {"zona": z, "total": 0, "precios_m2": [], "m2": []})
        d["total"] += 1
        if database.precio_m2_confiable(f.get("precio_m2")):
            d["precios_m2"].append(float(f["precio_m2"]))
        if f.get("m2"):
            d["m2"].append(float(f["m2"]))

    salida = []
    for z, d in por_zona.items():
        ppm = d["precios_m2"]
        salida.append({
            "zona": z,
            "color": zonas.COLOR_ZONA.get(z),
            "total": d["total"],
            "precio_m2_mediana": _mediana(ppm),
            "precio_m2_promedio": round(sum(ppm) / len(ppm), 2) if ppm else None,
            "precio_m2_minimo": round(min(ppm), 2) if ppm else None,
            "precio_m2_maximo": round(max(ppm), 2) if ppm else None,
            "m2_mediana": _mediana(d["m2"]),
            "con_precio_confiable": len(ppm),
        })
    salida.sort(key=lambda x: x["total"], reverse=True)

    todos = [float(f["precio_m2"]) for f in filas
             if database.precio_m2_confiable(f.get("precio_m2"))]
    descartados = sum(
        1 for f in filas
        if f.get("precio_m2") and not database.precio_m2_confiable(f.get("precio_m2"))
    )

    # Desglose por tamaño: ver el comentario de SEGMENTOS.
    por_segmento = []
    for nombre, desc, lo, hi in SEGMENTOS:
        en_seg = [
            f for f in filas
            if f.get("m2") and lo <= float(f["m2"]) < hi
            and database.precio_m2_confiable(f.get("precio_m2"))
        ]
        ppm = [float(f["precio_m2"]) for f in en_seg]
        por_segmento.append({
            "segmento": nombre,
            "descripcion": desc,
            "n": len(en_seg),
            "precio_m2_mediana": _mediana(ppm),
            "precio_m2_minimo": round(min(ppm), 2) if ppm else None,
            "precio_m2_maximo": round(max(ppm), 2) if ppm else None,
            # Con pocas observaciones la mediana se mueve con un solo anuncio.
            # Se marca para que el dashboard lo advierta y nadie la cite como censo.
            "muestra_pequena": len(en_seg) < 10,
        })

    return {
        "total_terrenos": len(filas),
        "precio_m2_mediana_ciudad": _mediana(todos),
        "precio_m2_promedio_ciudad": round(sum(todos) / len(todos), 2) if todos else None,
        "precios_descartados_por_atipicos": descartados,
        "rango_confiable": {"min": database.PRECIO_M2_MINIMO, "max": database.PRECIO_M2_MAXIMO},
        "zonas": salida,
        "segmentos": por_segmento,
    }


@app.get("/api/corridas")
def corridas(limite: int = 20):
    """Bitácora: sirve para ver si el scheduler está vivo y detectar fuentes caídas."""
    conn = database.conectar()
    filas = conn.execute(
        "SELECT * FROM corridas ORDER BY id DESC LIMIT ?", (limite,)
    ).fetchall()
    conn.close()
    salida = []
    for f in filas:
        d = dict(f)
        if d.get("detalle"):
            try:
                d["detalle"] = json.loads(d["detalle"])
            except json.JSONDecodeError:
                pass
        salida.append(d)
    return {"total": len(salida), "corridas": salida}


# El dashboard se sirve desde ESTE mismo servicio, no aparte. Al quedar en el
# mismo origen que /api, el navegador ya no aplica CORS al fetch() y se acaban
# de tajo los problemas de puertos, dominios y encabezados. El middleware de
# CORS se queda de todos modos, por si algun dia el HTML se sirve desde otro
# lado.
#
# Va al final a proposito: un mount en "/" atrapa todo lo que no empato antes,
# asi que tiene que declararse despues de las rutas /api y /salud.
if WEB.is_dir():
    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(WEB / "index.html")

    app.mount("/", StaticFiles(directory=WEB, html=True), name="dashboard")
else:  # pragma: no cover - solo si alguien borra web/
    @app.get("/", include_in_schema=False)
    def sin_dashboard():
        return {"error": "No se encontró la carpeta web/ con el dashboard."}
