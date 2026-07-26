"""
Verifica que zonas.py (pipeline) coincida con web/geo.js (mapa).

Los valores esperados se midieron ejecutando GeoZonas.clasificar() en el
navegador sobre el mismo geojson. Si alguien cambia TOLERANCIA_KM o los
poligonos en un lado y no en el otro, esta prueba truena.

Uso:  python tests/test_zonas.py
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import zonas  # noqa: E402

RAIZ = pathlib.Path(__file__).resolve().parent.parent

# (nombre, lat, lon, ciudad, estado esperado, zona esperada o None)
CASOS = [
    ("GP Filadelfia con ciudad",   25.5300, -103.4900, "Gómez Palacio", "fuera",  None),
    ("GP centro con ciudad",       25.5611, -103.4956, "Gómez Palacio", "fuera",  None),
    ("GP centro sin ciudad",       25.5611, -103.4956, None,            "fuera",  None),
    ("Lerdo con ciudad",           25.5389, -103.5245, "Lerdo",         "fuera",  None),
    ("Torreon centro",             25.5428, -103.4068, "Torreón",       "dentro", "Zona 3 - Centro-Norte"),
    ("La Rosita",                  25.5610, -103.3900, "Torreón",       "dentro", "Zona 4 - Oriente"),
    ("Ejido El Tajito",            25.4900, -103.3900, "Torreón",       "borde",  "Zona 5 - Sur Oriente"),
    ("Industrial oriente",         25.5350, -103.3300, "Torreón",       "fuera",  None),
    ("Saltillo (control)",         25.4232, -101.0053, None,            "fuera",  None),
    ("coords invertidas",         -103.4100,   25.5400, None,           "fuera",  None),
]

CONTEO_DEMO_ESPERADO = {
    "Zona 1 - Poniente y Centro Histórico": 3,
    "Zona 2 - Zona Norte": 4,
    "Zona 3 - Centro-Norte": 4,
    "Zona 4 - Oriente": 3,
    "Zona 5 - Sur Oriente": 5,
}


def main() -> int:
    fallas = []

    # 1) consistencia con los valores medidos en el navegador
    print("Clasificacion punto por punto:")
    for nombre, lat, lon, ciudad, estado_esp, zona_esp in CASOS:
        r = zonas.clasificar(lon, lat, ciudad)
        ok = r["estado"] == estado_esp and r["zona"] == zona_esp
        print(f"  [{'ok ' if ok else 'MAL'}] {nombre:<26} -> {r['estado']:<6} {r['zona'] or '-'}")
        if not ok:
            fallas.append(f"{nombre}: esperaba ({estado_esp}, {zona_esp}), obtuvo ({r['estado']}, {r['zona']})")

    # 2) los 19 puntos demo caen en su zona declarada
    print("\nPuntos demo contra su zona declarada:")
    puntos = json.loads((RAIZ / "data" / "puntos_prueba_demo.json").read_text(encoding="utf-8"))
    conteo: dict[str, int] = {}
    for i, p in enumerate(puntos, 1):
        r = zonas.clasificar(p["lon"], p["lat"], "Torreón")
        conteo[r["zona"]] = conteo.get(r["zona"], 0) + 1
        if r["estado"] != "dentro":
            fallas.append(f"punto demo #{i} quedo '{r['estado']}', se esperaba 'dentro'")
        elif r["zona"] != p["zona"]:
            fallas.append(f"punto demo #{i}: geojson dice {r['zona']!r}, el archivo dice {p['zona']!r}")
    print(f"  {len(puntos)} puntos, {len([1 for z in conteo])} zonas con oferta")

    # 3) conteo por zona igual al del mapa
    print("\nConteo por zona (debe coincidir con la leyenda del mapa):")
    for z in sorted(CONTEO_DEMO_ESPERADO):
        obt, esp = conteo.get(z, 0), CONTEO_DEMO_ESPERADO[z]
        ok = obt == esp
        print(f"  [{'ok ' if ok else 'MAL'}] {z:<40} {obt} (esperado {esp})")
        if not ok:
            fallas.append(f"conteo de {z!r}: {obt} != {esp}")

    # 4) el fallback siempre cae dentro del poligono
    print("\nFallback 'punto aleatorio en zona' (100 intentos por zona):")
    for z in CONTEO_DEMO_ESPERADO:
        malos = 0
        for k in range(100):
            par = zonas.punto_aleatorio_en_zona(z, semilla=f"{z}-{k}")
            if par is None:
                malos += 1
                continue
            lat, lon = par
            if zonas.clasificar(lon, lat, "Torreón")["zona"] != z:
                malos += 1
        print(f"  [{'ok ' if malos == 0 else 'MAL'}] {z:<40} {100 - malos}/100 dentro")
        if malos:
            fallas.append(f"fallback de {z!r}: {malos}/100 cayeron fuera")

    # 5) determinismo del fallback
    a = zonas.punto_aleatorio_en_zona("Zona 2 - Zona Norte", semilla="anuncio-123")
    b = zonas.punto_aleatorio_en_zona("Zona 2 - Zona Norte", semilla="anuncio-123")
    print(f"\nDeterminismo del fallback: {'ok' if a == b else 'MAL'} ({a} == {b})")
    if a != b:
        fallas.append("el fallback no es determinista con la misma semilla")

    print("\n" + "=" * 62)
    if fallas:
        print(f"FALLARON {len(fallas)} verificacion(es):")
        for f in fallas:
            print(f"  - {f}")
        return 1
    print("Todo en orden: zonas.py coincide con web/geo.js")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
