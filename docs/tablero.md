# El tablero: cómo está armado y por qué

El frontend completo. Para el mapa hay un documento aparte, `mapa.md`, porque
la geometría de las zonas da para largo.

---

## La decisión de fondo: no hay API

Es lo primero que hay que entender, porque explica casi todo lo demás.

Los datos cambian **una vez cada 3 días**. Un tablero que consulta un servidor
en cada visita tendría sentido si la información cambiara mientras alguien lo
mira; aquí no cambia. Así que el pipeline escribe un archivo y el navegador lo
lee como cualquier otro script:

```html
<script src="datos.js"></script>
```

Y `datos.js` es literalmente esto:

```js
window.DATOS_MONITOR = {"generado": "...", "total": 111, "terrenos": [...]};
```

Lo que se gana: sin proceso encendido, sin puerto, sin CORS, sin base de datos
que responda en vivo, sin nada que reiniciar cuando el hosting se reinicia. El
tablero es HTML estático y **no puede caerse** mientras Apache siga sirviendo
archivos. Si el pipeline falla, la página sigue mostrando la corrida anterior en
vez de una pantalla en blanco.

Lo que se pierde: no hay consultas arbitrarias ni filtros del lado del servidor.
Todo el filtrado ocurre en el navegador, sobre los ~111 registros que ya se
descargaron. A esta escala eso es gratis. Con 100 mil registros sería otra
conversación.

---

## Los archivos

```
web/
  index.html      estructura, estilos y textos. Todo el CSS va aquí adentro.
  tablero.js      la lógica: dibuja mapa, gráficas, tabla y filtros.  (64 KB)
  geo.js          clasifica un punto en su zona. Espeja a zonas.py.   (14 KB)

  ── generados por el pipeline, NO se editan a mano ──
  datos.js        los anuncios de la última corrida.
  estado.json     el parte médico de la corrida.
  zonas.js        polígonos de las 5 zonas.
  municipio.js    límite municipal de Torreón.
  puntos_demo.js  puntos de ejemplo, por si nunca ha corrido el pipeline.
```

Los cinco de abajo salen de `tools/generar_assets_web.py`. Si editas uno a mano,
la siguiente corrida te lo borra. Cada uno lleva un encabezado que lo dice.

Orden de carga en `index.html`, y es a propósito: **primero los datos, luego la
lógica que los consume.**

```html
<script src="zonas.js"></script>       <!-- geometría -->
<script src="municipio.js"></script>
<script src="puntos_demo.js"></script>
<script src="datos.js" onerror="..."></script>   <!-- los anuncios -->
<script src="geo.js"></script>         <!-- clasificador -->
<script src="tablero.js"></script>     <!-- dibuja todo -->
```

Ese `onerror` en `datos.js` no es adorno: en una instalación recién clonada ese
archivo **no existe** todavía, porque está en `.gitignore`. Sin el `onerror`, la
consola tiraría un error rojo y parecería que algo se rompió. Con él, deja un
aviso informativo y el tablero cae a los puntos de ejemplo.

---

## Las secciones, en orden

| Sección | Qué contesta |
|---|---|
| **4 indicadores** arriba | ofertas activas, precio medio por m², superficie mediana, días en el mercado |
| **Distribución por zona** (mapa) | dónde está la oferta. Ver `mapa.md` |
| **Inteligencia de mercado** | precio por m² segmentado por tamaño de predio, con índice base 100 |
| **Cómo se reparte la oferta** | 5 gráficas: por zona, por tamaño, antigüedad, portal, tendencia |
| **Ofertas registradas** | la tabla completa, ordenable y filtrable, cada renglón liga al anuncio |
| **Pipeline con HITL** | la metodología, para que se pueda auditar de dónde sale cada número |
| **Quién construye esto** | créditos |

---

## Decisiones que no se ven pero sostienen todo

### Mediana, no promedio

En los indicadores y en cada gráfica de precio se usa **mediana**. Un terreno
mal capturado con un precio de $4,300,000,000 —que los hay, salen del portal—
mueve el promedio hasta volverlo basura. La mediana ni se entera.

### Cada bloque se dibuja por separado

```js
function intentar(nombre, fn) {
  try { fn(); } catch (e) { console.error(...); avisar(nombre); }
}
```

Si truena la gráfica de antigüedad, las demás siguen. Sin esto, un dato raro en
una sección deja la página entera en blanco. Y cuando algo falla aparece un
aviso que dice **"los datos son correctos; falló la presentación"**, porque son
problemas distintos y el que lee necesita saber cuál de los dos le tocó.

### El sello de frescura

Arriba a la derecha, junto a la fecha, hay una etiqueta que dice "hoy", "ayer" o
"hace N días". A partir de 2 días agrega **"· sin actualizar"** y se pinta de
naranja.

Existe porque un tablero desactualizado es peligroso de una forma particular: se
ve exactamente igual que uno al día. Alguien podría tomar decisiones con datos
de hace tres semanas sin enterarse. La etiqueta lo delata sola.

### El estado de las fuentes viaja con los datos

`datos.js` no trae solo los anuncios: trae cómo respondió cada portal.

```js
"fuentes": {"inmuebles24": {"estatus":"ok","crudos":120},
            "pincali": {"estatus":"ok","crudos":5}}
```

Si un portal se cae, el tablero lo dice en pantalla. Sin esto, una caída de
oferta por falla técnica se leería como caída de mercado, que es justo la
conclusión equivocada que un instituto de planeación no se puede permitir
publicar.

Por lo mismo el texto de los portales se arma leyendo los datos y no está
escrito a mano: antes decía "vía Inmuebles24 y Pincali" incluso cuando Pincali
no había traído un solo anuncio.

### Color y accesibilidad

El color **no identifica la zona**, y no es descuido. Con el criterio de
contraste entre todos los pares, ni una paleta profesional de 8 colores sostiene
más de tres categorías distinguibles bajo daltonismo. Aquí la identidad la carga
el **nombre** —etiqueta en el mapa, leyenda y tooltip—; el color solo refuerza.

Los créditos van en verde, blanco y rojo. La barra blanca sobre tarjeta blanca
sería invisible, así que lleva un filo de 1px para que se lea como blanco
deliberado y no como una barra que falta.

### El mapa base

Sale de OpenStreetMap. Antes era CARTO Positron, que se veía mejor porque su
gris compite menos con los colores de las zonas, pero **CARTO empezó a exigir
llave y le estampa "API KEY REQUIRED" encima a cada mosaico**.

Ese caso enseñó algo que vale la pena recordar: la marca viene **pintada dentro
del PNG**, que llega con código 200 y tamaño normal. Revisando respuestas HTTP
todo se ve sano. Solo se detecta mirando el mapa.

Para volver a CARTO, hay llave gratis en `carto.com/basemaps/apikey` y se
declara antes de cargar `tablero.js`:

```html
<script>window.MONITOR_CARTO_KEY = 'la-llave';</script>
```

---

## El HTML de un solo archivo

`tools/empaquetar_html.py` mete todo —CSS, JS, datos y el logo en base64— en
`Monitor de Suelo - IMPLAN Torreon.html`. Se abre con doble clic, se manda por
correo y no necesita servidor. Solo quedan fuera Leaflet y Chart.js, que siguen
viniendo por CDN: embeberlos sumaría ~400 KB y de todos modos hace falta
internet para los mosaicos del mapa.

**Se rearma en cada corrida**, junto con `datos.js`. Antes se empaquetaba a
mano, y el archivo que se mandaba por correo decía "actualizado el 1 de agosto"
con el pipeline corriendo al día.

---

## Si le vas a mover

1. **Edita `web/`, nunca el HTML de un solo archivo.** Ese es generado; la
   siguiente corrida lo sobreescribe.
2. **`geo.js` y `zonas.py` tienen que decir lo mismo.** El primero clasifica en
   el navegador, el segundo en el pipeline. Si se separan, el mapa y la base
   cuentan distinto. `tests/test_zonas.py` compara los dos y truena si difieren
   — córrelo después de tocar cualquiera.
3. **El CSS vive dentro de `index.html`**, en un `<style>`. No hay archivo
   `.css` aparte, a propósito: son ~300 líneas y así el empaquetado a un solo
   archivo no tiene que resolver rutas.
4. Después de cualquier cambio, ábrelo y **mira la consola**. El único error
   esperado es el 404 de `/api/monitor-terrenos`, que es un resto de cuando
   había API en Railway y cae con gracia.
