"""
database.py — guarda, compara y detecta altas/bajas.

Dos blindajes contra bajas falsas (un dashboard que dice "se vendieron 84
terrenos" porque el scraper tronó es peor que un dashboard sin actualizar):

  1. Si la lista de anuncios llega VACIA, no se ejecuta el UPDATE de
     "marcar inactivos". En el código original ese UPDATE se armaba con
     `IN ()` vacío, que en SQL no empata con nada y por lo tanto marcaba
     TODA la tabla como inactiva.

  2. Las bajas se aplican SOLO a las fuentes que respondieron bien en esta
     corrida. Si Pincali funcionó e Inmuebles24 tronó, no se dan de baja los
     anuncios de Inmuebles24: no sabemos nada de ellos hoy.

El filtro de tipo de propiedad se hace aquí, del lado del código, sin confiar
en el filtro del Actor.
"""
from __future__ import annotations

import json
import os
import pathlib
import sqlite3
from datetime import date, datetime
from typing import Any, Iterable

from dotenv import load_dotenv

import compuertas
import zonas

load_dotenv()

RAIZ = pathlib.Path(__file__).resolve().parent
SCHEMA_PATH = RAIZ / "schema.sql"

# DATOS_DIR permite mover la base a un volumen persistente. Es indispensable en
# Railway o cualquier contenedor: el disco normal es efimero y cada redeploy
# borraria terrenos.db, y con ella el historial que sostiene la deteccion de
# altas y bajas. Sin historial, cada corrida se veria como si todo fuera nuevo.
DATOS_DIR = pathlib.Path(os.getenv("DATOS_DIR", str(RAIZ))).expanduser()
DATOS_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATOS_DIR / "terrenos.db"

# Las listas de palabras y los umbrales viven en compuertas.py, que es donde se
# documentan y se miden contra datos reales.
# Se reexportan aqui porque api.py y las pruebas ya los consumen por este nombre.
PRECIO_M2_MINIMO = compuertas.PRECIO_M2_MIN
PRECIO_M2_MAXIMO = compuertas.PRECIO_M2_MAX
precio_m2_confiable = compuertas.precio_m2_confiable


def conectar() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


# ---------- filtros ----------

def es_terreno(a: dict) -> bool:
    """Es oferta de suelo? La regla vive en compuertas.py."""
    return compuertas._r_es_terreno(a) is None


def es_venta(a: dict) -> bool:
    """Descarta rentas: el monitor es de oferta en venta."""
    return compuertas._r_es_venta(a) is None


def filtrar(anuncios: list[dict]) -> tuple[list[dict], dict]:
    """
    Aplica las compuertas de calidad. Regresa (validos, motivos_descarte).

    La lógica vive en compuertas.py, donde cada regla tiene nombre y cada
    rechazo queda explicado. Aquí se conserva la forma del resultado que ya
    esperaban main.py y las pruebas.
    """
    validos, rechazados, reporte = compuertas.filtrar(anuncios)

    # Nombres viejos para no romper lo que ya los usa.
    por_regla = reporte["por_regla"]
    motivos = {
        "no_terreno": por_regla.get("es_suelo", 0) + por_regla.get("identificador", 0),
        "no_venta": por_regla.get("es_venta", 0),
        "fuera_de_zona": por_regla.get("zona", 0),
        "sin_precio": por_regla.get("precio", 0),
        "superficie_implausible": por_regla.get("superficie", 0),
        "precio_m2_implausible": por_regla.get("precio_m2", 0),
        "_reporte": reporte,
        "_rechazados": rechazados,
    }
    return validos, motivos


# ---------- persistencia ----------

def _precio_m2(a: dict) -> float | None:
    precio, m2 = a.get("precio"), a.get("m2")
    if precio and m2 and float(m2) > 0:
        return round(float(precio) / float(m2), 2)
    return None


def guardar_anuncios(anuncios: list[dict], fuentes_ok: Iterable[str] | None = None) -> dict:
    """
    Guarda la corrida actual y detecta altas/bajas.

    `fuentes_ok` son las fuentes que respondieron bien. Solo dentro de ellas se
    dan de baja los anuncios que ya no aparecieron. Si es None se deduce de los
    propios anuncios.
    """
    hoy = date.today().isoformat()
    conn = conectar()
    nuevos = actualizados = bajas = cambios_precio = 0

    try:
        # --- BLINDAJE 1: lista vacia ---
        if not anuncios:
            conn.close()
            return {
                "nuevos": 0, "actualizados": 0, "dados_de_baja": 0, "cambios_precio": 0,
                "fecha": hoy,
                "aviso": "La lista llegó vacía: no se marcó nada como inactivo "
                         "(probable falla del scraper, no bajas reales).",
            }

        if fuentes_ok is None:
            fuentes_ok = {a.get("fuente") for a in anuncios if a.get("fuente")}
        fuentes_ok = [f for f in fuentes_ok if f]

        ids_vistos: list[str] = []

        for a in anuncios:
            idn = a["id_anuncio"]
            ids_vistos.append(idn)
            ppm = _precio_m2(a)

            fila = conn.execute(
                "SELECT precio FROM anuncios WHERE id_anuncio = ?", (idn,)
            ).fetchone()

            if fila:
                if fila["precio"] is not None and a.get("precio") is not None:
                    if abs(float(fila["precio"]) - float(a["precio"])) > 0.5:
                        cambios_precio += 1
                conn.execute(
                    """UPDATE anuncios SET
                         fecha_ultima_vista = ?, precio = ?, m2 = ?, precio_m2 = ?,
                         zona = ?, zona_estado = ?, zona_motivo = ?,
                         nombre_colonia = ?, lat = ?, lon = ?, coords_origen = ?,
                         ciudad = ?, estado = ?, url = ?, activo = 1
                       WHERE id_anuncio = ?""",
                    (hoy, a.get("precio"), a.get("m2"), ppm,
                     a.get("zona"), a.get("zona_estado"), a.get("zona_motivo"),
                     a.get("nombre_colonia"), a.get("lat"), a.get("lon"), a.get("coords_origen"),
                     a.get("ciudad"), a.get("estado"), a.get("url"), idn),
                )
                actualizados += 1
            else:
                conn.execute(
                    """INSERT INTO anuncios
                         (id_anuncio, fuente, titulo, precio, m2, precio_m2, ubicacion,
                          ciudad, estado, nombre_colonia, zona, zona_estado, zona_motivo,
                          lat, lon, coords_origen, tipo_propiedad, url,
                          fecha_publicacion, fecha_primera_vista, fecha_ultima_vista, activo)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
                    (idn, a.get("fuente"), a.get("titulo"), a.get("precio"), a.get("m2"), ppm,
                     a.get("ubicacion"), a.get("ciudad"), a.get("estado"), a.get("nombre_colonia"),
                     a.get("zona"), a.get("zona_estado"), a.get("zona_motivo"),
                     a.get("lat"), a.get("lon"), a.get("coords_origen"),
                     a.get("tipo_propiedad"), a.get("url"),
                     a.get("fecha_publicacion"), hoy, hoy),
                )
                nuevos += 1

            if a.get("precio"):
                conn.execute(
                    "INSERT OR IGNORE INTO historial_precios (id_anuncio, precio, fecha) VALUES (?,?,?)",
                    (idn, a["precio"], hoy),
                )

        # --- BLINDAJE 2: bajas solo en fuentes que respondieron ---
        if ids_vistos and fuentes_ok:
            ph_ids = ",".join("?" * len(ids_vistos))
            ph_fuentes = ",".join("?" * len(fuentes_ok))
            cur = conn.execute(
                f"""UPDATE anuncios SET activo = 0
                    WHERE activo = 1
                      AND fuente IN ({ph_fuentes})
                      AND id_anuncio NOT IN ({ph_ids})""",
                (*fuentes_ok, *ids_vistos),
            )
            bajas = cur.rowcount or 0

        conn.commit()
    finally:
        conn.close()

    return {
        "nuevos": nuevos, "actualizados": actualizados,
        "dados_de_baja": bajas, "cambios_precio": cambios_precio,
        "fecha": hoy, "fuentes_evaluadas": list(fuentes_ok),
    }


# ---------- bitacora de corridas ----------

def iniciar_corrida() -> int:
    conn = conectar()
    cur = conn.execute(
        "INSERT INTO corridas (inicio, estatus) VALUES (?, 'en_proceso')",
        (datetime.now().isoformat(timespec="seconds"),),
    )
    conn.commit()
    idc = cur.lastrowid
    conn.close()
    return idc


def cerrar_corrida(id_corrida: int, estatus: str, **campos: Any) -> None:
    conn = conectar()
    conn.execute(
        """UPDATE corridas SET fin = ?, estatus = ?, total_crudos = ?, total_terrenos = ?,
                  nuevos = ?, actualizados = ?, dados_de_baja = ?, descartados_zona = ?, detalle = ?
           WHERE id = ?""",
        (
            datetime.now().isoformat(timespec="seconds"), estatus,
            campos.get("total_crudos", 0), campos.get("total_terrenos", 0),
            campos.get("nuevos", 0), campos.get("actualizados", 0),
            campos.get("dados_de_baja", 0), campos.get("descartados_zona", 0),
            json.dumps(campos.get("detalle", {}), ensure_ascii=False),
            id_corrida,
        ),
    )
    conn.commit()
    conn.close()


def obtener_activos() -> list[dict]:
    conn = conectar()
    filas = conn.execute(
        """SELECT * FROM anuncios
           WHERE activo = 1
           ORDER BY fecha_primera_vista DESC, precio_m2 ASC"""
    ).fetchall()
    conn.close()
    return [dict(f) for f in filas]


def ultima_corrida() -> dict | None:
    conn = conectar()
    fila = conn.execute(
        "SELECT * FROM corridas ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(fila) if fila else None
