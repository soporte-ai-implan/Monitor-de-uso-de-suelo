"""
scraper.py — trae los anuncios de los 2 Actores de Apify ya validados.

Cada portal regresa un schema distinto; aqui se normalizan a un solo diccionario
para que el resto del pipeline no sepa de que portal vino cada anuncio.

Los nombres de campo NO son inventados: se leyeron del output schema real de
cada Actor (ver docs/scraper.md). El prompt original asumia
`location.full_address` para Inmuebles24, pero ese campo no existe: el schema
real trae `address`, `neighborhood`, `city` planos.
"""
from __future__ import annotations

import os
from typing import Any

from apify_client import ApifyClient
from dotenv import load_dotenv

load_dotenv()

# --- Actores validados. No cambiar sin volver a probar. ---
ACTOR_INMUEBLES24 = "benthepythondev/inmuebles24-scraper"
ACTOR_PINCALI = "azzouzana/pincali-com-scraper-by-search-url"

URL_INMUEBLES24 = "https://www.inmuebles24.com/terrenos-en-venta-en-torreon.html"
URL_PINCALI = "https://www.pincali.com/inmuebles/terrenos-en-venta-en-torreon-coahuila"

# Vivanuncios queda fuera a proposito: los 2 actores disponibles fallaron en
# pruebas reales (uno crashea en ~1s, el otro muere a los 66s por Cloudflare).
# Ver docs/scraper.md. El dashboard lo declara tachado, no lo esconde.

MAX_POR_FUENTE = int(os.getenv("MAX_RESULTADOS_POR_FUENTE", "200"))


def _cliente() -> ApifyClient:
    token = os.getenv("APIFY_TOKEN")
    if not token:
        raise RuntimeError(
            "Falta APIFY_TOKEN. Copia .env.example a .env y pon el token de Apify."
        )
    return ApifyClient(token)


def _correr_actor(client: ApifyClient, actor_id: str, run_input: dict) -> list[dict]:
    run = client.actor(actor_id).call(run_input=run_input)
    if run is None:
        raise RuntimeError(f"El Actor {actor_id} no regresó información de corrida.")
    if run.get("status") != "SUCCEEDED":
        raise RuntimeError(f"El Actor {actor_id} terminó en estado {run.get('status')}.")
    return client.dataset(run["defaultDatasetId"]).list_items().items


def _num(v: Any) -> float | None:
    """Convierte a float sin tronarse con None, '' o texto."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fecha(v: Any) -> str | None:
    """Se queda con la parte YYYY-MM-DD de un ISO timestamp."""
    if not v:
        return None
    return str(v)[:10]


# ---------- normalizadores por portal ----------

def normalizar_inmuebles24(a: dict) -> dict:
    """
    Campos del schema real: id, title, generated_title, price, currency,
    land_area_m2, covered_area_m2, address, neighborhood, city, province,
    latitude, longitude, url, property_type, operation, modified_at.
    """
    m2 = _num(a.get("land_area_m2")) or _num(a.get("total_area_m2")) or _num(a.get("covered_area_m2"))
    partes = [a.get("address"), a.get("neighborhood"), a.get("city")]
    return {
        "id_anuncio": f"i24-{a.get('id')}",
        "fuente": "inmuebles24",
        "titulo": a.get("title") or a.get("generated_title") or "Terreno en venta",
        "precio": _num(a.get("price")),
        "m2": m2,
        "ubicacion": ", ".join(p for p in partes if p) or None,
        "ciudad": a.get("city"),
        "estado": a.get("province"),
        "nombre_colonia": a.get("neighborhood"),
        "lat": _num(a.get("latitude")),
        "lon": _num(a.get("longitude")),
        "tipo_propiedad": a.get("property_type"),
        "operacion": a.get("operation"),
        "url": a.get("url"),
        "fecha_publicacion": _fecha(a.get("modified_at")),
    }


def normalizar_pincali(a: dict) -> dict:
    """
    Campos del schema real: listingId, propertyId, price, currency, areaM2,
    fullAddress, locationText, neighborhood, city, state, latitude, longitude,
    url, canonicalUrl, propertyType, operationType, publishedAt.

    Ojo: `title` en Pincali viene siempre null, por eso se arma el titulo.
    """
    ident = a.get("listingId") or a.get("propertyId")
    tipo = a.get("propertyType") or "Terreno"
    donde = a.get("locationText") or a.get("neighborhood") or a.get("city") or "Torreón"
    return {
        "id_anuncio": f"pin-{ident}",
        "fuente": "pincali",
        "titulo": a.get("title") or f"{tipo} en {donde}",
        "precio": _num(a.get("price")),
        "m2": _num(a.get("areaM2")),
        "ubicacion": a.get("fullAddress") or a.get("locationText"),
        "ciudad": a.get("city"),
        "estado": a.get("state"),
        "nombre_colonia": a.get("neighborhood"),
        "lat": _num(a.get("latitude")),
        "lon": _num(a.get("longitude")),
        "tipo_propiedad": tipo,
        "operacion": a.get("operationType"),
        "url": a.get("url") or a.get("canonicalUrl"),
        "fecha_publicacion": _fecha(a.get("publishedAt")),
    }


# ---------- fachada ----------

def obtener_anuncios_torreon(max_por_fuente: int | None = None) -> tuple[list[dict], dict]:
    """
    Corre las 2 fuentes y regresa (anuncios_normalizados, detalle_por_fuente).

    Si una fuente falla, la otra sigue: el monitor prefiere datos parciales
    con la falla anotada, a no publicar nada. `detalle` es lo que se guarda
    en la tabla `corridas` para poder auditar despues.
    """
    tope = max_por_fuente or MAX_POR_FUENTE
    client = _cliente()
    anuncios: list[dict] = []
    detalle: dict[str, dict] = {}

    fuentes = [
        (
            "inmuebles24",
            ACTOR_INMUEBLES24,
            # La URL va YA ARMADA a proposito. El otro actor
            # (fatihtahta/inmuebles24-scraper) arma la busqueda con parametros
            # sueltos y tiene un bug confirmado: location+property_type juntos
            # regresan 0 resultados para Torreon.
            {"maxResultsPerSearch": tope, "searchUrls": [{"url": URL_INMUEBLES24}]},
            normalizar_inmuebles24,
        ),
        (
            "pincali",
            ACTOR_PINCALI,
            {"maxItems": tope, "startUrl": URL_PINCALI},
            normalizar_pincali,
        ),
    ]

    for nombre, actor_id, run_input, normalizar in fuentes:
        try:
            crudos = _correr_actor(client, actor_id, run_input)
            normalizados = [normalizar(a) for a in crudos]
            # Sin id no hay forma de detectar altas/bajas: se descarta.
            validos = [a for a in normalizados if a["id_anuncio"] and "None" not in a["id_anuncio"]]
            anuncios.extend(validos)
            detalle[nombre] = {
                "estatus": "ok",
                "crudos": len(crudos),
                "normalizados": len(validos),
                "sin_id": len(normalizados) - len(validos),
            }
            print(f"  [{nombre}] {len(validos)} anuncios ({len(crudos)} crudos)")
        except Exception as e:  # noqa: BLE001 - una fuente caida no debe tumbar la corrida
            detalle[nombre] = {"estatus": "error", "error": str(e), "crudos": 0, "normalizados": 0}
            print(f"  [{nombre}] ERROR: {e}")

    detalle["vivanuncios"] = {
        "estatus": "descartado",
        "razon": "los 2 actores disponibles fallaron en pruebas reales (crash / bloqueo Cloudflare)",
    }
    return anuncios, detalle


if __name__ == "__main__":
    lista, det = obtener_anuncios_torreon()
    print(f"\nTotal normalizado: {len(lista)}")
    for k, v in det.items():
        print(f"  {k}: {v}")
