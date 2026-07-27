"""
compuertas.py — control de calidad de los anuncios antes de publicarlos.

Cada anuncio pasa por una lista de reglas con nombre. Si falla alguna, se
rechaza y queda registrado POR CUAL regla y por que. Nada se descarta en
silencio: `reporte()` regresa el conteo por regla, y eso llega hasta el
dashboard.

Por que auditable y no solo "filtrado": esto es un dato publico de un instituto
de planeacion. Si alguien pregunta por que su terreno no aparece, o por que el
conteo bajo de un dia a otro, la respuesta tiene que existir.

Los umbrales NO son a ojo: salieron de medir los 101 terrenos de la primera
corrida real (ver docs/compuertas.md).
"""
from __future__ import annotations

import collections
import unicodedata
from typing import Any, Callable

# ---------------------------------------------------------------- umbrales

# Superficie: los reales van de 111 a 46,538 m2. Se deja holgura para lotes
# urbanos chicos y para predios rusticos grandes.
SUPERFICIE_MIN_M2 = 50.0
SUPERFICIE_MAX_M2 = 500_000.0

# Precio total: los reales arrancan en $400,000 salvo dos errores de captura
# ($4,500 y $5,000). El piso los atrapa sin tocar nada legitimo.
PRECIO_MIN = 50_000.0
PRECIO_MAX = 500_000_000.0

# Precio por m2: los reales van de $300 a $27,833 una vez quitados los dos
# errores, que daban $8 y $29 por m2.
#
# El piso es deliberadamente BAJO ($10) y no $50, aunque a primera vista $50
# parecia mas seguro. Dos razones:
#
#   1. Es redundante subirlo. Los dos errores reales ($4,500 y $5,000 de precio
#      total) ya los atrapa la compuerta de precio total, que corre antes.
#   2. Subirlo hace dano. El suelo rural grande vale legitimamente poco por m2:
#      un predio ejidal de 4 hectareas en $2 millones da $43/m2, y con piso de
#      $50 lo estariamos tirando. Justo el suelo periferico que a un instituto
#      de planeacion le interesa vigilar.
#
# Esta compuerta solo caza la incoherencia extrema entre precio y superficie.
PRECIO_M2_MIN = 10.0
PRECIO_M2_MAX = 50_000.0

PALABRAS_TERRENO = ("terreno", "terreo", "lote", "predio", "parcela", "solar", "land")

# Tipos de inmueble que NO son oferta de suelo. Solo descalifican cuando son el
# SUJETO del titulo ("Quinta en Venta en..."), no cuando aparecen como nombre
# de calle o fraccionamiento.
#
# Esto importa en Torreon: hay terrenos legitimos en "Circuito Quinta Bilbao" y
# en "Fraccionamiento Quintas del Nazas". Buscar la palabra suelta los habria
# tirado a todos.
TIPOS_NO_SUELO = (
    "casa", "departamento", "depto", "bodega", "local", "oficina",
    "edificio", "nave industrial", "quinta", "consultorio", "villa",
    "penthouse", "loft", "cabana", "hotel",
)


def normalizar(txt: Any) -> str:
    if not txt:
        return ""
    s = unicodedata.normalize("NFD", str(txt))
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _en_rango(v: Any, lo: float, hi: float) -> bool:
    n = _num(v)
    return n is not None and lo <= n <= hi


def titulo_es_de_otro_inmueble(titulo: Any) -> str | None:
    """
    Regresa el tipo de inmueble si el titulo lo declara como SUJETO.

    Los portales titulan "<Tipo> en Venta en <lugar>", asi que basta con mirar
    el arranque del titulo. Asi 'Quinta en Venta en Ampliacion Senderos' se
    rechaza y 'Propiedad en Venta - Circuito Quinta Bilbao' no.
    """
    t = normalizar(titulo)
    if not t:
        return None
    # Solo las primeras palabras: ahi va el sujeto.
    arranque = " ".join(t.split()[:3])
    for tipo in TIPOS_NO_SUELO:
        if arranque.startswith(tipo):
            return tipo
    return None


# ---------------------------------------------------------------- reglas
# Cada regla regresa None si pasa, o un texto explicando por que rechaza.

def _r_id(a: dict) -> str | None:
    idn = a.get("id_anuncio") or ""
    if not idn or "None" in str(idn):
        return "sin identificador; imposible seguirlo entre corridas"
    return None


def _r_es_terreno(a: dict) -> str | None:
    otro = titulo_es_de_otro_inmueble(a.get("titulo"))
    if otro:
        return f"el título lo anuncia como {otro}, no como suelo"

    tipo = normalizar(a.get("tipo_propiedad"))
    if tipo and any(p in tipo for p in PALABRAS_TERRENO):
        return None
    if tipo and any(p in tipo for p in TIPOS_NO_SUELO):
        return f"el portal lo tipifica como {tipo}"

    titulo = normalizar(a.get("titulo"))
    if any(p in titulo for p in PALABRAS_TERRENO):
        return None
    # Titulos genericos de Inmuebles24 ("Propiedad en Venta - <calle>") con
    # tipo declarado: se aceptan, el tipo del portal es lo unico que hay.
    if tipo:
        return None
    return "no hay nada que indique que sea un terreno"


def _r_es_venta(a: dict) -> str | None:
    op = normalizar(a.get("operacion"))
    if op and ("renta" in op or "rent" in op or "alquil" in op):
        return "está en renta, no en venta"
    return None


def _r_precio(a: dict) -> str | None:
    p = _num(a.get("precio"))
    if p is None or p <= 0:
        return "sin precio publicado"
    if not _en_rango(p, PRECIO_MIN, PRECIO_MAX):
        return (f"precio fuera de rango (${p:,.0f}); "
                f"probable error de captura del portal")
    return None


def _r_superficie(a: dict) -> str | None:
    m2 = _num(a.get("m2"))
    if m2 is None:
        return None  # sin superficie se acepta; solo no entra a estadísticas
    if not _en_rango(m2, SUPERFICIE_MIN_M2, SUPERFICIE_MAX_M2):
        return f"superficie fuera de rango ({m2:,.0f} m²)"
    return None


def _r_precio_m2(a: dict) -> str | None:
    p, m2 = _num(a.get("precio")), _num(a.get("m2"))
    if not p or not m2 or m2 <= 0:
        return None
    ppm = p / m2
    if not _en_rango(ppm, PRECIO_M2_MIN, PRECIO_M2_MAX):
        return (f"precio por m² imposible (${ppm:,.2f}/m²); "
                f"al anuncio le faltan o le sobran ceros")
    return None


def _r_zona(a: dict) -> str | None:
    if a.get("zona_estado") == "fuera":
        return a.get("zona_motivo") or "fuera de las zonas del monitor"
    if a.get("zona_estado") == "sin_coords" or not a.get("zona"):
        return "sin ubicación asignable a una zona"
    return None


REGLAS: list[tuple[str, str, Callable[[dict], str | None]]] = [
    ("identificador", "Tiene un id estable para seguirlo entre corridas", _r_id),
    ("es_suelo",      "Es oferta de suelo, no una construcción",          _r_es_terreno),
    ("es_venta",      "Está en venta, no en renta",                       _r_es_venta),
    ("precio",        "Tiene precio y es plausible",                      _r_precio),
    ("superficie",    "La superficie es plausible",                       _r_superficie),
    ("precio_m2",     "El precio por m² es plausible",                    _r_precio_m2),
    ("zona",          "Está ubicado en alguna de las 5 zonas",            _r_zona),
]


def evaluar(anuncio: dict) -> tuple[bool, str | None, str | None]:
    """Regresa (pasa, regla_que_fallo, motivo)."""
    for nombre, _desc, fn in REGLAS:
        motivo = fn(anuncio)
        if motivo:
            return False, nombre, motivo
    return True, None, None


# ------------------------------------------------- ubicación compartida

# Cuando varios anuncios comparten la coordenada exacta, no es coincidencia:
# el portal puso su punto por omisión. En la primera corrida real, 5 propiedades
# con precios de $5,000 a $19 millones caían en (25.54284, -103.40679), que es
# el centro de Torreón. No se descartan —el terreno existe— pero se marcan como
# ubicación aproximada para no fingir una precisión que no hay.
MIN_PARA_SOSPECHAR = 3


def marcar_ubicaciones_compartidas(anuncios: list[dict]) -> list[dict]:
    conteo = collections.Counter(
        (round(a["lat"], 5), round(a["lon"], 5))
        for a in anuncios
        if a.get("lat") is not None and a.get("lon") is not None
    )
    for a in anuncios:
        lat, lon = a.get("lat"), a.get("lon")
        if lat is None or lon is None:
            a["ubicacion_precisa"] = False
            a["comparten_punto"] = 0
            continue
        n = conteo[(round(lat, 5), round(lon, 5))]
        a["comparten_punto"] = n
        a["ubicacion_precisa"] = n < MIN_PARA_SOSPECHAR
    return anuncios


# ---------------------------------------------------------------- fachada

def filtrar(anuncios: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """
    Regresa (aceptados, rechazados, reporte).

    Los rechazados llevan `_regla` y `_motivo`, para poder explicar cualquier
    ausencia sin volver a correr nada.
    """
    aceptados, rechazados = [], []
    por_regla: dict[str, int] = collections.OrderedDict((n, 0) for n, _, _ in REGLAS)

    for a in anuncios:
        pasa, regla, motivo = evaluar(a)
        if pasa:
            aceptados.append(a)
        else:
            b = dict(a)
            b["_regla"], b["_motivo"] = regla, motivo
            rechazados.append(b)
            por_regla[regla] += 1

    marcar_ubicaciones_compartidas(aceptados)
    aproximados = sum(1 for a in aceptados if not a.get("ubicacion_precisa"))

    return aceptados, rechazados, {
        "recibidos": len(anuncios),
        "aceptados": len(aceptados),
        "rechazados": len(rechazados),
        "por_regla": dict(por_regla),
        "ubicacion_aproximada": aproximados,
        "reglas": [{"nombre": n, "descripcion": d} for n, d, _ in REGLAS],
    }


def precio_m2_confiable(valor: Any) -> bool:
    """Si un precio por m² sirve para promediar. Lo usa la API."""
    return _en_rango(valor, PRECIO_M2_MIN, PRECIO_M2_MAX)
