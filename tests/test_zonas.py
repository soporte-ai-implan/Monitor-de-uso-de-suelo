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
    ("GP con el estado nada mas",  25.5611, -103.4956, "Durango",       "fuera",  None),
    ("Lerdo con ciudad",           25.5389, -103.5245, "Lerdo",         "fuera",  None),
    ("Torreon centro",             25.5428, -103.4068, "Torreón",       "dentro", "Zona 3 - Centro-Norte"),
    ("La Rosita",                  25.5610, -103.3900, "Torreón",       "dentro", "Zona 4 - Oriente"),
    ("Ejido El Tajito",            25.4900, -103.3900, "Torreón",       "borde",  "Zona 5 - Sur Oriente"),
    # Predio real de Torreon a 2.29 km de toda zona. Con TOLERANCIA_KM=1.5 se
    # perdia; con 3.0 se recupera. Es la razon de haber subido el umbral.
    ("Industrial oriente (rural)",  25.5350, -103.3300, "Torreón",      "borde",  "Zona 4 - Oriente"),
    ("Saltillo (control)",         25.4232, -101.0053, None,            "fuera",  None),
    ("coords invertidas",         -103.4100,   25.5400, None,           "fuera",  None),
]

# LIMITACION CONOCIDA, documentada a proposito como prueba.
#
# Un anuncio con coordenadas en Gomez Palacio y SIN una sola palabra de
# ubicacion se dibuja como si fuera de Torreon: a 2.43 km del borde de Zona 1,
# dentro de la tolerancia de 3.0 km. La geometria no puede distinguirlo porque
# las dos ciudades son contiguas.
#
# Se acepta el riesgo porque: (a) los dos portales si mandan texto de ubicacion
# en la practica, (b) el geocoding con Nominatim rellena la ciudad cuando falta,
# y (c) el costo de la alternativa (bajar el umbral) era perder predios
# legitimos de la periferia de Torreon, que era el problema mas grande.
#
# Se cierra del todo con el poligono municipal del INEGI. Ver docs/mapa.md.
CASO_LIMITE = ("GP centro SIN nada de texto", 25.5611, -103.4956, (None, None, None, None), "borde")

# Casos tomados de anuncios REALES de la corrida de diagnostico. Inmuebles24
# recorre su jerarquia de ubicacion: en 14 de 20 anuncios mandaba
# city='Coahuila' (el estado) y neighborhood='Torreón' (el municipio).
# Leer solo `city` los rechazaba, y 11 de ellos caian en una zona real.
CASOS_CAMPOS_CORRIDOS = [
    # (nombre, lat, lon, (ciudad, colonia, ubicacion, titulo), debe_dibujarse)
    ("Las Quintas: city=Coahuila, colonia=Torreón",
     25.5991, -103.4071,
     ("Coahuila", "Torreón", "Terreno, Quinta DEL Carmen, Torreón, Coahuila",
      "Terreno en Venta Residencial Las Quintas Torreón"),
     True),
    ("Otro con campos corridos",
     25.5917, -103.3681,
     ("Coahuila", "Torreón", "Terreno, Torreón, Coahuila", "Terreno en Venta"),
     True),
    ("Campos bien puestos",
     25.5428, -103.4068,
     ("Torreón", "Centro", "Av. Juárez, Torreón", "Terreno céntrico"),
     True),
    # Un vecino nombrado tiene que ganar aunque tambien diga Torreon
    ("Gómez Palacio aunque mencione Torreón",
     25.5611, -103.4956,
     ("Durango", "Gómez Palacio", "Centro, Gómez Palacio, a 10 min de Torreón", "Terreno"),
     False),
    ("Lerdo con el estado en city",
     25.5389, -103.5245,
     ("Durango", "Lerdo", "Centro, Lerdo, Durango", "Terreno en Lerdo"),
     False),
    ("Matamoros Coahuila",
     25.5300, -103.2300,
     ("Coahuila", "Matamoros", "Matamoros, Coahuila", "Terreno en Matamoros"),
     False),
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

    # 1b) el caso que rompio el filtro en produccion: campos de ubicacion corridos
    print("\nCampos de ubicación corridos (anuncios reales de Inmuebles24):")
    for nombre, lat, lon, textos, debe_dibujarse in CASOS_CAMPOS_CORRIDOS:
        r = zonas.clasificar(lon, lat, *textos)
        se_dibuja = r["estado"] != "fuera"
        ok = se_dibuja == debe_dibujarse
        esperado = "se dibuja" if debe_dibujarse else "se descarta"
        print(f"  [{'ok ' if ok else 'MAL'}] {nombre:<44} -> {r['estado']:<6} ({esperado})")
        if not ok:
            fallas.append(f"{nombre}: esperaba {esperado}, obtuvo estado={r['estado']} ({r['motivo']})")

    # 1b-bis) la limitacion conocida, verificada como tal
    nombre, lat, lon, textos, estado_esp = CASO_LIMITE
    r = zonas.clasificar(lon, lat, *textos)
    ok = r["estado"] == estado_esp
    print(f"\nLimitación conocida (documentada, no es un descuido):")
    print(f"  [{'ok ' if ok else 'MAL'}] {nombre} -> {r['estado']}"
          f"   <- sin texto, la geometría no separa Torreón de Gómez")
    if not ok:
        fallas.append(
            f"{nombre}: el comportamiento cambió (esperaba {estado_esp}, dio {r['estado']}). "
            "Si fue a propósito, actualiza CASO_LIMITE y docs/mapa.md."
        )

    # 1c) municipio_valido con varios campos
    print("\nGuardián de municipio sobre texto completo:")
    pruebas_mv = [
        (("Coahuila", "Torreón", None, None), True,  "estado en city, municipio en colonia"),
        (("Torreón", "Centro", None, None),   True,  "campos bien puestos"),
        (("Durango", "Gómez Palacio", None, None), False, "vecino nombrado"),
        (("Coahuila", None, None, None),      None,  "solo el estado: no se puede saber"),
        ((None, None, None, None),            None,  "sin datos"),
        (("Coahuila", "Torreón", "cerca de Lerdo", None), False, "vecino gana sobre Torreón"),
    ]
    for textos, esperado, desc in pruebas_mv:
        got = zonas.municipio_valido(*textos)
        ok = got is esperado
        print(f"  [{'ok ' if ok else 'MAL'}] {desc:<44} -> {got}")
        if not ok:
            fallas.append(f"municipio_valido({desc}): esperaba {esperado}, dio {got}")

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
