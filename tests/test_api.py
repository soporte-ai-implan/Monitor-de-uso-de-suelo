"""
Verifica que la API responda y que los encabezados CORS salgan.

Sin CORS el navegador bloquea el fetch() del dashboard SIN decir por que, y se
ve igual que si la API estuviera caida. Por eso se prueba explicitamente.

Uso:  python tests/test_api.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402

fallas: list[str] = []


def check(cond: bool, nombre: str, extra: str = "") -> None:
    print(f"  [{'ok ' if cond else 'MAL'}] {nombre}" + (f"  ({extra})" if extra else ""))
    if not cond:
        fallas.append(nombre + (f" — {extra}" if extra else ""))


def main() -> int:
    c = TestClient(api.app)

    print("Endpoints responden")
    for ruta in ["/", "/api", "/salud", "/api/monitor-terrenos", "/api/zonas", "/api/resumen", "/api/corridas"]:
        r = c.get(ruta)
        check(r.status_code == 200, f"GET {ruta}", f"HTTP {r.status_code}")

    print("\nEl dashboard se sirve desde el mismo servicio (adiós CORS)")
    raiz = c.get("/")
    check("text/html" in raiz.headers.get("content-type", ""),
          "GET / devuelve HTML, no JSON", raiz.headers.get("content-type", ""))
    check("Monitor de Suelo" in raiz.text, "el HTML es el dashboard")
    for asset in ["/geo.js", "/zonas.js", "/puntos_demo.js"]:
        r = c.get(asset)
        check(r.status_code == 200, f"sirve {asset}", f"HTTP {r.status_code}")
    z = c.get("/zonas.js")
    check("TORREON_ZONAS" in z.text, "zonas.js trae la variable esperada")
    check(c.get("/api").json().get("servicio") is not None,
          "el índice JSON se movió a /api y sigue vivo")

    print("\nEl scheduler integrado viene apagado por omisión")
    check(api.SCHEDULER_EN_API is False,
          "SCHEDULER_EN_API apagado si no se define",
          "si estuviera prendido, levantar la API en local pondría a scrapear")

    print("\nGuardia anti-reinicio (protege el crédito de Apify)")
    import datetime as _dt

    original = api.database.ultima_corrida
    try:
        # Sin corridas previas -> sí debe correr
        api.database.ultima_corrida = lambda: None
        check(api._toca_correr() is True, "sin corridas previas, corre")

        # Corrida hace 10 minutos -> NO debe correr (esto es un reinicio)
        hace_10min = (_dt.datetime.now() - _dt.timedelta(minutes=10)).isoformat()
        api.database.ultima_corrida = lambda: {"fin": hace_10min, "estatus": "ok"}
        check(api._toca_correr() is False,
              "tras un reinicio reciente NO vuelve a scrapear",
              "sin esto, 20 reinicios = 20 llamadas a Apify")

        # Corrida hace 25 horas -> sí debe correr
        hace_25h = (_dt.datetime.now() - _dt.timedelta(hours=25)).isoformat()
        api.database.ultima_corrida = lambda: {"fin": hace_25h, "estatus": "ok"}
        check(api._toca_correr() is True, "pasadas las 24 h sí corre")

        # Corrida sin fecha de fin (quedó a medias) -> corre
        api.database.ultima_corrida = lambda: {"fin": None, "estatus": "en_proceso"}
        check(api._toca_correr() is True, "si la última quedó sin cerrar, corre")

        # Fecha corrupta -> corre (no se queda trabado)
        api.database.ultima_corrida = lambda: {"fin": "no-es-fecha", "estatus": "ok"}
        check(api._toca_correr() is True, "con fecha ilegible no se traba, corre")
    finally:
        api.database.ultima_corrida = original

    print("\nForma de la respuesta que consume el mapa")
    d = c.get("/api/monitor-terrenos").json()
    for llave in ("total", "ultima_actualizacion", "terrenos", "fuentes"):
        check(llave in d, f"/api/monitor-terrenos trae '{llave}'")
    check(isinstance(d.get("terrenos"), list), "'terrenos' es una lista")

    # 'fuentes' tiene DOS formas y hay que probar las dos por separado, porque
    # antes esto leia la base de verdad: con la base recien creada salia la
    # forma de respaldo y la prueba pasaba, y en cuanto habia una corrida
    # guardada salia la otra y tronaba. O sea que fallaba solo despues de la
    # primera corrida real, que es el peor momento para enterarse.
    original = api.database.ultima_corrida
    try:
        api.database.ultima_corrida = lambda: None
        f = c.get("/api/monitor-terrenos").json()["fuentes"]
        check(f["descartadas"] == ["vivanuncios"],
              "sin corridas: declara Vivanuncios como descartada", str(f))

        api.database.ultima_corrida = lambda: {"detalle": {"fuentes": {
            "inmuebles24": {"estatus": "ok", "crudos": 120},
            "pincali": {"estatus": "ok", "crudos": 0},
        }}}
        f = c.get("/api/monitor-terrenos").json()["fuentes"]
        check(f["inmuebles24"]["estatus"] == "ok",
              "con corrida: reporta el estatus real por portal", str(f))
        check(f["pincali"]["estatus"] == "vacia",
              "un 'ok' con cero anuncios se reetiqueta 'vacia'", str(f))
    finally:
        api.database.ultima_corrida = original

    print("\nGeoJSON de zonas")
    z = c.get("/api/zonas").json()
    check(z.get("type") == "FeatureCollection", "es un FeatureCollection", str(z.get("type")))
    check(len(z.get("features", [])) == 5, "trae las 5 zonas", str(len(z.get("features", []))))
    nombres = [f["properties"]["zona"] for f in z["features"]]
    check(all(n.startswith("Zona ") for n in nombres), "todas las zonas traen nombre")
    check(z["features"][0]["geometry"]["type"] in ("Polygon", "MultiPolygon"),
          "la geometría es Polygon o MultiPolygon")

    print("\nCORS (el dashboard vive en otro dominio)")
    r = c.get("/api/monitor-terrenos", headers={"Origin": "https://trcimplan.gob.mx"})
    acao = r.headers.get("access-control-allow-origin")
    check(acao is not None, "responde Access-Control-Allow-Origin", str(acao))

    pre = c.options(
        "/api/monitor-terrenos",
        headers={
            "Origin": "https://trcimplan.gob.mx",
            "Access-Control-Request-Method": "GET",
        },
    )
    check(pre.status_code in (200, 204), "el preflight OPTIONS pasa", f"HTTP {pre.status_code}")
    check(pre.headers.get("access-control-allow-origin") is not None,
          "el preflight trae Access-Control-Allow-Origin")

    print("\nResumen por zona")
    s = c.get("/api/resumen").json()
    for llave in ("total_terrenos", "precio_m2_promedio_ciudad", "zonas"):
        check(llave in s, f"/api/resumen trae '{llave}'")
    check(isinstance(s.get("zonas"), list), "'zonas' es una lista")

    print("\nSalud (para el uptime check del scheduler)")
    h = c.get("/salud").json()
    check(h.get("ok") is True, "/salud dice ok")
    check("estatus_ultima_corrida" in h, "/salud reporta el estatus de la última corrida",
          str(h.get("estatus_ultima_corrida")))

    print("\n" + "=" * 62)
    if fallas:
        print(f"FALLARON {len(fallas)} verificacion(es):")
        for f in fallas:
            print(f"  - {f}")
        return 1
    print("Todo en orden: la API responde y CORS está puesto")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
