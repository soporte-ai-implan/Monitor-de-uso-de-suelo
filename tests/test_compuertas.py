"""
Prueba las compuertas de calidad con los casos REALES de la primera corrida.

Los umbrales salieron de medir 101 terrenos verdaderos, así que las pruebas
usan esos mismos valores. Si alguien mueve un umbral, aquí truena.

Uso:  python tests/test_compuertas.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import compuertas  # noqa: E402

fallas: list[str] = []


def check(cond: bool, nombre: str, extra: str = "") -> None:
    print(f"  [{'ok ' if cond else 'MAL'}] {nombre}" + (f"  ({extra})" if extra else ""))
    if not cond:
        fallas.append(nombre + (f" — {extra}" if extra else ""))


def anuncio(**kw):
    base = {
        "id_anuncio": "i24-1", "titulo": "Terreno en Venta en Torreón",
        "tipo_propiedad": "Terrenos", "operacion": "Venta",
        "precio": 1_500_000.0, "m2": 400.0,
        "zona": "Zona 2 - Zona Norte", "zona_estado": "dentro",
        "lat": 25.5690, "lon": -103.4218,
    }
    base.update(kw)
    return base


def main() -> int:
    print("La trampa del nombre de calle (casos reales de Torreón)")
    casos_titulo = [
        # (titulo, debe_rechazarse, por qué)
        ("Quinta en Venta en Ampliacion Senderos, Torreon, Coah.", True,
         "el sujeto del título es una Quinta"),
        ("Propiedad en Venta - Circuito Quinta Bilbao, Fraccionamiento Quintas", False,
         "'Quinta' es nombre de calle, no el tipo de inmueble"),
        ("Terreno en Venta en Fraccionamiento Quintas del Nazas", False,
         "fraccionamiento que se llama Quintas"),
        ("Casa en Venta con terreno amplio", True, "es una casa"),
        ("Terreno con casa vieja para demoler", False, "el sujeto es el terreno"),
        ("Venta de Terreo en El Cortijo Torreon Coah", False,
         "'Terreo' es errata de Terreno y sí aparece en los datos reales"),
        ("Propiedad en Venta - Calle Ferropuertos, Zona Industrial", False,
         "título genérico de Inmuebles24 con tipo declarado"),
        ("Bodega en Venta zona industrial", True, "es una bodega"),
    ]
    for titulo, debe_rechazar, porque in casos_titulo:
        pasa, regla, _motivo = compuertas.evaluar(anuncio(titulo=titulo))
        rechazado = not pasa
        ok = rechazado == debe_rechazar
        check(ok, f"{titulo[:52]:<52} — {porque}",
              f"esperaba {'rechazo' if debe_rechazar else 'aceptación'}, regla={regla}")

    print("\nPrecio: los dos errores reales de captura")
    check(not compuertas.evaluar(anuncio(precio=4_500.0, m2=561.0))[0],
          "terreno de 561 m² en $4,500 se rechaza", "el caso real de Las Quintas")
    check(not compuertas.evaluar(anuncio(precio=5_000.0, m2=169.0))[0],
          "terreno de 169 m² en $5,000 se rechaza")
    check(compuertas.evaluar(anuncio(precio=400_000.0, m2=371.0))[0],
          "el más barato legítimo ($400,000) sí pasa")
    check(compuertas.evaluar(anuncio(precio=70_000_000.0, m2=46_538.0))[0],
          "el más caro legítimo ($70M por 4.6 ha) sí pasa")

    print("\nSuperficie: rangos reales (111 a 46,538 m²)")
    # El precio va acorde a la superficie, si no lo rechaza la regla de $/m².
    for m2, precio, esperado, desc in [
        (111.0, 700_000.0, True, "el más chico real"),
        (46_538.0, 70_000_000.0, True, "el más grande real, a $1,504/m²"),
        (49.0, 500_000.0, False, "por debajo del mínimo"),
        (600_000.0, 60_000_000.0, False, "60 hectáreas, error de captura"),
        (None, 1_000_000.0, True, "sin superficie se acepta (solo no entra a estadísticas)"),
    ]:
        pasa = compuertas.evaluar(anuncio(m2=m2, precio=precio))[0]
        check(pasa == esperado, f"m²={m2} — {desc}", f"dio {'pasa' if pasa else 'rechaza'}")

    print("\nPrecio por m²")
    check(not compuertas.evaluar(anuncio(precio=4_500.0, m2=561.0))[0], "$8/m² se rechaza")
    check(compuertas.evaluar(anuncio(precio=90_000.0, m2=300.0))[0], "$300/m² rural sí pasa")
    check(compuertas.evaluar(anuncio(precio=8_350_000.0, m2=300.0))[0],
          "$27,833/m² pasa la compuerta de precio", "se excluye después, solo de promedios")
    # El piso bajo protege al suelo rural grande, que es el que menos vale por m²
    check(compuertas.evaluar(anuncio(precio=2_000_000.0, m2=46_538.0))[0],
          "predio ejidal de 4.6 ha a $43/m² sí pasa",
          "con piso de $50/m² lo habríamos tirado")
    check(not compuertas.evaluar(anuncio(precio=100_000.0, m2=46_538.0))[0],
          "pero $2/m² sigue siendo incoherente y se rechaza")

    print("\nRentas y anuncios sin id")
    check(not compuertas.evaluar(anuncio(operacion="Renta"))[0], "renta se rechaza")
    check(compuertas.evaluar(anuncio(operacion=None))[0], "sin operación se asume venta")
    check(not compuertas.evaluar(anuncio(id_anuncio="i24-None"))[0], "sin id se rechaza")

    print("\nZona")
    check(not compuertas.evaluar(anuncio(zona_estado="fuera", zona=None))[0],
          "fuera de zona se rechaza")
    check(not compuertas.evaluar(anuncio(zona_estado="sin_coords", zona=None))[0],
          "sin coordenadas se rechaza")
    check(compuertas.evaluar(anuncio(zona_estado="borde"))[0], "borde sí pasa")

    print("\nUbicación compartida: el punto por omisión del portal")
    # El caso real: 5 propiedades distintas en el centro de Torreón
    grupo = [
        anuncio(id_anuncio=f"x{i}", lat=25.54284, lon=-103.40679, precio=p, m2=m)
        for i, (p, m) in enumerate(
            [(5_000_000.0, 169.0), (400_000.0, 371.0), (5_831_000.0, 1_666.0),
             (19_047_000.0, 5_442.0), (2_000_000.0, 400.0)])
    ]
    aparte = anuncio(id_anuncio="solo", lat=25.5690, lon=-103.4218)
    compuertas.marcar_ubicaciones_compartidas(grupo + [aparte])
    check(all(not a["ubicacion_precisa"] for a in grupo),
          "los 5 del mismo punto quedan marcados como ubicación aproximada")
    check(all(a["comparten_punto"] == 5 for a in grupo), "se cuenta cuántos comparten el punto")
    check(aparte["ubicacion_precisa"], "el que está solo conserva ubicación precisa")

    print("\nEl reporte explica cada rechazo")
    entrada = [
        anuncio(),
        anuncio(id_anuncio="a2", titulo="Quinta en Venta en Senderos"),
        anuncio(id_anuncio="a3", operacion="Renta"),
        anuncio(id_anuncio="a4", precio=4_500.0, m2=561.0),
        anuncio(id_anuncio="a5", zona_estado="fuera", zona=None),
    ]
    aceptados, rechazados, reporte = compuertas.filtrar(entrada)
    check(len(aceptados) == 1, "solo 1 de 5 pasa", f"pasaron {len(aceptados)}")
    check(reporte["recibidos"] == 5 and reporte["rechazados"] == 4, "el reporte cuadra")
    check(all(r.get("_regla") and r.get("_motivo") for r in rechazados),
          "cada rechazado dice qué regla falló y por qué")
    check(reporte["por_regla"]["es_suelo"] == 1, "cuenta el rechazo por tipo de inmueble")
    check(reporte["por_regla"]["es_venta"] == 1, "cuenta la renta")
    check(reporte["por_regla"]["zona"] == 1, "cuenta el fuera de zona")
    check(len(reporte["reglas"]) == len(compuertas.REGLAS),
          "el reporte publica la lista de reglas para que sea auditable")

    print("\n" + "=" * 66)
    if fallas:
        print(f"FALLARON {len(fallas)} verificacion(es):")
        for f in fallas:
            print(f"  - {f}")
        return 1
    print("Todo en orden: las compuertas filtran y explican cada rechazo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
