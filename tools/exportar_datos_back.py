"""
Deja en datos_back/ una copia legible de los anuncios de cada corrida.

Por que existe, si ya esta terrenos.db: la base es un binario de sqlite. Para
abrirla hace falta una herramienta, y para consultarla hace falta SQL. Estos
archivos se abren con doble clic en Excel o en cualquier editor, sin instalar
nada y sin permisos sobre el servidor.

Sirve para tres cosas concretas:
  - Revisar a mano que la corrida trajo lo que debia.
  - Pasarle los datos a alguien que no va a tocar la base.
  - Reconstruir el inventario de una fecha si la base se pierde o se ensucia.

Deja dos formatos por corrida, con la fecha en el nombre:

  datos_back/
    anuncios-2026-08-27.csv    tabla plana, una fila por anuncio (Excel)
    anuncios-2026-08-27.json   los mismos datos con su tipo, para releerlos

El CSV se escribe con BOM (utf-8-sig) a proposito: sin el, Excel en Windows
abre "Torreón" como "TorreÃ³n" y el archivo parece corrupto aunque este bien.

Uso:  python tools/exportar_datos_back.py        (lo llama main.py solo)
"""
from __future__ import annotations

import csv
import json
import pathlib
import sqlite3
import sys
from datetime import date

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import database  # noqa: E402

# Orden pensado para leerse, no para la base: primero lo que identifica el
# predio, luego precio y medida, y al final la trazabilidad.
COLUMNAS = [
    "id_anuncio", "fuente", "titulo", "nombre_colonia", "zona", "zona_estado",
    "zona_motivo",
    "precio", "m2", "precio_m2",
    "ciudad", "estado", "ubicacion", "lat", "lon", "coords_origen",
    "tipo_propiedad", "fecha_publicacion",
    "fecha_primera_vista", "fecha_ultima_vista", "activo", "url",
]


def carpeta() -> pathlib.Path:
    """Junto a la base, no junto al codigo: se mueven las dos con DATOS_DIR."""
    return database.DB_PATH.parent / "datos_back"


def exportar(cuando: date | None = None) -> dict:
    """
    Escribe el CSV y el JSON de la corrida. Devuelve las rutas y el conteo.

    No filtra por `activo`: se exporta TODO lo que la base conoce, incluidos los
    archivados. Un export que solo trae lo vigente no sirve para responder "que
    habia el mes pasado", que es justo para lo que uno vuelve a estos archivos.
    """
    conn = database.conectar()
    try:
        conn.row_factory = sqlite3.Row
        filas = [dict(r) for r in conn.execute(
            "SELECT * FROM anuncios ORDER BY fecha_publicacion DESC, id_anuncio")]
    finally:
        conn.close()

    destino = carpeta()
    destino.mkdir(parents=True, exist_ok=True)
    sello = (cuando or date.today()).isoformat()

    ruta_csv = destino / f"anuncios-{sello}.csv"
    with ruta_csv.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, extrasaction="ignore")
        w.writeheader()
        for fila in filas:
            w.writerow({c: fila.get(c) for c in COLUMNAS})

    ruta_json = destino / f"anuncios-{sello}.json"
    ruta_json.write_text(
        json.dumps(
            {"generado": sello, "total": len(filas),
             "anuncios": [{c: fila.get(c) for c in COLUMNAS} for fila in filas]},
            ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return {"csv": ruta_csv, "json": ruta_json, "total": len(filas)}


def main() -> int:
    r = exportar()
    print(f"  datos_back/: {r['total']} anuncios")
    print(f"    {r['csv'].name}")
    print(f"    {r['json'].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
