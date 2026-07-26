"""
api.py — sirve los datos al dashboard.

CORS explícito porque el HTML se sirve desde otro dominio (trcimplan.gob.mx)
o desde file:// durante las demos, y sin encabezados el navegador bloquea el
fetch() sin decir por qué.

Arrancar:  uvicorn api:app --reload --port 8000
"""
from __future__ import annotations

import json
import os
import pathlib

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import database
import zonas

load_dotenv()

RAIZ = pathlib.Path(__file__).resolve().parent

app = FastAPI(
    title="API Monitor de Suelo — IMPLAN Torreón",
    description="Oferta de terrenos en venta en Torreón, vía Inmuebles24 y Pincali.",
    version="1.0.0",
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


@app.get("/")
def raiz():
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


@app.get("/api/resumen")
def resumen():
    """Agregados por zona: lo que alimenta los KPIs y la gráfica de $/m²."""
    filas = database.obtener_activos()

    por_zona: dict[str, dict] = {}
    for f in filas:
        z = f.get("zona") or "(sin zona)"
        d = por_zona.setdefault(z, {"zona": z, "total": 0, "precios_m2": [], "m2": []})
        d["total"] += 1
        if f.get("precio_m2"):
            d["precios_m2"].append(f["precio_m2"])
        if f.get("m2"):
            d["m2"].append(f["m2"])

    salida = []
    for z, d in por_zona.items():
        ppm = d["precios_m2"]
        salida.append({
            "zona": z,
            "color": zonas.COLOR_ZONA.get(z),
            "total": d["total"],
            "precio_m2_promedio": round(sum(ppm) / len(ppm), 2) if ppm else None,
            "precio_m2_minimo": min(ppm) if ppm else None,
            "precio_m2_maximo": max(ppm) if ppm else None,
            "m2_mediana": sorted(d["m2"])[len(d["m2"]) // 2] if d["m2"] else None,
        })
    salida.sort(key=lambda x: x["total"], reverse=True)

    todos_ppm = [f["precio_m2"] for f in filas if f.get("precio_m2")]
    return {
        "total_terrenos": len(filas),
        "precio_m2_promedio_ciudad": round(sum(todos_ppm) / len(todos_ppm), 2) if todos_ppm else None,
        "zonas": salida,
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
