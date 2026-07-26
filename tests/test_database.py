"""
Prueba los dos blindajes contra bajas falsas y los filtros de código.

Usa una base temporal, no toca terrenos.db.

Uso:  python tests/test_database.py
"""
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import database  # noqa: E402

fallas: list[str] = []


def check(cond: bool, nombre: str, extra: str = "") -> None:
    print(f"  [{'ok ' if cond else 'MAL'}] {nombre}" + (f"  ({extra})" if extra else ""))
    if not cond:
        fallas.append(nombre + (f" — {extra}" if extra else ""))


def anuncio(idn: str, fuente: str, precio: float = 500000, zona: str = "Zona 2 - Zona Norte") -> dict:
    return {
        "id_anuncio": idn, "fuente": fuente, "titulo": "Terreno en venta en Torreón",
        "precio": precio, "m2": 250, "ubicacion": "Torreón", "ciudad": "Torreón",
        "estado": "Coahuila", "nombre_colonia": "Col. Prueba",
        "zona": zona, "zona_estado": "dentro", "zona_motivo": "point-in-polygon",
        "lat": 25.5690, "lon": -103.4218, "coords_origen": "portal",
        "tipo_propiedad": "Terreno", "operacion": "Venta",
        "url": f"https://ejemplo.mx/{idn}", "fecha_publicacion": "2026-07-01",
    }


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp())
    database.DB_PATH = tmp / "prueba.db"

    print("BLINDAJE 1 — lista vacía no debe dar de baja nada")
    base = [anuncio("a1", "inmuebles24"), anuncio("a2", "inmuebles24"), anuncio("b1", "pincali")]
    r = database.guardar_anuncios(base)
    check(r["nuevos"] == 3, "carga inicial inserta 3", f"nuevos={r['nuevos']}")

    r_vacio = database.guardar_anuncios([])
    activos = database.obtener_activos()
    check(r_vacio["dados_de_baja"] == 0, "lista vacía no marca bajas")
    check("aviso" in r_vacio, "lista vacía regresa aviso explícito")
    check(len(activos) == 3, "los 3 anuncios siguen activos tras la lista vacía",
          f"activos={len(activos)}")

    print("\nBLINDAJE 2 — bajas solo en fuentes que respondieron")
    # Inmuebles24 responde y ya no trae 'a2'; Pincali tronó (no está en fuentes_ok).
    r2 = database.guardar_anuncios([anuncio("a1", "inmuebles24")], fuentes_ok=["inmuebles24"])
    activos = {a["id_anuncio"]: a for a in database.obtener_activos()}
    check(r2["dados_de_baja"] == 1, "da de baja 'a2' (desapareció de una fuente viva)",
          f"bajas={r2['dados_de_baja']}")
    check("a2" not in activos, "'a2' quedó inactivo")
    check("b1" in activos, "'b1' de Pincali NO se dio de baja aunque no vino en la corrida")
    check("a1" in activos, "'a1' sigue activo")

    print("\nHistorial de precios y detección de cambios")
    r3 = database.guardar_anuncios([anuncio("a1", "inmuebles24", precio=430000)],
                                   fuentes_ok=["inmuebles24"])
    check(r3["cambios_precio"] == 1, "detecta el cambio de precio", f"={r3['cambios_precio']}")
    conn = database.conectar()
    n_hist = conn.execute(
        "SELECT COUNT(*) c FROM historial_precios WHERE id_anuncio='a1'"
    ).fetchone()["c"]
    conn.close()
    check(n_hist == 2, "historial guarda los 2 precios de 'a1'", f"filas={n_hist}")

    print("\nFiltro de tipo de propiedad (lado del código)")
    casos = [
        ("Terreno en venta zona norte", "Terreno", True),
        ("Lote residencial en Torreón", "Lote", True),
        ("Predio ejidal 5 hectáreas", None, True),
        ("Casa con terreno amplio", "Casa", False),
        ("Bodega industrial en renta", "Bodega", False),
        ("Departamento nuevo", "Departamento", False),
        ("Local comercial céntrico", "Local", False),
    ]
    for titulo, tipo, esperado in casos:
        got = database.es_terreno({"titulo": titulo, "tipo_propiedad": tipo})
        check(got == esperado, f"es_terreno({titulo[:34]!r})", f"esperaba {esperado}, dio {got}")

    print("\nFiltro de operación (descartar rentas)")
    for op, esperado in [("Venta", True), ("Renta", False), ("rent", False), (None, True)]:
        got = database.es_venta({"operacion": op})
        check(got == esperado, f"es_venta({op!r})", f"esperaba {esperado}, dio {got}")

    print("\nFiltrar() descarta lo que no debe entrar al mapa")
    entrada = [
        anuncio("v1", "inmuebles24"),
        {**anuncio("v2", "inmuebles24"), "zona_estado": "fuera", "zona": None},
        {**anuncio("v3", "inmuebles24"), "titulo": "Casa con jardín", "tipo_propiedad": "Casa"},
        {**anuncio("v4", "inmuebles24"), "precio": None},
    ]
    validos, motivos = database.filtrar(entrada)
    check(len(validos) == 1, "solo 1 de 4 pasa el filtro", f"pasaron={len(validos)}")
    check(motivos["fuera_de_zona"] == 1, "cuenta 1 fuera de zona")
    check(motivos["no_terreno"] == 1, "cuenta 1 que no es terreno")
    check(motivos["sin_precio"] == 1, "cuenta 1 sin precio")

    print("\n" + "=" * 62)
    if fallas:
        print(f"FALLARON {len(fallas)} verificacion(es):")
        for f in fallas:
            print(f"  - {f}")
        return 1
    print("Todo en orden: los blindajes y filtros funcionan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
