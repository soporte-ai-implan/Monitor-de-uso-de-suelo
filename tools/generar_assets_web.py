"""
Convierte los archivos de data/ en assets JS para web/.

Por que JS y no JSON: el dashboard debe poder abrirse con doble clic
(protocolo file://), y ahi fetch() esta bloqueado por CORS mientras que
<script src="..."> si carga. Asi el mapa funciona sin servidor, y cuando
la API esta arriba simplemente sobreescribe los puntos.

Uso:  python tools/generar_assets_web.py
"""
import json
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
WEB = RAIZ / "web"


def escribir_js(destino: pathlib.Path, variable: str, datos, nota: str) -> None:
    payload = json.dumps(datos, ensure_ascii=False, separators=(",", ":"))
    destino.write_text(
        f"// GENERADO por tools/generar_assets_web.py - no editar a mano.\n"
        f"// {nota}\n"
        f"window.{variable} = {payload};\n",
        encoding="utf-8",
    )
    print(f"  {destino.relative_to(RAIZ)}  ({destino.stat().st_size:,} bytes)")


def generar_datos(anuncios: list[dict], ultima_actualizacion: str | None = None) -> pathlib.Path:
    """
    Escribe web/datos.js con los anuncios activos.

    Es lo que permite que el dashboard viva en hosting compartido sin API: si
    los datos cambian una vez al dia, no hace falta un servidor respondiendo
    peticiones. La corrida diaria regenera este archivo y el HTML lo lee como
    <script src>, que funciona hasta en el hosting mas limitado y sin CORS.
    """
    import compuertas

    WEB.mkdir(exist_ok=True)
    destino = WEB / "datos.js"
    payload = {
        "generado": ultima_actualizacion,
        "total": len(anuncios),
        # Los umbrales viajan con los datos para que el dashboard no tenga su
        # propia copia. Si el JS y el pipeline usan cortes distintos, la API y
        # la pantalla reportan medianas distintas y nadie se entera.
        "umbrales": {
            "precio_m2_min": compuertas.PRECIO_M2_MIN,
            "precio_m2_max": compuertas.PRECIO_M2_MAX,
        },
        "terrenos": anuncios,
    }
    destino.write_text(
        "// GENERADO en cada corrida del pipeline - no editar a mano.\n"
        "// Permite que el dashboard funcione sin API, en hosting estatico.\n"
        f"window.DATOS_MONITOR = {json.dumps(payload, ensure_ascii=False, default=str)};\n",
        encoding="utf-8",
    )
    return destino


def main() -> None:
    WEB.mkdir(exist_ok=True)
    print("Generando assets web...")

    zonas = json.loads((DATA / "torreon_zonas_final.geojson").read_text(encoding="utf-8"))
    escribir_js(
        WEB / "zonas.js",
        "TORREON_ZONAS",
        zonas,
        "5 zonas de Torreon (SEPOMEX, fusionadas). Se dibuja SOLO el contorno exterior.",
    )

    puntos = json.loads((DATA / "puntos_prueba_demo.json").read_text(encoding="utf-8"))
    escribir_js(
        WEB / "puntos_demo.js",
        "PUNTOS_DEMO",
        puntos,
        "Puntos de ejemplo (precio y m2 simulados). Placeholder hasta conectar la API.",
    )

    n_zonas = len(zonas.get("features", []))
    print(f"Listo: {n_zonas} zonas, {len(puntos)} puntos demo.")


if __name__ == "__main__":
    main()
