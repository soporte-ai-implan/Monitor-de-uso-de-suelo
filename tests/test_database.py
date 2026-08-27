"""
Prueba los dos blindajes contra bajas falsas y los filtros de código.

Usa una base temporal, no toca terrenos.db.

Uso:  python tests/test_database.py
"""
import pathlib
import sys
import tempfile
from datetime import date

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

    # El piso es $10/m2, no $50, a propósito: el suelo rural grande vale poco
    # por m2 y con $50 se tiraban predios ejidales legítimos. Los errores de
    # captura los atrapa antes la compuerta de precio TOTAL (mínimo $50,000).
    # Ver compuertas.py y tests/test_compuertas.py.
    print("\nDetección de precios atípicos (errores de captura del portal)")
    casos_ppm = [
        (8.02,     False, "el caso real: terreno de 561 m2 anunciado en $4,500"),
        (9.99,     False, "justo abajo del mínimo"),
        (10.0,     True,  "el mínimo exacto sí pasa"),
        (43.0,     True,  "predio ejidal de 4.6 ha: barato por m2 pero legítimo"),
        (300.0,    True,  "predio rural barato, legítimo"),
        (4650.0,   True,  "precio urbano típico"),
        (27833.33, True,  "caro pero plausible en zona premium"),
        (50000.0,  True,  "el máximo exacto sí pasa"),
        (50000.01, False, "arriba del máximo"),
        (None,     False, "sin precio"),
        ("no",     False, "texto basura"),
    ]
    for valor, esperado, desc in casos_ppm:
        got = database.precio_m2_confiable(valor)
        check(got == esperado, f"precio_m2_confiable({valor!r}) — {desc}",
              f"esperaba {esperado}, dio {got}")

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

    print("\nRECLASIFICAR — la base no debe quedarse con reglas viejas")
    # El caso real: i24-145257488 ("La Nueva Laguna"), guardado el 28/07/2026
    # como "Zona 2 / borde" antes de que existiera el guardián municipal. Sus
    # coordenadas caen FUERA de Torreón; hoy zonas.py lo dice y el tablero lo
    # descartaba, pero la base lo seguía contando: 97 contra 98 en pantalla.
    rancio = anuncio("rancio1", "inmuebles24")
    rancio.update({"lat": 25.6146312, "lon": -103.4240849,
                   "zona": "Zona 2 - Zona Norte", "zona_estado": "borde",
                   "zona_motivo": "zona más cercana (0.4 km)"})
    database.guardar_anuncios([rancio], fuentes_ok=["inmuebles24"])

    import zonas
    dice = zonas.clasificar(rancio["lon"], rancio["lat"], rancio["ciudad"],
                            rancio["nombre_colonia"], rancio["ubicacion"], rancio["titulo"])
    check(dice["estado"] == "fuera",
          "zonas.py hoy dice que ese punto cae fuera del municipio", dice["estado"])

    antes = [a for a in database.obtener_activos() if a["id_anuncio"] == "rancio1"][0]
    check(antes["zona_estado"] == "borde", "la fila entra con la clasificación vieja")

    rz = database.reclasificar_zonas()
    check(rz["reclasificados"] >= 1, "detecta al menos una fila desactualizada",
          f"reclasificados={rz['reclasificados']}")

    despues = [a for a in database.obtener_activos() if a["id_anuncio"] == "rancio1"][0]
    check(despues["zona_estado"] == "fuera", "queda marcada como fuera", str(despues["zona_estado"]))
    check(despues["zona"] is None, "y sin zona asignada", str(despues["zona"]))
    check(despues["zona_motivo"] and "municipio" in despues["zona_motivo"],
          "conserva el motivo, el descarte es auditable", str(despues["zona_motivo"]))
    check(any(a["id_anuncio"] == "rancio1" for a in database.obtener_activos()),
          "NO se borra la fila: el descarte se registra, no se esconde")

    # Idempotente: correrla dos veces seguidas no debe mover nada mas.
    rz2 = database.reclasificar_zonas()
    check(rz2["reclasificados"] == 0, "una segunda pasada ya no cambia nada",
          f"reclasificados={rz2['reclasificados']}")

    print("\nRESPALDO — el historial no se puede reconstruir, asi que se copia")
    respaldos = database.DB_PATH.parent / "respaldos"
    copias = sorted(respaldos.glob("terrenos-*.db"))
    check(len(copias) == 1, "guardar_anuncios dejo una copia de la base",
          f"copias={len(copias)}")
    check(copias and copias[0].stat().st_size > 0, "la copia no esta vacia")

    # Que sea una base legible de verdad, no un archivo a medias: es la
    # diferencia entre tener respaldo y creer que se tiene.
    if copias:
        import sqlite3 as _sq
        c = _sq.connect(copias[0])
        try:
            n = c.execute("SELECT COUNT(*) FROM anuncios").fetchone()[0]
            check(n > 0, "la copia se abre y trae los anuncios", f"filas={n}")
        except Exception as e:  # noqa: BLE001
            check(False, "la copia se abre y trae los anuncios", str(e))
        finally:
            c.close()

    # Sin base todavia no hay nada que copiar, y eso no es un error.
    original = database.DB_PATH
    try:
        database.DB_PATH = database.DB_PATH.parent / "no-existe.db"
        check(database.respaldar_base() is None,
              "sin base previa regresa None en vez de tronar")
    finally:
        database.DB_PATH = original

    # La rotacion conserva los N mas recientes y no crece sin fin.
    for dia in range(1, 11):
        (respaldos / f"terrenos-2026-01-{dia:02d}.db").write_bytes(b"x")
    database.respaldar_base(conservar=7)
    quedan = sorted(respaldos.glob("terrenos-*.db"))
    check(len(quedan) == 7, "la rotacion deja solo los 7 mas recientes",
          f"quedan={len(quedan)}")
    check(quedan[-1].name.startswith(f"terrenos-{date.today().isoformat()}"),
          "el mas reciente es el de hoy", quedan[-1].name)

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
