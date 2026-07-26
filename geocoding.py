"""
geocoding.py — completa coordenadas y colonia, y asigna zona.

Orden de preferencia para las coordenadas (de mas confiable a menos):
  1. 'portal'          -> lat/lon que ya trae el anuncio
  2. 'nominatim'       -> geocoding de la direccion en texto (OpenStreetMap, gratis)
  3. 'centroide_zona'  -> punto DENTRO del poligono de la zona deducida del texto

El paso 3 nunca es aleatorio en todo el mapa, y es determinista por id de
anuncio para que el mismo predio no brinque de lugar entre corridas.

Reglas de cortesia de Nominatim (obligatorias, si no te bloquean):
  - maximo 1 peticion por segundo
  - User-Agent identificable con forma de contacto
  - cachear resultados; la misma direccion no se pregunta dos veces
"""
from __future__ import annotations

import json
import os
import pathlib
import time
from typing import Any

import requests
from dotenv import load_dotenv

import zonas

load_dotenv()

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
CONTACTO = os.getenv("NOMINATIM_CONTACTO", "soporte-ai@trcimplan.gob.mx")
USER_AGENT = f"MonitorSueloIMPLAN/1.0 ({CONTACTO})"
ESPERA_SEG = 1.1
TIMEOUT_SEG = 12

CACHE_PATH = pathlib.Path(__file__).resolve().parent / "data" / "cache_geocoding.json"

# Pistas de texto -> zona, para el fallback cuando no hay coordenadas.
# Se revisan en orden; la primera que aparezca en la direccion gana.
PISTAS_ZONA: list[tuple[str, str]] = [
    ("centro historico", "Zona 1 - Poniente y Centro Histórico"),
    ("poniente", "Zona 1 - Poniente y Centro Histórico"),
    ("zona norte", "Zona 2 - Zona Norte"),
    ("norte", "Zona 2 - Zona Norte"),
    ("centro", "Zona 3 - Centro-Norte"),
    ("oriente", "Zona 4 - Oriente"),
    ("sur oriente", "Zona 5 - Sur Oriente"),
    ("sur", "Zona 5 - Sur Oriente"),
]


class Geocodificador:
    def __init__(self, usar_cache: bool = True) -> None:
        self.usar_cache = usar_cache
        self.cache: dict[str, Any] = {}
        self._ultima_peticion = 0.0
        self.stats = {"portal": 0, "nominatim": 0, "centroide_zona": 0, "sin_ubicar": 0, "cache_hits": 0}
        if usar_cache and CACHE_PATH.exists():
            try:
                self.cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.cache = {}

    # ---------- Nominatim ----------

    def _respetar_limite(self) -> None:
        transcurrido = time.time() - self._ultima_peticion
        if transcurrido < ESPERA_SEG:
            time.sleep(ESPERA_SEG - transcurrido)
        self._ultima_peticion = time.time()

    def geocodificar(self, direccion: str) -> dict | None:
        """Regresa {'lat','lon','colonia'} o None."""
        if not direccion or not direccion.strip():
            return None

        clave = zonas.normalizar(direccion)
        if clave in self.cache:
            self.stats["cache_hits"] += 1
            return self.cache[clave]

        # Acotar la busqueda a Torreon, Coahuila: sin esto Nominatim regresa
        # calles con el mismo nombre en otras ciudades del pais.
        consulta = direccion if "torre" in clave else f"{direccion}, Torreón, Coahuila, México"

        self._respetar_limite()
        try:
            r = requests.get(
                NOMINATIM_URL,
                params={
                    "q": consulta,
                    "format": "jsonv2",
                    "limit": 1,
                    "addressdetails": 1,
                    "countrycodes": "mx",
                },
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT_SEG,
            )
            r.raise_for_status()
            datos = r.json()
        except (requests.RequestException, json.JSONDecodeError) as e:
            print(f"    Nominatim falló para {direccion!r}: {e}")
            return None

        if not datos:
            self.cache[clave] = None
            return None

        d = datos[0]
        dir_detalle = d.get("address") or {}
        res = {
            "lat": float(d["lat"]),
            "lon": float(d["lon"]),
            "colonia": (
                dir_detalle.get("neighbourhood")
                or dir_detalle.get("suburb")
                or dir_detalle.get("quarter")
                or dir_detalle.get("city_district")
            ),
            "ciudad_nominatim": dir_detalle.get("city") or dir_detalle.get("town") or dir_detalle.get("municipality"),
        }
        self.cache[clave] = res
        return res

    def guardar_cache(self) -> None:
        if not self.usar_cache:
            return
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(
            json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    # ---------- zona por texto ----------

    @staticmethod
    def zona_por_texto(*textos: Any) -> str | None:
        blob = zonas.normalizar(" ".join(str(t) for t in textos if t))
        if not blob:
            return None
        # Las pistas mas especificas primero (ver PISTAS_ZONA).
        for pista, zona in PISTAS_ZONA:
            if pista in blob:
                return zona
        return None

    # ---------- proceso principal ----------

    def enriquecer(self, anuncio: dict) -> dict:
        """
        Deja el anuncio con lat/lon, nombre_colonia, zona, zona_estado,
        zona_motivo y coords_origen. Nunca lanza excepcion.
        """
        a = dict(anuncio)
        lat, lon = a.get("lat"), a.get("lon")
        origen = "portal" if (lat is not None and lon is not None) else None

        # 2) Nominatim si el portal no dio coordenadas
        if origen is None and a.get("ubicacion"):
            g = self.geocodificar(a["ubicacion"])
            if g:
                lat, lon, origen = g["lat"], g["lon"], "nominatim"
                if not a.get("nombre_colonia") and g.get("colonia"):
                    a["nombre_colonia"] = g["colonia"]
                # Nominatim tambien sirve de segunda opinion sobre el municipio.
                if not a.get("ciudad") and g.get("ciudad_nominatim"):
                    a["ciudad"] = g["ciudad_nominatim"]

        # Clasificar lo que haya
        if lat is not None and lon is not None:
            c = zonas.clasificar(lon, lat, a.get("ciudad"))
        else:
            c = {"zona": None, "estado": "sin_coords", "motivo": "sin coordenadas ni dirección geocodificable", "distancia_km": None}

        # 3) Fallback: punto dentro del poligono de la zona deducida del texto.
        #    Solo aplica si el anuncio SI es de Torreon; si es de otro municipio
        #    no se le invienta una ubicacion, se descarta.
        if c["estado"] == "sin_coords" and zonas.municipio_valido(a.get("ciudad")) is not False:
            zona_txt = self.zona_por_texto(a.get("ubicacion"), a.get("nombre_colonia"), a.get("titulo"))
            if zona_txt:
                par = zonas.punto_aleatorio_en_zona(zona_txt, semilla=a.get("id_anuncio"))
                if par:
                    lat, lon = par
                    origen = "centroide_zona"
                    c = {
                        "zona": zona_txt,
                        "estado": "borde",
                        "motivo": f"sin coordenadas; ubicado dentro del polígono de {zona_txt} por texto",
                        "distancia_km": 0.0,
                    }

        a["lat"], a["lon"] = lat, lon
        a["coords_origen"] = origen
        a["zona"] = c["zona"]
        a["zona_estado"] = c["estado"]
        a["zona_motivo"] = c["motivo"]

        if origen:
            self.stats[origen] += 1
        else:
            self.stats["sin_ubicar"] += 1
        return a

    def enriquecer_lista(self, anuncios: list[dict]) -> list[dict]:
        total = len(anuncios)
        salida = []
        for i, a in enumerate(anuncios, 1):
            if i % 25 == 0 or i == total:
                print(f"    geocoding {i}/{total}")
            salida.append(self.enriquecer(a))
        self.guardar_cache()
        return salida


def enriquecer_anuncios(anuncios: list[dict]) -> tuple[list[dict], dict]:
    """Fachada para main.py. Regresa (anuncios, stats)."""
    g = Geocodificador()
    resultado = g.enriquecer_lista(anuncios)
    return resultado, g.stats


if __name__ == "__main__":
    prueba = [
        {"id_anuncio": "demo-1", "titulo": "Terreno", "ubicacion": "Blvd. Independencia 1500, Torreón", "ciudad": "Torreón", "lat": None, "lon": None},
        {"id_anuncio": "demo-2", "titulo": "Terreno zona norte", "ubicacion": "Colonia sin nombre, zona norte", "ciudad": "Torreón", "lat": None, "lon": None},
        {"id_anuncio": "demo-3", "titulo": "Terreno GP", "ubicacion": "Centro, Gómez Palacio", "ciudad": "Gómez Palacio", "lat": 25.5611, "lon": -103.4956},
    ]
    res, stats = enriquecer_anuncios(prueba)
    for a in res:
        print(f"  {a['id_anuncio']}: zona={a['zona']} estado={a['zona_estado']} origen={a['coords_origen']}")
        print(f"     motivo: {a['zona_motivo']}")
    print(f"  stats: {stats}")
