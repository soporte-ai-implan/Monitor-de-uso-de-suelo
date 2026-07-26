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
    for ruta in ["/", "/salud", "/api/monitor-terrenos", "/api/zonas", "/api/resumen", "/api/corridas"]:
        r = c.get(ruta)
        check(r.status_code == 200, f"GET {ruta}", f"HTTP {r.status_code}")

    print("\nForma de la respuesta que consume el mapa")
    d = c.get("/api/monitor-terrenos").json()
    for llave in ("total", "ultima_actualizacion", "terrenos", "fuentes"):
        check(llave in d, f"/api/monitor-terrenos trae '{llave}'")
    check(isinstance(d.get("terrenos"), list), "'terrenos' es una lista")
    check(d["fuentes"]["descartadas"] == ["vivanuncios"],
          "declara Vivanuncios como descartada", str(d["fuentes"]))

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
