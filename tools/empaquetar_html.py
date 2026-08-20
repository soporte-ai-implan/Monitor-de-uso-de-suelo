"""
Empaqueta el dashboard en UN SOLO archivo HTML autocontenido.

Para que se pueda mandar por correo, subir a cualquier hosting o abrir con
doble clic sin servidor ni carpeta de archivos sueltos. Es el formato en que
conviene enseñarlo antes de tocar producción.

Deja fuera solo Leaflet y Chart.js, que siguen viniendo por CDN: embeberlos
sumaría ~400 KB y de todos modos hace falta internet para los mosaicos del mapa.

Uso:  python tools/empaquetar_html.py
"""
from __future__ import annotations

import datetime
import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parent.parent
WEB = RAIZ / "web"
SALIDA = RAIZ / "Monitor de Suelo - IMPLAN Torreon.html"

# Orden de carga: los datos antes que la lógica que los consume.
LOCALES = ["zonas.js", "municipio.js", "puntos_demo.js", "datos.js", "geo.js", "tablero.js"]


def main() -> None:
    import base64

    html = (WEB / "index.html").read_text(encoding="utf-8")

    # El logo también se incrusta, si no el archivo suelto llega sin imagen.
    logo = WEB / "logo_implan.png"
    if logo.exists():
        b64 = base64.b64encode(logo.read_bytes()).decode()
        html = html.replace('src="logo_implan.png"', f'src="data:image/png;base64,{b64}"')
        print(f"  incrustado logo_implan.png ({logo.stat().st_size:,} bytes)")

    incrustados = 0
    faltantes = []
    for nombre in LOCALES:
        ruta = WEB / nombre
        # Acepta con y sin atributo onerror
        patron = re.compile(
            r'<script src="' + re.escape(nombre) + r'"[^>]*>\s*</script>'
        )
        if not patron.search(html):
            continue
        if not ruta.exists():
            html = patron.sub("", html)
            faltantes.append(nombre)
            continue
        js = ruta.read_text(encoding="utf-8")
        # Evita que un '</script>' dentro del JS corte el bloque.
        js = js.replace("</script>", "<\\/script>")
        html = patron.sub(
            lambda _m, j=js, n=nombre: f"<script>\n/* ---- {n} ---- */\n{j}\n</script>",
            html,
        )
        incrustados += 1
        print(f"  incrustado {nombre} ({ruta.stat().st_size:,} bytes)")

    if faltantes:
        print(f"  sin generar (se omiten): {', '.join(faltantes)}")

    sello = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    html = html.replace(
        "</head>",
        f"<!-- Archivo autocontenido generado el {sello} por tools/empaquetar_html.py.\n"
        f"     No editar a mano: los cambios se hacen en web/ y se vuelve a empaquetar. -->\n"
        "</head>",
    )

    SALIDA.write_text(html, encoding="utf-8")
    print(f"\n{SALIDA.name}")
    print(f"  {SALIDA.stat().st_size:,} bytes · {incrustados} archivos incrustados")
    print("  se abre con doble clic; solo necesita internet para el mapa base")


if __name__ == "__main__":
    main()
