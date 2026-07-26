"""
main.py — orquesta la corrida completa. Esto es lo que dispara el scheduler.

    scraper  ->  geocoding  ->  database

Todo queda anotado en la tabla `corridas`, para poder contestar despues
"¿por qué el martes bajó la oferta 30%?" sin adivinar.

Uso:
    python main.py                  corrida normal
    python main.py --seco           no escribe en la base, solo reporta
    python main.py --max 20         limita resultados por fuente (pruebas)
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime

import database
import geocoding
import scraper


def correr_monitor(max_por_fuente: int | None = None, seco: bool = False) -> dict:
    inicio = datetime.now()
    print(f"\n=== Monitor de Suelo IMPLAN — corrida {inicio:%Y-%m-%d %H:%M:%S} ===")
    if seco:
        print("(modo seco: no se escribe en la base)")

    id_corrida = None if seco else database.iniciar_corrida()

    try:
        # 1) Scraping
        print("\n[1/3] Extrayendo de Apify...")
        crudos, detalle_fuentes = scraper.obtener_anuncios_torreon(max_por_fuente)
        fuentes_ok = [n for n, d in detalle_fuentes.items() if d.get("estatus") == "ok"]

        if not crudos:
            # No es lo mismo "no hay terrenos en venta" que "el scraper tronó".
            # Se cierra la corrida como error y NO se toca el estado activo.
            print("\n  Ninguna fuente devolvió anuncios. No se modifica la base "
                  "(evita dar de baja todo por error).")
            if not seco:
                database.cerrar_corrida(
                    id_corrida, "error", total_crudos=0, detalle=detalle_fuentes
                )
            return {"estatus": "error", "razon": "sin anuncios de ninguna fuente",
                    "detalle": detalle_fuentes}

        print(f"  Total crudo: {len(crudos)} anuncios de {len(fuentes_ok)} fuente(s) OK")

        # 2) Geocoding + asignación de zona
        print("\n[2/3] Geocoding y asignación de zona...")
        enriquecidos, stats_geo = geocoding.enriquecer_anuncios(crudos)
        print(f"  Coordenadas: {stats_geo['portal']} del portal, "
              f"{stats_geo['nominatim']} por Nominatim, "
              f"{stats_geo['centroide_zona']} por polígono de zona, "
              f"{stats_geo['sin_ubicar']} sin ubicar")

        conteo_zonas = {}
        for a in enriquecidos:
            conteo_zonas[a.get("zona_estado")] = conteo_zonas.get(a.get("zona_estado"), 0) + 1
        print(f"  Validación geográfica: {conteo_zonas}")

        # 3) Filtros y persistencia
        print("\n[3/3] Filtrando y guardando...")
        validos, motivos = database.filtrar(enriquecidos)
        print(f"  Descartados: {motivos}")
        print(f"  Terrenos válidos: {len(validos)}")

        if seco:
            print("\n  (modo seco) No se escribió nada.")
            return {"estatus": "seco", "validos": len(validos), "motivos": motivos,
                    "detalle": detalle_fuentes, "geo": stats_geo}

        resumen = database.guardar_anuncios(validos, fuentes_ok=fuentes_ok)
        if resumen.get("aviso"):
            print(f"  AVISO: {resumen['aviso']}")

        print(f"  Nuevos: {resumen['nuevos']} · "
              f"Actualizados: {resumen['actualizados']} · "
              f"Bajas: {resumen['dados_de_baja']} · "
              f"Cambios de precio: {resumen['cambios_precio']}")

        estatus = "ok" if len(fuentes_ok) == 2 else "parcial"
        database.cerrar_corrida(
            id_corrida, estatus,
            total_crudos=len(crudos), total_terrenos=len(validos),
            nuevos=resumen["nuevos"], actualizados=resumen["actualizados"],
            dados_de_baja=resumen["dados_de_baja"],
            descartados_zona=motivos.get("fuera_de_zona", 0),
            detalle={"fuentes": detalle_fuentes, "geocoding": stats_geo,
                     "descartes": motivos, "zonas": conteo_zonas},
        )

        dur = (datetime.now() - inicio).total_seconds()
        print(f"\n=== Corrida '{estatus}' en {dur:.1f}s ===\n")
        return {"estatus": estatus, **resumen, "motivos": motivos}

    except Exception as e:  # noqa: BLE001
        print(f"\n!!! La corrida falló: {e}", file=sys.stderr)
        traceback.print_exc()
        if not seco and id_corrida is not None:
            database.cerrar_corrida(id_corrida, "error", detalle={"error": str(e)})
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description="Corrida del Monitor de Suelo IMPLAN Torreón")
    ap.add_argument("--seco", action="store_true", help="no escribir en la base")
    ap.add_argument("--max", type=int, default=None, help="máximo de resultados por fuente")
    ap.add_argument("--json", action="store_true", help="imprimir el resumen como JSON")
    args = ap.parse_args()

    try:
        r = correr_monitor(max_por_fuente=args.max, seco=args.seco)
    except Exception:
        return 1

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    return 0 if r.get("estatus") in ("ok", "parcial", "seco") else 1


if __name__ == "__main__":
    raise SystemExit(main())
