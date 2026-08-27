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
import pathlib
import sys
import traceback
from datetime import datetime

import database
import geocoding
import scraper


def _diagnostico_descartes(anuncios: list[dict]) -> None:
    """
    Explica por qué se descartó cada anuncio fuera de zona, y guarda el detalle
    para poder revisarlo sin volver a gastar crédito de Apify.
    """
    fuera = [a for a in anuncios if a.get("zona_estado") in ("fuera", "sin_coords")]
    if not fuera:
        return

    por_municipio, por_distancia, sin_coords = [], [], []
    for a in fuera:
        motivo = a.get("zona_motivo") or ""
        if motivo.startswith("municipio distinto"):
            por_municipio.append(a)
        elif a.get("zona_estado") == "sin_coords":
            sin_coords.append(a)
        else:
            por_distancia.append(a)

    print(f"\n  --- por qué se descartaron {len(fuera)} anuncios ---")

    if por_municipio:
        ciudades: dict[str, int] = {}
        for a in por_municipio:
            c = a.get("ciudad") or "(sin dato)"
            ciudades[c] = ciudades.get(c, 0) + 1
        detalle = ", ".join(f"{c}: {n}" for c, n in sorted(ciudades.items(), key=lambda x: -x[1]))
        print(f"  {len(por_municipio):3d} de otro municipio  ->  {detalle}")
        print("      (esto es correcto: el portal devuelve toda la Comarca Lagunera)")

    if por_distancia:
        print(f"  {len(por_distancia):3d} dentro de Torreón pero lejos de toda zona:")
        for a in por_distancia[:12]:
            d = a.get("zona_motivo", "")
            ciudad = a.get("ciudad") or "?"
            col = a.get("nombre_colonia") or a.get("ubicacion") or "?"
            print(f"        [{ciudad}] {str(col)[:46]:<46} {d}")
        if len(por_distancia) > 12:
            print(f"        ... y {len(por_distancia) - 12} más")
        print("      (OJO: si estos son terrenos reales de Torreón, los polígonos")
        print("       se están quedando cortos y hay que revisarlos)")

    if sin_coords:
        print(f"  {len(sin_coords):3d} sin coordenadas ni dirección geocodificable:")
        for a in sin_coords[:5]:
            print(f"        {str(a.get('titulo'))[:60]}")

    # Guardar todo para analizarlo sin volver a correr los Actores
    destino = pathlib.Path(__file__).resolve().parent / "data" / "ultima_corrida_diagnostico.json"
    try:
        destino.write_text(
            json.dumps(anuncios, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )
        print(f"\n  Detalle completo guardado en {destino.name} "
              f"({len(anuncios)} anuncios) — se puede revisar sin volver a gastar crédito.")
    except OSError as e:
        print(f"  No pude guardar el diagnóstico: {e}")


def _escribir_estado(**campos) -> None:
    """
    Deja el parte de la corrida en web/estado.json, publicado junto al tablero.

    Nunca lanza excepcion: es instrumentacion, no puede tumbar la corrida que
    esta reportando. Y se llama en todas las salidas, incluida la de error.
    """
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "tools"))
        import generar_assets_web

        generar_assets_web.generar_estado({
            "corrida": datetime.now().isoformat(timespec="seconds"),
            **campos,
        })
    except Exception as e:  # noqa: BLE001
        print(f"  Aviso: no pude escribir estado.json: {e}")


# Por debajo de esta fracción de lo que trajo la última corrida buena, la fuente
# se considera mermada. 0.6 deja pasar el vaivén normal del inventario (±40% de
# una corrida a otra ya sería noticia) y atrapa el desplome del 27/08, que fue a
# la mitad. Subirlo daría falsos positivos cada vez que el mercado se mueve.
UMBRAL_MERMA = 0.6

# Debajo de esto no hay con qué comparar y la fracción es puro ruido: pasar de
# 3 a 1 anuncio es -66% y no significa nada. Pincali entrega ~5 por el tope de
# cuenta gratuita, así que sin este piso viviría marcada como mermada.
MINIMO_PARA_COMPARAR = 20


def _detectar_mermas(detalle_fuentes: dict) -> list[str]:
    """
    Fuentes que respondieron 'ok' pero con muchos menos anuncios que la última
    corrida buena. Devuelve sus nombres.

    Nunca lanza excepción: si no se puede leer la corrida anterior, se sigue sin
    el blindaje en vez de tumbar la corrida.
    """
    try:
        previa = database.ultima_corrida()
        detalle = (previa or {}).get("detalle")
        if isinstance(detalle, str):
            detalle = json.loads(detalle)
        antes = (detalle or {}).get("fuentes") or {}
    except Exception:  # noqa: BLE001
        return []

    mermadas = []
    for nombre, d in detalle_fuentes.items():
        if d.get("estatus") != "ok":
            continue
        hoy = d.get("crudos") or 0
        ayer = (antes.get(nombre) or {}).get("crudos") or 0
        if ayer < MINIMO_PARA_COMPARAR or hoy >= ayer * UMBRAL_MERMA:
            continue
        mermadas.append(nombre)
        print(f"\n  ALTO: '{nombre}' trajo {hoy} y la corrida anterior trajo "
              f"{ayer} ({hoy / ayer:.0%}). Se trata como caída: no se dan de "
              f"baja sus terrenos.")
    return mermadas


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

        # BLINDAJE 3 — una fuente que rinde de MENOS tampoco es de fiar.
        #
        # Los blindajes 1 y 2 cubren la fuente que devuelve cero. El 27/08/2026
        # apareció el caso intermedio, que es peor porque no se nota: el Actor
        # de Inmuebles24 devolvió 60 de los ~120 habituales y terminó 'ok'. Los
        # 60 que no llegaron se leyeron como desaparecidos y la corrida archivó
        # 56 terrenos reales como vendidos, sin una sola señal de error.
        #
        # Así que se compara contra la última corrida buena. Un desplome no se
        # puede distinguir de un mercado que se movió de golpe, y ante la duda
        # NO se archiva: publicar "se vendió la mitad del suelo de Torreón" por
        # una falla del scraper es el peor error que puede cometer el monitor.
        mermadas = _detectar_mermas(detalle_fuentes)
        for nombre in mermadas:
            detalle_fuentes[nombre]["estatus"] = "mermada"

        fuentes_ok = [n for n, d in detalle_fuentes.items() if d.get("estatus") == "ok"]
        caidas = [n for n, d in detalle_fuentes.items()
                  if d.get("estatus") in ("error", "vacia", "mermada")]
        if caidas:
            print(f"\n  OJO: {len(caidas)} fuente(s) sin datos confiables hoy: "
                  f"{', '.join(caidas)}. Sus terrenos NO se dan de baja; "
                  f"la corrida se marca 'parcial'.")

        if not crudos:
            # No es lo mismo "no hay terrenos en venta" que "el scraper tronó".
            # Se cierra la corrida como error y NO se toca el estado activo.
            print("\n  Ninguna fuente devolvió anuncios. No se modifica la base "
                  "(evita dar de baja todo por error).")
            if not seco:
                database.cerrar_corrida(
                    id_corrida, "error", total_crudos=0, detalle=detalle_fuentes
                )
                _escribir_estado(
                    estatus="error",
                    razon="ninguna fuente devolvió anuncios; no se tocó la base",
                    fuentes={n: d.get("estatus") for n, d in detalle_fuentes.items()},
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

        # Desglose de POR QUE se descarto cada uno. Sin esto no se distingue
        # "el portal nos manda anuncios de Gomez Palacio" (correcto descartarlos)
        # de "nuestros poligonos no cubren zona ejidal de Torreon" (estamos
        # tirando datos buenos). Son problemas opuestos con arreglos opuestos.
        _diagnostico_descartes(enriquecidos)

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

        # La zona se asigna al dar de alta, asi que la base acumulaba reglas
        # viejas: un anuncio guardado antes del guardian municipal conservaba
        # su zona para siempre y el tablero contaba 97 donde el pipeline decia
        # 98. Se revisa todo lo activo contra las reglas de HOY.
        try:
            rz = database.reclasificar_zonas()
            if rz["reclasificados"]:
                print(f"  Zonas reclasificadas: {rz['reclasificados']} de {rz['revisados']}")
                for c in rz["detalle"][:10]:
                    print(f"    {c['id_anuncio']}: {c['antes']}  ->  {c['ahora']}")
            else:
                print(f"  Zonas al dia: {rz['revisados']} revisados, sin cambios")
        except Exception as e:  # noqa: BLE001 - no debe tumbar la corrida
            print(f"  Aviso: no pude reclasificar zonas: {e}")

        # Regenerar el dashboard estatico. Con esto el HTML no necesita API:
        # basta subir la carpeta web/ a cualquier hosting.
        try:
            sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "tools"))
            import generar_assets_web

            activos = database.obtener_activos()
            ruta = generar_assets_web.generar_datos(
                activos, datetime.now().isoformat(timespec="seconds"),
                # El estado de cada fuente viaja con los datos: si un portal
                # se cayo, el tablero tiene que decirlo. Si no, la baja de
                # oferta se lee como mercado y no como falla tecnica.
                fuentes=detalle_fuentes,
            )
            print(f"  Dashboard estático actualizado: {ruta.name} ({len(activos)} terrenos)")

            # Y el archivo de un solo HTML. Si no se rearma aqui, se queda con
            # los datos del dia que se empaqueto: el tablero decia "actualizado
            # el 1 de agosto" con el pipeline corriendo al dia. Es el artefacto
            # que se manda por correo y se sube al hosting, asi que tiene que
            # salir de cada corrida, no de un empaquetado manual.
            try:
                import empaquetar_html

                empaquetar_html.main()
            except Exception as e:  # noqa: BLE001 - el tablero de carpeta ya quedo
                print(f"  Aviso: no pude rearmar el HTML autocontenido: {e}")

            # Copia legible de los anuncios en datos_back/, para revisarlos sin
            # abrir la base ni escribir SQL. Va aparte del tablero a proposito:
            # el tablero publica lo vigente, esto guarda todo lo que la base
            # conoce, archivados incluidos.
            try:
                import exportar_datos_back

                r = exportar_datos_back.exportar()
                print(f"  datos_back/: {r['total']} anuncios "
                      f"({r['csv'].name}, {r['json'].name})")
            except Exception as e:  # noqa: BLE001 - la base ya quedo guardada
                print(f"  Aviso: no pude exportar a datos_back/: {e}")
        except Exception as e:  # noqa: BLE001 - no debe tumbar la corrida
            print(f"  Aviso: no pude regenerar el dashboard estático: {e}")

        # Contra las fuentes que de verdad se iban a correr, no contra un 2
        # fijo: con Pincali apagado, "2 de 2" marcaba parcial toda corrida sana.
        estatus = "ok" if len(fuentes_ok) == len(scraper.FUENTES_ACTIVAS) else "parcial"
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
        _escribir_estado(
            estatus=estatus,
            terrenos_publicados=len(validos),
            anuncios_crudos=len(crudos),
            fuentes={n: d.get("estatus") for n, d in detalle_fuentes.items()},
            nuevos=resumen["nuevos"],
            actualizados=resumen["actualizados"],
            dados_de_baja=resumen["dados_de_baja"],
            cambios_precio=resumen["cambios_precio"],
            duracion_seg=round(dur, 1),
        )
        print(f"\n=== Corrida '{estatus}' en {dur:.1f}s ===\n")
        return {"estatus": estatus, **resumen, "motivos": motivos}

    except Exception as e:  # noqa: BLE001
        print(f"\n!!! La corrida falló: {e}", file=sys.stderr)
        traceback.print_exc()
        if not seco and id_corrida is not None:
            database.cerrar_corrida(id_corrida, "error", detalle={"error": str(e)})
            _escribir_estado(estatus="error", razon=str(e)[:300])
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
