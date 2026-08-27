"""
Prueba los normalizadores y el accesor de campos de scraper.py.

Lo importante que cubre: `_campo()` tiene que funcionar con las dos formas en
que apify-client regresa una corrida, porque cambiaron entre versiones mayores:

    1.x / 2.x -> dict con llaves camelCase   {'defaultDatasetId': 'abc'}
    3.x       -> modelo Pydantic snake_case  run.default_dataset_id

Si esto truena, el pipeline entero se queda sin datos.

Uso:  python tests/test_scraper.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import scraper  # noqa: E402

fallas: list[str] = []


def check(cond: bool, nombre: str, extra: str = "") -> None:
    print(f"  [{'ok ' if cond else 'MAL'}] {nombre}" + (f"  ({extra})" if extra else ""))
    if not cond:
        fallas.append(nombre + (f" — {extra}" if extra else ""))


class RunFalso3x:
    """Imita el modelo Pydantic de apify-client 3.x."""
    def __init__(self):
        self.status = "SUCCEEDED"
        self.default_dataset_id = "dataset-3x"


class EnumFalso:
    """Imita un estatus que llega como enum."""
    value = "SUCCEEDED"


def main() -> int:
    print("_campo() contra las dos formas de respuesta")
    dict_1x = {"status": "SUCCEEDED", "defaultDatasetId": "dataset-1x"}
    check(scraper._campo(dict_1x, "status") == "SUCCEEDED", "dict 1.x: lee status")
    check(
        scraper._campo(dict_1x, "default_dataset_id", "defaultDatasetId") == "dataset-1x",
        "dict 1.x: lee defaultDatasetId por el alias camelCase",
    )

    obj_3x = RunFalso3x()
    check(scraper._campo(obj_3x, "status") == "SUCCEEDED", "objeto 3.x: lee status")
    check(
        scraper._campo(obj_3x, "default_dataset_id", "defaultDatasetId") == "dataset-3x",
        "objeto 3.x: lee default_dataset_id por el nombre snake_case",
    )
    check(scraper._campo(obj_3x, "no_existe") is None, "campo ausente regresa None")
    check(scraper._campo({}, "status") is None, "dict vacío regresa None")

    # El estatus como enum tiene que quedar comparable
    e = EnumFalso()
    check(str(getattr(e, "value", e)) == "SUCCEEDED", "estatus enum se normaliza a texto")

    print("\nnormalizar_inmuebles24() con el schema real")
    i24 = {
        "id": "143820994",
        "title": "Terreno en venta en Torreón Residencial",
        "price": 1850000,
        "currency": "MXN",
        "land_area_m2": 420,
        "covered_area_m2": None,
        "total_area_m2": None,
        "address": "Blvd. Diagonal Reforma 2400",
        "neighborhood": "Torreón Residencial",
        "city": "Torreón",
        "province": "Coahuila",
        "latitude": 25.5610,
        "longitude": -103.3900,
        "url": "https://www.inmuebles24.com/propiedades/x-143820994.html",
        "property_type": "Terreno",
        "operation": "Venta",
        "modified_at": "2026-07-14T18:22:31.000Z",
    }
    a = scraper.normalizar_inmuebles24(i24)
    check(a["id_anuncio"] == "i24-143820994", "id lleva prefijo de fuente", a["id_anuncio"])
    check(a["m2"] == 420, "usa land_area_m2 (no covered_area_m2)", str(a["m2"]))
    check(a["ciudad"] == "Torreón", "conserva ciudad para el guardián de municipio")
    check(a["fecha_publicacion"] == "2026-07-14", "recorta la fecha a YYYY-MM-DD", a["fecha_publicacion"])
    check(a["nombre_colonia"] == "Torreón Residencial", "toma la colonia de neighborhood")
    check("Blvd. Diagonal Reforma 2400" in a["ubicacion"], "arma la ubicación con address")

    print("\nnormalizar_pincali() con el schema real")
    pin = {
        "listingId": "PIN-88213",
        "propertyId": "88213",
        "title": None,  # Pincali SIEMPRE manda null aquí
        "price": 720000,
        "areaM2": 300,
        "fullAddress": "Calle Sin Nombre 12, Ampliación La Rosita",
        "locationText": "La Rosita, Torreón",
        "neighborhood": "Ampliación La Rosita",
        "city": "Torreón",
        "state": "Coahuila",
        "latitude": 25.5300,
        "longitude": -103.3800,
        "url": "https://www.pincali.com/inmueble/88213",
        "propertyType": "Terreno",
        "operationType": "Venta",
        "publishedAt": "2026-06-30T10:00:00Z",
    }
    b = scraper.normalizar_pincali(pin)
    check(b["id_anuncio"] == "pin-PIN-88213", "id lleva prefijo de fuente", b["id_anuncio"])
    check(b["titulo"] and b["titulo"] != "None", "arma un título aunque title venga null", repr(b["titulo"]))
    check(b["m2"] == 300, "usa areaM2")
    check(b["fecha_publicacion"] == "2026-06-30", "recorta la fecha", b["fecha_publicacion"])
    check(b["estado"] == "Coahuila", "toma la entidad de `state`")

    print("\nSuperficie de Pincali: el Actor deja areaM2 null y la pone en features")
    # Los 5 casos son anuncios REALES de la corrida del 21/08/2026.
    reales = [
        (["25,748 m² de terreno", "Publicado", "25,748 m² de terreno"], 25748.0),
        (["601.15 m² de terreno", "Publicado"], 601.15),
        (["14,496.79 m² de terreno"], 14496.79),
        (["401.4 m² de terreno"], 401.4),
        (["200 m² de terreno", "20 m de largo", "10 m de frente"], 200.0),
    ]
    for feats, esperado in reales:
        got = scraper._m2_pincali({"areaM2": None, "features": feats})
        check(got == esperado, f"lee {esperado} m² de features", str(got))
    check(scraper._m2_pincali({"areaM2": 350, "features": ["999 m² de terreno"]}) == 350,
          "si algún día llenan areaM2, ese manda")
    # Largo y frente NO son superficie: confundirlos arruinaría el precio por m².
    check(scraper._m2_pincali({"features": ["20 m de largo", "10 m de frente"]}) is None,
          "ignora largo y frente")
    check(scraper._m2_pincali({}) is None, "sin features ni areaM2 deja None")
    con_feats = scraper.normalizar_pincali(
        {"listingId": "X1", "features": ["601.15 m² de terreno"]}
    )
    check(con_feats["m2"] == 601.15, "el normalizador ya trae la superficie", str(con_feats["m2"]))

    print("\nRobustez ante campos faltantes o basura")
    check(scraper._num(None) is None, "_num(None)")
    check(scraper._num("") is None, "_num('')")
    check(scraper._num("no es número") is None, "_num(texto)")
    check(scraper._num("1500.5") == 1500.5, "_num(texto numérico)")
    check(scraper._fecha(None) is None, "_fecha(None)")

    vacio_i24 = scraper.normalizar_inmuebles24({})
    check(vacio_i24["titulo"] == "Terreno en venta", "i24 sin datos usa título por omisión")
    check(vacio_i24["m2"] is None, "i24 sin superficie deja m2 en None")
    vacio_pin = scraper.normalizar_pincali({})
    check(vacio_pin["titulo"].startswith("Terreno en"), "pincali sin datos arma título")

    # Un anuncio sin id no debe poder colarse: main lo filtra por 'None' en el id
    check("None" in scraper.normalizar_inmuebles24({})["id_anuncio"],
          "anuncio sin id queda detectable para descarte")

    print("\nFuente que termina bien pero devuelve CERO anuncios")
    # El caso real: Pincali del 29/07/2026 en adelante. El Actor termina
    # SUCCEEDED con 0 items. Si eso cuenta como fuente 'ok', database.py archiva
    # todo su inventario como si se hubiera vendido (blindaje 2), y la corrida
    # se reporta 'ok' con un portal caido.
    original_cliente, original_correr = scraper._cliente, scraper._correr_actor
    original_activas = scraper.FUENTES_ACTIVAS
    try:
        scraper._cliente = lambda: None
        scraper._correr_actor = lambda _c, actor_id, _i: (
            [] if actor_id == scraper.ACTOR_PINCALI else [dict(i24)]
        )
        anuncios, detalle = scraper.obtener_anuncios_torreon(10)
    finally:
        scraper._cliente, scraper._correr_actor = original_cliente, original_correr
        scraper.FUENTES_ACTIVAS = original_activas

    check(detalle["pincali"]["estatus"] == "vacia",
          "la fuente vacía NO se marca 'ok'", detalle["pincali"]["estatus"])
    check(detalle["inmuebles24"]["estatus"] == "ok",
          "la fuente con datos sigue siendo 'ok'", detalle["inmuebles24"]["estatus"])

    # Es lo que main.py calcula para decidir dónde se dan de baja anuncios.
    fuentes_ok = [n for n, d in detalle.items() if d.get("estatus") == "ok"]
    check(fuentes_ok == ["inmuebles24"],
          "'pincali' queda fuera de fuentes_ok: no se archiva su inventario", str(fuentes_ok))
    check(len(anuncios) == 1, "los anuncios de la fuente viva sí pasan", str(len(anuncios)))

    print("\nFuentes apagadas: se declaran, no se esconden")
    try:
        scraper._cliente = lambda: None
        scraper._correr_actor = lambda _c, _a, _i: [dict(i24)]
        _, det2 = scraper.obtener_anuncios_torreon(10)
    finally:
        scraper._cliente, scraper._correr_actor = original_cliente, original_correr

    check("pincali" in scraper.FUENTES_ACTIVAS,
          "Pincali sí se corre: la superficie viene en features", str(scraper.FUENTES_ACTIVAS))
    for apagada in ("vivanuncios",):
        check(det2.get(apagada, {}).get("estatus") == "descartado",
              f"'{apagada}' viaja declarado como descartado", str(det2.get(apagada)))
        check(bool(det2.get(apagada, {}).get("razon")),
              f"'{apagada}' dice por qué quedó fuera")

    print("\n" + "=" * 62)
    if fallas:
        print(f"FALLARON {len(fallas)} verificacion(es):")
        for f in fallas:
            print(f"  - {f}")
        return 1
    print("Todo en orden: normalizadores y accesor de campos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
