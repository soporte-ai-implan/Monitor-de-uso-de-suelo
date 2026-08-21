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


def generar_datos(
    anuncios: list[dict],
    ultima_actualizacion: str | None = None,
    fuentes: dict | None = None,
) -> pathlib.Path:
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
        # Estado por portal en la ultima corrida ('ok', 'vacia', 'error',
        # 'descartado'). El tablero lo usa para avisar cuando la oferta bajo
        # porque un portal se cayo, no porque el mercado se moviera.
        "fuentes": fuentes or {},
        "terrenos": anuncios,
    }
    destino.write_text(
        "// GENERADO en cada corrida del pipeline - no editar a mano.\n"
        "// Permite que el dashboard funcione sin API, en hosting estatico.\n"
        f"window.DATOS_MONITOR = {json.dumps(payload, ensure_ascii=False, default=str)};\n",
        encoding="utf-8",
    )
    return destino


def generar_estado(estado: dict) -> pathlib.Path:
    """
    Escribe web/estado.json: el parte medico de la ultima corrida.

    Existe para no depender de que alguien lea el log del servidor. Queda
    publicado junto al tablero, asi que se consulta desde el navegador
    (monitor.trcimplan.gob.mx/estado.json) sin acceso a cPanel ni a SSH.

    Se escribe SIEMPRE, tambien cuando la corrida falla: si solo se escribiera
    al terminar bien, una corrida rota se veria igual que un cron que nunca se
    disparo, que son problemas distintos.
    """
    WEB.mkdir(exist_ok=True)
    destino = WEB / "estado.json"
    destino.write_text(
        json.dumps(estado, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
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
        "5 zonas de Torreon. La geometria es de SEPOMEX; el agrupamiento hasta\n// quedar en 5 siguio los distritos del Plan Director de Desarrollo Urbano.\n// Se dibuja SOLO el contorno exterior.",
    )

    municipio = DATA / "torreon_municipio.geojson"
    if municipio.exists():
        escribir_js(
            WEB / "municipio.js",
            "TORREON_MUNICIPIO",
            json.loads(municipio.read_text(encoding="utf-8")),
            "Limite municipal (OSM rel. 5606549, ODbL). Es el guardian: dentro es Torreon.",
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
