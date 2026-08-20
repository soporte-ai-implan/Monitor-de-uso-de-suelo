"""
zonas.py — asignacion de zona por geometria real. Espejo exacto de web/geo.js.

Las dos implementaciones (Python en el pipeline, JS en el mapa) tienen que dar
el mismo resultado, si no la base de datos y el dashboard se contradicen.
tests/test_zonas.py verifica que coincidan.

Decision clave, medida contra este mismo geojson:
    Gomez Palacio (col. Filadelfia)  ->  0.25 km del borde de Zona 1
    Gomez Palacio centro             ->  2.43 km
    Torreon zona industrial oriente  ->  2.29 km   (legitimo)
Hay puntos de Durango mas cerca que puntos validos de Torreon, asi que la
distancia NO separa las dos ciudades. El guardian principal es el municipio
declarado por el anuncio; la geometria solo asigna zona.
"""
from __future__ import annotations

import json
import math
import pathlib
import unicodedata
from typing import Any, Iterable

RAIZ = pathlib.Path(__file__).resolve().parent
GEOJSON = RAIZ / "data" / "torreon_zonas_final.geojson"
MUNICIPIO = RAIZ / "data" / "torreon_municipio.geojson"

# Zona 6 no tiene poligono propio: es una REGLA — lo que esta dentro del
# municipio y lejos de la mancha urbana. Definirla asi evita recortar geometrias
# y la deja exacta por construccion.
ZONA_PERIFERIA = "Zona 6 - Periferia Sur"

COLOR_ZONA = {
    "Zona 1 - Poniente y Centro Histórico": "#5B4B8A",
    "Zona 2 - Zona Norte": "#E95026",
    "Zona 3 - Centro-Norte": "#1B5286",   # re-escalonado: el #15467A quedaba
                                          # fuera de la banda de luminosidad
    "Zona 4 - Oriente": "#C6881E",        # re-escalonado: contraste 2.99 -> 3.03
    "Zona 5 - Sur Oriente": "#1A7A47",
    ZONA_PERIFERIA: "#A85751",
}

# Se subio de 1.5 a 3.0 km una vez que el guardian empezo a descartar por
# NOMBRE de municipio. Antes la distancia era la unica defensa contra Gomez
# Palacio y habia que tenerla corta; ahora Gomez y Lerdo se frenan porque el
# anuncio los menciona, asi que la distancia puede cubrir su verdadero trabajo:
# alcanzar la periferia rural de Torreon que las zonas SEPOMEX no cubren.
# Medido sobre 20 anuncios reales, esto recupera predios legitimos a ~2 km sin
# dejar entrar nada de Durango.
TOLERANCIA_KM = 3.0
KM_POR_GRADO_LAT = 111.32

# Municipios vecinos. Si alguno aparece por su nombre en el texto de ubicacion,
# el anuncio NO es de Torreon y se descarta.
MUNICIPIOS_VECINOS = (
    "gomez palacio", "lerdo",            # Durango, del otro lado del Rio Nazas
    "matamoros", "viesca", "san pedro",  # Coahuila, colindantes
    "francisco i madero", "fco i madero",
    # Torreon es Coahuila: si el anuncio dice Durango, no es de aqui. Atrapa
    # los anuncios de Gomez o Lerdo que solo nombran el estado.
    "durango",
)

MUNICIPIO_PROPIO = "torreon"

_cache: dict | None = None
_cache_municipio: dict | None = None


def cargar_zonas() -> dict:
    """Lee el geojson una sola vez."""
    global _cache
    if _cache is None:
        _cache = json.loads(GEOJSON.read_text(encoding="utf-8"))
    return _cache


def geometria_municipio() -> dict | None:
    """
    Limite municipal oficial de Torreon (OpenStreetMap rel. 5606549, ODbL).

    Es el guardian principal, y resuelve de raiz lo que las heuristicas hacian
    a medias:

      · Las 5 zonas son union de colonias SEPOMEX y solo cubren la mancha
        urbana (hasta lat 25.48). El municipio llega hasta lat 24.79: todo el
        sur rural quedaba fuera y se descartaba como si fuera otro municipio.
      · Antes se decidia por el TEXTO del anuncio mas una tolerancia de
        distancia. Ahora se decide por geometria: dentro del poligono es
        Torreon, y punto.

    Validado contra los 101 terrenos de la primera corrida real: 101 de 101
    caen dentro. Gomez Palacio, Lerdo y Matamoros quedan fuera.
    """
    global _cache_municipio
    if _cache_municipio is None:
        if not MUNICIPIO.exists():
            return None
        gj = json.loads(MUNICIPIO.read_text(encoding="utf-8"))
        _cache_municipio = gj["features"][0]["geometry"]
    return _cache_municipio


def en_municipio(lon: float, lat: float) -> bool | None:
    """True/False si hay poligono municipal; None si el archivo no esta."""
    geom = geometria_municipio()
    if geom is None:
        return None
    return en_geometria(lon, lat, geom)


def normalizar(txt: Any) -> str:
    if not txt:
        return ""
    s = unicodedata.normalize("NFD", str(txt))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def municipio_valido(*textos: Any) -> bool | None:
    """
    Decide si el anuncio es de Torreon mirando TODO el texto de ubicacion.

    Regresa True (es de Torreon), False (es de otro municipio) o None (no hay
    forma de saberlo; que decida la geometria).

    Por que se miran varios campos y no solo `city`: Inmuebles24 recorre su
    jerarquia de ubicacion segun el anuncio. Medido sobre 20 anuncios reales:

        6 anuncios ->  city='Torreón'   neighborhood='<colonia>'   (bien)
       14 anuncios ->  city='Coahuila'  neighborhood='Torreón'     (corrido)

    Leer solo `city` rechazaba esos 14 por "municipio distinto: Coahuila", y al
    reclasificarlos 11 caian dentro o al borde de una zona real. O sea, se
    estaban tirando terrenos buenos de Torreon.

    La regla se invierte respecto a la version anterior: en vez de exigir que
    diga "Torreon", se descarta solo si aparece un municipio VECINO con nombre
    propio. Un vecino nombrado gana sobre la mencion de Torreon, porque
    "a 10 min de Torreon, en Gomez Palacio" es un anuncio de Gomez Palacio.
    """
    blob = normalizar(" | ".join(str(t) for t in textos if t))
    if not blob:
        return None
    if any(v in blob for v in MUNICIPIOS_VECINOS):
        return False
    if MUNICIPIO_PROPIO in blob:
        return True
    return None


# ---------- geometria ----------

def _anillos(geom: dict) -> list[tuple[list, list]]:
    t = geom.get("type")
    if t == "Polygon":
        polys = [geom["coordinates"]]
    elif t == "MultiPolygon":
        polys = geom["coordinates"]
    else:
        return []
    return [(p[0], p[1:]) for p in polys]


def _en_anillo(lon: float, lat: float, ring: list) -> bool:
    dentro = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            dentro = not dentro
        j = i
    return dentro


def en_geometria(lon: float, lat: float, geom: dict) -> bool:
    for ext, huecos in _anillos(geom):
        if _en_anillo(lon, lat, ext):
            if not any(_en_anillo(lon, lat, h) for h in huecos):
                return True
    return False


def _km_por_grado_lon(lat: float) -> float:
    return KM_POR_GRADO_LAT * math.cos(math.radians(lat))


def _dist_segmento(lon: float, lat: float, a: list, b: list) -> float:
    kx = _km_por_grado_lon(lat)
    px, py = (lon - a[0]) * kx, (lat - a[1]) * KM_POR_GRADO_LAT
    bx, by = (b[0] - a[0]) * kx, (b[1] - a[1]) * KM_POR_GRADO_LAT
    largo2 = bx * bx + by * by
    t = 0.0 if largo2 == 0 else max(0.0, min(1.0, (px * bx + py * by) / largo2))
    dx, dy = px - t * bx, py - t * by
    return math.hypot(dx, dy)


def distancia_a_geometria(lon: float, lat: float, geom: dict) -> float:
    if en_geometria(lon, lat, geom):
        return 0.0
    minimo = math.inf
    for ext, huecos in _anillos(geom):
        for ring in [ext, *huecos]:
            for i in range(len(ring)):
                d = _dist_segmento(lon, lat, ring[i - 1], ring[i])
                if d < minimo:
                    minimo = d
    return minimo


def nombre_de(feature: dict) -> str:
    return (feature.get("properties") or {}).get("zona") or "(sin nombre)"


# ---------- clasificacion ----------

def clasificar(lon: float, lat: float, *textos_ubicacion: Any) -> dict:
    """
    Regresa {'zona', 'color', 'estado', 'distancia_km', 'motivo'}.
      'dentro' -> point-in-polygon exacto
      'borde'  -> fuera de todo pero a <= TOLERANCIA_KM; se asigna la mas cercana
      'fuera'  -> se descarta, no entra al mapa

    `textos_ubicacion` son todos los campos con texto de ubicacion del anuncio
    (ciudad, colonia, direccion, titulo). Ver municipio_valido() para el porque.
    """
    # 1) Guardian geometrico: el limite municipal manda sobre cualquier texto.
    dentro_mun = en_municipio(lon, lat)
    if dentro_mun is False:
        return {
            "zona": None, "color": "#8A8178", "estado": "fuera",
            "distancia_km": None,
            "motivo": "fuera del municipio de Torreón",
        }

    # 2) Solo si no hay poligono municipal se cae al guardian por texto, que es
    #    el metodo viejo y mas fragil.
    if dentro_mun is None and municipio_valido(*textos_ubicacion) is False:
        blob = " ".join(str(t) for t in textos_ubicacion if t)
        vecino = next(
            (v for v in MUNICIPIOS_VECINOS if v in normalizar(blob)), "otro municipio"
        )
        return {
            "zona": None, "color": "#8A8178", "estado": "fuera",
            "distancia_km": None,
            "motivo": f"el anuncio menciona {vecino}, no Torreón",
        }

    features = cargar_zonas().get("features", [])

    for f in features:
        if en_geometria(lon, lat, f["geometry"]):
            n = nombre_de(f)
            return {
                "zona": n, "color": COLOR_ZONA.get(n, "#8A8178"),
                "estado": "dentro", "distancia_km": 0.0,
                "motivo": "point-in-polygon",
            }

    mejor, mejor_d = None, math.inf
    for f in features:
        d = distancia_a_geometria(lon, lat, f["geometry"])
        if d < mejor_d:
            mejor, mejor_d = f, d

    # Cerca de la mancha urbana: lo absorbe la zona mas proxima.
    if mejor is not None and mejor_d <= TOLERANCIA_KM:
        n = nombre_de(mejor)
        return {
            "zona": n, "color": COLOR_ZONA.get(n, "#8A8178"),
            "estado": "borde", "distancia_km": mejor_d,
            "motivo": f"zona más cercana ({mejor_d:.1f} km)",
        }

    # Dentro del municipio pero lejos de toda zona urbana: es la Periferia Sur.
    # No se absorbe en una zona urbana a proposito — un predio rustico a $850/m2
    # mezclado con lotes urbanos a $4,500 le arruinaria la mediana a esa zona.
    if dentro_mun is True:
        return {
            "zona": ZONA_PERIFERIA, "color": COLOR_ZONA[ZONA_PERIFERIA],
            "estado": "periferia", "distancia_km": mejor_d,
            "motivo": f"dentro del municipio, {mejor_d:.1f} km fuera de la mancha urbana",
        }

    return {
        "zona": None, "color": "#8A8178", "estado": "fuera",
        "distancia_km": mejor_d,
        "motivo": f"a {mejor_d:.1f} km de cualquier zona",
    }


def punto_aleatorio_en_zona(nombre_zona: str, semilla: Any = None) -> tuple[float, float] | None:
    """
    Fallback cuando el geocoding no da coordenadas: un punto DENTRO del poligono
    de la zona, nunca aleatorio en todo el mapa.

    Es determinista respecto a `semilla` (usa el id del anuncio) para que el
    mismo anuncio no brinque de lugar entre corridas.
    """
    import random

    features = cargar_zonas().get("features", [])
    geom = next((f["geometry"] for f in features if nombre_de(f) == nombre_zona), None)
    if geom is None:
        return None

    coords = [c for ext, _ in _anillos(geom) for c in ext]
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]

    rng = random.Random(str(semilla)) if semilla is not None else random.Random()
    for _ in range(800):
        lon = rng.uniform(min(lons), max(lons))
        lat = rng.uniform(min(lats), max(lats))
        if not en_geometria(lon, lat, geom):
            continue
        # Las zonas SEPOMEX no anidan perfectamente dentro del limite municipal:
        # ~2% de la Zona 1 (Poniente, junto al rio) queda del lado de Durango.
        # Sin esta comprobacion el fallback colocaria un punto que despues la
        # propia clasificacion rechaza — el pipeline se contradiria a si mismo.
        if en_municipio(lon, lat) is False:
            continue
        return lat, lon
    return None


def bounds() -> tuple[float, float, float, float]:
    """(lat_min, lon_min, lat_max, lon_max) de todas las zonas."""
    coords = [
        c
        for f in cargar_zonas().get("features", [])
        for ext, _ in _anillos(f["geometry"])
        for c in ext
    ]
    lats = [c[1] for c in coords]
    lons = [c[0] for c in coords]
    return min(lats), min(lons), max(lats), max(lons)


def resumen_lista(anuncios: Iterable[dict]) -> dict:
    """Contador de estados, util para logs del pipeline."""
    conteo = {"dentro": 0, "borde": 0, "fuera": 0, "sin_coords": 0}
    for a in anuncios:
        lat, lon = a.get("lat"), a.get("lon")
        if lat is None or lon is None:
            conteo["sin_coords"] += 1
            continue
        conteo[clasificar(lon, lat, *textos_de(a))["estado"]] += 1
    return conteo


def textos_de(anuncio: dict) -> tuple:
    """Todos los campos con pistas de ubicacion de un anuncio, en un solo lugar."""
    return (
        anuncio.get("ciudad"),
        anuncio.get("nombre_colonia"),
        anuncio.get("ubicacion"),
        anuncio.get("titulo"),
    )
