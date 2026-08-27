/*
 * tablero.js — arma el Monitor de Suelo: mapa, indicadores, gráficas y tabla.
 *
 * Regla de color del tablero: el color NUNCA identifica una categoría por sí
 * solo. Con el criterio de mapa (todos los pares), ni una paleta profesional de
 * ocho colores sostiene más de tres categorías distinguibles bajo daltonismo.
 * Por eso las zonas se identifican por NOMBRE (etiqueta en el mapa, leyenda,
 * tooltip) y todas las gráficas son de serie única con un solo color: el eje
 * ya etiqueta cada barra.
 */
(function () {
  'use strict';

  // De dónde se refresca. Importa para el archivo suelto que se manda por
  // correo: un HTML estático se queda congelado en la fecha en que se empaquetó,
  // así que después de pintar los datos incrustados se consulta la API y, si
  // trae una corrida más nueva, se vuelve a pintar.
  //
  // Servido desde un hosting (cPanel), el valor por omisión es el MISMO origen:
  // si ahí vive la API, refresca; si es hosting estático con cron, el fetch
  // falla, se ignora y manda el datos.js que el cron acaba de escribir. Lo que
  // no puede pasar es que el tablero de trcimplan.gob.mx siga jalando datos de
  // un Railway apagado o desactualizado. Para apuntar a otro servidor:
  // window.MONITOR_API_URL = 'https://...' antes de cargar este archivo.
  var API = window.MONITOR_API_URL ||
            (window.DATOS_MONITOR && window.DATOS_MONITOR.api) ||
            (location.protocol === 'http:' || location.protocol === 'https:' ? location.origin : '');

  var AZUL = '#1B5286', NARANJA = '#E95026', TINTA = '#1B1714',
      GRIS = '#5C554D', MUTED = '#6F675E', REJILLA = '#EFEAE3';

  var mxn = function (v) { return '$' + Number(v).toLocaleString('es-MX', { maximumFractionDigits: 0 }); };
  var num = function (v) { return Number(v).toLocaleString('es-MX', { maximumFractionDigits: 0 }); };

  var UMBR = (window.DATOS_MONITOR && window.DATOS_MONITOR.umbrales) || {};
  var PPM_MIN = UMBR.precio_m2_min != null ? UMBR.precio_m2_min : 10;
  var PPM_MAX = UMBR.precio_m2_max != null ? UMBR.precio_m2_max : 50000;
  function ppmOk(v) { return v >= PPM_MIN && v <= PPM_MAX; }

  var SEGMENTOS = [
    { nombre: 'Predio menor de 300 m²', corto: '< 300 m²', rango: 'menos de 300 m²', lo: 0, hi: 300 },
    { nombre: 'Predio de 300 a 600 m²', corto: '300 a 600 m²', rango: '300 a 600 m²', lo: 300, hi: 600 },
    { nombre: 'Predio de 600 a 1,500 m²', corto: '600 a 1,500 m²', rango: '600 a 1,500 m²', lo: 600, hi: 1500 },
    { nombre: 'Predio de 1,500 a 10,000 m²', corto: '1,500 a 10,000 m²', rango: '1,500 a 10,000 m²', lo: 1500, hi: 10000 },
    { nombre: 'Predio mayor a 10,000 m²', corto: '> 10,000 m²', rango: 'más de 10,000 m²', lo: 10000, hi: Infinity }
  ];

  function mediana(v) {
    if (!v.length) return null;
    var s = v.slice().sort(function (a, b) { return a - b; }), n = s.length;
    return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
  }
  function ppm(p) {
    if (p.precio_m2) return Number(p.precio_m2);
    if (p.precio && p.m2 > 0) return Number(p.precio) / Number(p.m2);
    return 0;
  }
  function diasEnMercado(p) {
    if (!p.fecha_publicacion) return null;
    var d = new Date(p.fecha_publicacion);
    if (isNaN(d)) return null;
    return Math.max(0, Math.round((Date.now() - d.getTime()) / 86400000));
  }
  function fechaLegible(v) {
    var d = v ? new Date(v) : new Date();
    if (isNaN(d.getTime())) return String(v);
    return d.toLocaleDateString('es-MX', { day: '2-digit', month: 'long', year: 'numeric' }) +
           ', ' + d.toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit' });
  }
  // La fecha sale del dato, no del reloj: es cuando corrio el pipeline. Pero
  // una fecha sola no distingue "de hoy" de "de hace tres semanas", y un dato
  // viejo mostrado sin aviso se lee como vigente. Aqui se dice la antiguedad.
  function sellarFecha(fecha) {
    var el = document.getElementById('sello-fecha');
    if (!el) return;
    el.textContent = fechaLegible(fecha);

    var chip = el.closest ? el.closest('.chip-fecha') : null;
    var vieja = document.getElementById('sello-edad');
    if (vieja && vieja.parentNode) vieja.parentNode.removeChild(vieja);
    if (chip) chip.classList.remove('rancio');

    var d = fecha ? new Date(fecha) : null;
    if (!d || isNaN(d.getTime())) return;
    var dias = Math.floor((Date.now() - d.getTime()) / 86400000);
    if (dias < 0) dias = 0;

    var txt = dias === 0 ? 'hoy' : dias === 1 ? 'ayer' : 'hace ' + dias + ' días';
    var s = document.createElement('span');
    s.id = 'sello-edad';
    s.className = 'edad' + (dias >= 2 ? ' rancia' : '');
    s.textContent = dias >= 2 ? txt + ' · sin actualizar' : txt;
    el.parentNode.appendChild(s);
    if (chip && dias >= 2) chip.classList.add('rancio');
  }

  function segDe(p) {
    var m = Number(p.m2);
    for (var i = 0; i < SEGMENTOS.length; i++) {
      if (m >= SEGMENTOS[i].lo && m < SEGMENTOS[i].hi) return SEGMENTOS[i].nombre;
    }
    return null;
  }
  function corta(z) { return String(z || '').replace(/^Zona \d+ - /, ''); }

  // Los avisos se cuelgan bajo los KPIs: son advertencias sobre esas cifras,
  // así que tienen que leerse antes de creerles. Antes se anclaban al bloque
  // .aviso de la cabecera, que ahora vive dentro del pipeline.
  function colgarAviso(c) {
    var ref = document.querySelector('main .kpis');
    if (ref && ref.parentNode) { ref.parentNode.insertBefore(c, ref.nextSibling); return; }
    var m = document.querySelector('main');
    if (m) m.insertBefore(c, m.firstChild);
  }

  // Cada bloque se dibuja por separado: si uno truena, los demás siguen.
  function intentar(nombre, fn) {
    try { fn(); } catch (e) { console.error('Falló "' + nombre + '":', e); avisar(nombre); }
  }
  function avisar(nombre) {
    var c = document.getElementById('aviso-falla');
    if (!c) {
      c = document.createElement('div');
      c.id = 'aviso-falla';
      c.className = 'aviso';
      c.style.cssText = 'background:#FDECEC;border-color:#F0C4C4;border-left-color:#C0392B;color:#7B2D26';
      c.innerHTML = '<b>Algunas secciones no se pudieron dibujar.</b> Los datos son correctos; ' +
                    'falló la presentación. Secciones: <span></span>';
      colgarAviso(c);
    }
    var s = c.querySelector('span');
    var v = s.textContent ? s.textContent.split(', ') : [];
    if (v.indexOf(nombre) === -1) v.push(nombre);
    s.textContent = v.join(', ');
  }

  var NOMBRE_PORTAL = { inmuebles24: 'Inmuebles24', pincali: 'Pincali', vivanuncios: 'Vivanuncios' };
  function nombrePortal(k) { return NOMBRE_PORTAL[k] || k; }

  // El letrero de "cobertura incompleta" se retiro a peticion. La caida de un
  // portal sigue siendo visible en la dona de "Oferta por portal": aparece en
  // la leyenda con cero anuncios en vez de desaparecer de la grafica.

  /* ================= mapa ================= */
  var mapa = L.map('mapa', { scrollWheelZoom: false, zoomControl: true });
  // Fondo del mapa. CARTO empezo a exigir llave y le estampa "API KEY REQUIRED"
  // encima a cada tile — el PNG llega completo, con la marca pintada adentro, asi
  // que no se detecta mirando codigos HTTP: hay que verlo. Por eso el default es
  // OpenStreetMap, que no pide llave y nunca deja de servir.
  //
  // El gris claro de CARTO (Positron) le queda mejor al tablero, porque compite
  // menos con los colores de las zonas. Para recuperarlo basta sacar una llave
  // gratis en carto.com/basemaps/apikey y declararla antes de este archivo:
  //
  //     <script>window.MONITOR_CARTO_KEY = 'la-llave';</script>
  var LLAVE_CARTO = window.MONITOR_CARTO_KEY || '';
  var fondo = LLAVE_CARTO
    ? { url: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png?api_key=' + LLAVE_CARTO,
        cred: '&copy; OpenStreetMap &copy; CARTO' }
    : { url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
        cred: '&copy; OpenStreetMap' };
  L.tileLayer(fondo.url, { maxZoom: 19, attribution: fondo.cred }).addTo(mapa);

  var capaZonas = L.layerGroup().addTo(mapa),
      capaEtq = L.layerGroup().addTo(mapa),
      capaCalor = L.layerGroup().addTo(mapa),
      capaPuntos = L.layerGroup().addTo(mapa);

  var conteoZona = {};

  function centroide(feature) {
    var lats = [], lons = [];
    L.geoJSON(feature).eachLayer(function (l) {
      var b = l.getBounds();
      lats.push(b.getCenter().lat); lons.push(b.getCenter().lng);
    });
    if (!lats.length) return null;
    return [lats.reduce(function (a, b) { return a + b; }) / lats.length,
            lons.reduce(function (a, b) { return a + b; }) / lons.length];
  }

  /* ---------- simplificacion SOLO para dibujo ----------
     Los poligonos de zona traen entre 178 y 289 vertices con escaloncitos de
     codigo postal que a escala de ciudad son ruido. Se adelgazan para pintar.
     OJO: el poligono de precision completa se queda intacto para clasificar
     (GeoZonas.clasificar). Aqui no se decide en que zona cae nada; solo se
     dibuja. Simplificar lo que clasifica moveria terrenos de zona. */
  function distPuntoRecta(p, a, b) {
    var dx = b[0] - a[0], dy = b[1] - a[1];
    if (dx === 0 && dy === 0) return Math.hypot(p[0] - a[0], p[1] - a[1]);
    var t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy);
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
  }
  function douglasPeucker(pts, tol) {
    if (pts.length < 3) return pts;
    var dmax = 0, idx = 0;
    for (var i = 1; i < pts.length - 1; i++) {
      var d = distPuntoRecta(pts[i], pts[0], pts[pts.length - 1]);
      if (d > dmax) { dmax = d; idx = i; }
    }
    if (dmax > tol) {
      var a = douglasPeucker(pts.slice(0, idx + 1), tol);
      return a.slice(0, -1).concat(douglasPeucker(pts.slice(idx), tol));
    }
    return [pts[0], pts[pts.length - 1]];
  }
  var TOL_DIBUJO = 0.00035;   // ~35 m: quita el escaloncito, respeta la forma
  function aligerar(geom) {
    function anillo(r) {
      var s = douglasPeucker(r, TOL_DIBUJO);
      return s.length >= 4 ? s : r;   // nunca degenerar un anillo
    }
    if (geom.type === 'Polygon') {
      return { type: 'Polygon', coordinates: geom.coordinates.map(anillo) };
    }
    if (geom.type === 'MultiPolygon') {
      return { type: 'MultiPolygon',
               coordinates: geom.coordinates.map(function (p) { return p.map(anillo); }) };
    }
    return geom;
  }

  // Atenua todo lo que queda FUERA del municipio: dice "esto es Torreon" sin
  // tener que gritar una linea gruesa. Es un poligono del mundo con un hueco
  // en forma de Torreon (el hueco va con el sentido de giro invertido).
  function mascaraMunicipio() {
    var f = (window.TORREON_MUNICIPIO.features || [])[0];
    if (!f) return null;
    var g = f.geometry;
    var anillos = g.type === 'Polygon' ? [g.coordinates[0]]
                                       : g.coordinates.map(function (p) { return p[0]; });
    var mundo = [[-90, -200], [-90, 200], [90, 200], [90, -200]];
    var huecos = anillos.map(function (r) {
      return r.map(function (c) { return [c[1], c[0]]; }).reverse();
    });
    return L.polygon([mundo].concat(huecos), {
      stroke: false, fill: true, fillColor: '#8A8178', fillOpacity: .13,
      interactive: false
    });
  }

  function dibujarZonas() {
    capaZonas.clearLayers(); capaEtq.clearLayers();

    if (window.TORREON_MUNICIPIO) {
      var m = mascaraMunicipio();
      if (m) m.addTo(capaZonas);
      L.geoJSON({ type: 'FeatureCollection', features: (window.TORREON_MUNICIPIO.features || []).map(function (f) {
        return { type: 'Feature', properties: {}, geometry: aligerar(f.geometry) };
      }) }, {
        style: { color: MUTED, weight: 1.1, opacity: .5, dashArray: '6,5', fill: false },
        interactive: false
      }).addTo(capaZonas);
    }

    (window.TORREON_ZONAS.features || []).forEach(function (f) {
      var n = GeoZonas.nombreDe(f), col = GeoZonas.COLOR_ZONA[n] || MUTED;
      var ligera = { type: 'Feature', properties: f.properties, geometry: aligerar(f.geometry) };
      // Relleno tenue = la pertenencia se lee de un golpe, sin trazar la
      // frontera con la vista. Antes iban 2.6px al 90% y sin relleno: la
      // referencia le ganaba al dato.
      L.geoJSON(ligera, { style: { color: col, weight: 4, opacity: .08, fillColor: col,
                                   fillOpacity: .07, lineJoin: 'round' }, interactive: false }).addTo(capaZonas);
      L.geoJSON(ligera, { style: { color: col, weight: 1.25, opacity: .5, fill: false,
                                   lineJoin: 'round', lineCap: 'round' }, interactive: false }).addTo(capaZonas);
      var c = centroide(f);
      if (c) {
        L.marker(c, {
          interactive: false,
          icon: L.divIcon({ className: '', html: '<span class="etq-zona" style="color:' + col + '">' + corta(n) + '</span>',
                            iconSize: [0, 0] })
        }).addTo(capaEtq);
      }
    });
    mapa.fitBounds(GeoZonas.boundsDe(window.TORREON_ZONAS), { padding: [26, 26] });
  }

  // Leaflet.heat truena si el contenedor aún mide 0 px. ResizeObserver dispara
  // aunque la pestaña esté en segundo plano, donde requestAnimationFrame se congela.
  function cuandoMida(fn) {
    var caja = mapa.getContainer(), listo = false;
    function go() { if (!listo && caja.clientWidth && caja.clientHeight) { listo = true; fn(); } }
    if (caja.clientWidth && caja.clientHeight) return fn();
    var obs = window.ResizeObserver ? new ResizeObserver(function () { go(); if (listo) obs.disconnect(); }) : null;
    if (obs) obs.observe(caja);
    var n = 0, t = setInterval(function () {
      go();
      if (listo || ++n > 40) { clearInterval(t); if (obs) obs.disconnect(); }
    }, 150);
  }

  function dibujarCalor(pts) {
    capaCalor.clearLayers();
    if (!pts.length) return;
    cuandoMida(function () {
      mapa.invalidateSize(false);
      // Referencia = percentil 90, no el máximo: un solo anuncio carísimo
      // aplastaría a todos los demás contra el piso de la escala.
      var v = pts.map(ppm).filter(function (x) { return x > 0 && ppmOk(x); }).sort(function (a, b) { return a - b; });
      var tope = v.length ? (v[Math.floor(v.length * .9)] || v[v.length - 1]) : 1;
      // Panel propio y atenuado: a plena opacidad las manchas tapaban los
      // tintes de zona y los puntos, que es lo que se venia viendo "opaco".
      if (!mapa.getPane('calor')) {
        var pane = mapa.createPane('calor');
        pane.style.zIndex = 380;
        pane.style.opacity = '.6';
        pane.style.pointerEvents = 'none';
      }
      L.heatLayer(pts.map(function (p) {
        var x = ppm(p);
        return [p.lat, p.lon, (x > 0 && tope > 0) ? Math.min(1, Math.max(.3, x / tope)) : .5];
      }), { pane: 'calor', radius: 32, blur: 28, maxZoom: 15, minOpacity: .22,
            gradient: { .2: '#c9d9ea', .4: '#7fa8cf', .6: '#e9a26f', .8: NARANJA, 1: '#b5341a' } }).addTo(capaCalor);
    });
  }

  /* ---------- puntos del mapa ----------
     Dos problemas que se arreglan aqui:

     1) Los portales geocodifican todos los lotes de un fraccionamiento al
        mismo punto. Medido: 41 de 98 anuncios compartian coordenada, y once
        caian exactamente en la entrada de Las Trojes. Se dibujaba un marcador
        por anuncio, encimados, asi que solo el ultimo era clicable: 41% del
        inventario no existia para quien mira el mapa. Ahora se agrupan y el
        globo lista todos los del punto.

     2) Un anuncio "borde" no cae dentro de ninguna zona: se le asigna la mas
        cercana (mediana 0.8 km, hasta 2.5 km). Se veia identico a uno medido
        dentro. Ahora va hueco y con el anillo punteado, y dice a que distancia
        quedo. Conserva el color de SU zona a proposito: ese anuncio si entra
        en la mediana de esa zona, y pintarlo gris haria que el mapa dijera
        una cosa y la grafica otra. El gris ya significa "limite municipal".  */

  function esAprox(p) { return p._estado === 'borde' || p._estado === 'periferia'; }

  function fichaDe(p) {
    var v = ppm(p), meta = [];
    if (p.m2) meta.push(num(p.m2) + ' m²');
    if (p.precio) meta.push(mxn(p.precio) + ' total');
    var dias = diasEnMercado(p);
    var col = p._color || MUTED;
    var arch = p.activo === 0 || p.activo === false;
    return '<div class="emg"><div class="t">' +
      '<span class="z" style="color:' + col + '">' + (p.zona || 'Sin zona') + '</span>' +
      '<span class="chip">' + nombrePortal(p.fuente) + '</span></div>' +
      (p.nombre_colonia ? '<div style="font-weight:600;font-size:.85rem;margin-bottom:5px">' + p.nombre_colonia + '</div>' : '') +
      '<div class="pr">' + (v && ppmOk(v) ? mxn(v) + ' /m²' : (p.precio ? mxn(p.precio) : 'Precio no publicado')) + '</div>' +
      '<div class="me">' + (meta.join(' · ') || 'Sin superficie') +
      (p.fecha_publicacion ? '<br>Publicado: ' + p.fecha_publicacion + (dias != null ? ' (' + dias + ' días)' : '') : '') + '</div>' +
      (esAprox(p) ? '<div class="h aprox">Ubicación aproximada: cae fuera de las zonas y se le asignó ' +
                    (p.zona ? corta(p.zona) : 'la más cercana') +
                    (p._distanciaKm != null ? ', a ' + p._distanciaKm.toFixed(1) + ' km' : '') + '</div>' : '') +
      (arch ? '<div class="h">Oferta archivada: ya no aparece en el portal</div>' : '') +
      (p.url ? '<a class="btn" href="' + p.url + '" target="_blank" rel="noopener noreferrer">Ver anuncio ↗</a>'
             : '<span class="sutil">Sin liga al anuncio</span>') + '</div>';
  }

  /* De lejos importa el patron, de cerca el anuncio. Con marcadores de tamano
     fijo, alejarse los amontona y el mapa se enturbia: los aros y los numeros
     dejan de leerse pero siguen ocupando lugar. Debajo de este zoom se reducen
     a puntos limpios y el calor lleva la lectura. */
  var ZOOM_DETALLE = 12;
  function conDetalle() { return mapa.getZoom() >= ZOOM_DETALLE; }

  // Area proporcional al conteo: un grupo de 11 tiene que verse mayor que uno
  // de 2. Antes todos median 26px y el tamano no decia nada.
  function ladoGrupo(n) { return Math.round(Math.min(34, 16 + 3.6 * Math.sqrt(n))); }

  function iconoPunto(p, cuantos) {
    var col = p._color || MUTED;
    var arch = p.activo === 0 || p.activo === false;
    var aprox = esAprox(p);
    var detalle = conDetalle();

    if (cuantos > 1) {
      if (!detalle) {
        var d = Math.round(Math.min(20, 9 + 2.2 * Math.sqrt(cuantos)));
        return L.divIcon({ className: 'mk',
          html: '<div class="grupo lejos" style="background:' + col + ';width:' + d + 'px;height:' + d + 'px"></div>',
          iconSize: [d, d], iconAnchor: [d / 2, d / 2] });
      }
      var s = ladoGrupo(cuantos);
      return L.divIcon({ className: 'mk',
        html: '<div class="grupo" style="background:' + col + ';width:' + s + 'px;height:' + s + 'px;' +
              'font-size:' + (s < 22 ? 10 : 11.5) + 'px">' + cuantos + '</div>',
        iconSize: [s, s], iconAnchor: [s / 2, s / 2] });
    }

    if (!detalle) {
      // Sueltos de lejos: un punto y ya. El aproximado solo se aclara.
      return L.divIcon({ className: 'mk',
        html: '<div class="chico" style="background:' + col + (aprox || arch ? ';opacity:.5' : '') + '"></div>',
        iconSize: [8, 8], iconAnchor: [4, 4] });
    }

    return L.divIcon({
      className: 'mk',
      html: '<div style="position:relative;width:14px;height:14px">' +
            (arch || aprox ? '' : '<div class="anillo" style="background:' + col + '"></div>' +
                                  '<div class="anillo" style="background:' + col + ';animation-delay:900ms"></div>') +
            // Aproximado: aro de tinta (dice "aproximado") con nucleo del color
            // de su zona (dice a cual pertenece). Sin numero, para no chocar con
            // el conteo de los grupos: el mismo digito con dos significados.
            (aprox ? '<div class="aro"></div><div class="centro" style="background:' + col + '"></div>'
                   : '<div class="nucleo" style="background:' + col + (arch ? ';opacity:.45' : '') + '"></div>') +
            '</div>',
      iconSize: [14, 14], iconAnchor: [7, 7]
    });
  }

  var ultimosPts = [], bandaPrevia = null;
  function dibujarPuntos(pts) {
    ultimosPts = pts;
    bandaPrevia = conDetalle();
    capaPuntos.clearLayers();

    // Agrupa por coordenada redondeada a ~11 m: eso junta tanto los duplicados
    // exactos como los que quedan a unos metros y de todos modos se encimarian.
    var grupos = {}, orden = [];
    pts.forEach(function (p) {
      if (p.lat == null || p.lon == null) return;
      var k = p.lat.toFixed(4) + ',' + p.lon.toFixed(4);
      if (!grupos[k]) { grupos[k] = []; orden.push(k); }
      grupos[k].push(p);
    });

    orden.forEach(function (k) {
      var g = grupos[k], p0 = g[0], n = g.length;
      var mk = L.marker([p0.lat, p0.lon], { icon: iconoPunto(p0, n), riseOnHover: true });

      if (n === 1) {
        var v = ppm(p0), meta = [];
        if (p0.m2) meta.push(num(p0.m2) + ' m²');
        if (p0.precio) meta.push(mxn(p0.precio) + ' total');
        if (p0.nombre_colonia) meta.unshift(p0.nombre_colonia);
        var dias = diasEnMercado(p0);
        var col = p0._color || MUTED;
        var globo = '<span class="z" style="color:' + col + '">' + (p0.zona || 'Sin zona') + '</span>' +
          '<div class="p">' + (v && ppmOk(v) ? mxn(v) + ' /m²' : (p0.precio ? mxn(p0.precio) : 'Precio no publicado')) + '</div>' +
          '<div class="m">' + (meta.join(' · ') || 'Sin datos de superficie') + '</div>' +
          '<div class="m">' + nombrePortal(p0.fuente) +
            (dias != null ? ' · ' + dias + ' días publicado' : '') + '</div>' +
          (esAprox(p0) ? '<div class="h">Ubicación aproximada</div>' : '') +
          (p0.url ? '<div class="h">Clic para abrir el anuncio</div>' : '');
        mk.bindTooltip(globo, { className: 'globo', direction: 'top', offset: [0, -10], sticky: true, opacity: 1 })
          .bindPopup(fichaDe(p0));
      } else {
        var ppms = g.map(ppm).filter(function (x) { return x > 0 && ppmOk(x); });
        var donde = p0.nombre_colonia || (p0.zona ? corta(p0.zona) : 'este punto');
        mk.bindTooltip(
          '<span class="z" style="color:' + (p0._color || MUTED) + '">' + donde + '</span>' +
          '<div class="p">' + n + ' ofertas aquí</div>' +
          '<div class="m">' + (ppms.length ? 'Mediana ' + mxn(mediana(ppms)) + ' /m²' : 'Sin precio por m²') + '</div>' +
          '<div class="h">Clic para verlas una por una</div>',
          { className: 'globo', direction: 'top', offset: [0, -16], sticky: true, opacity: 1 });
        // El globo lista TODAS: es la unica forma de llegar a las que antes
        // quedaban tapadas debajo del marcador de encima.
        var lista = g.map(function (p) {
          var v2 = ppm(p);
          return '<a class="reng" ' + (p.url ? 'href="' + p.url + '" target="_blank" rel="noopener noreferrer"' : '') + '>' +
            '<span class="r1">' + (p.m2 ? num(p.m2) + ' m²' : 'sin superficie') + '</span>' +
            '<span class="r2">' + (v2 && ppmOk(v2) ? mxn(v2) + '/m²' : (p.precio ? mxn(p.precio) : '—')) + '</span>' +
            (p.url ? '<span class="r3">↗</span>' : '') + '</a>';
        }).join('');
        mk.bindPopup(
          '<div class="emg"><div class="t">' +
          '<span class="z" style="color:' + (p0._color || MUTED) + '">' + (p0.zona || 'Sin zona') + '</span>' +
          '<span class="chip">' + n + ' ofertas</span></div>' +
          '<div style="font-weight:600;font-size:.85rem;margin-bottom:2px">' + donde + '</div>' +
          '<div class="me" style="margin-bottom:8px">Los portales las publican en la misma coordenada' +
          (esAprox(p0) ? ', y el punto es aproximado' : '') + '.</div>' +
          '<div class="rengs">' + lista + '</div></div>',
          { maxHeight: 260 });
      }
      mk.addTo(capaPuntos);
    });
  }

  var aproximados = 0, dibujados = 0;
  var notaVia = '.', notaArchivadas = 0;
  // Solo se redibuja al CRUZAR el umbral, no en cada rueda del raton.
  mapa.on('zoomend', function () {
    if (!ultimosPts.length) return;
    if (conDetalle() !== bandaPrevia) dibujarPuntos(ultimosPts);
  });

  function dibujarLeyenda() {
    var c = document.getElementById('leyenda');
    c.innerHTML = '';
    function it(html) {
      var e = document.createElement('span'); e.className = 'it-ley'; e.innerHTML = html; c.appendChild(e);
    }
    if (window.TORREON_MUNICIPIO) {
      it('<span class="trazo" style="border-top:2px dashed ' + MUTED + '"></span>Límite municipal');
    }
    // Solo las zonas que existen como polígono. La categoría de reserva
    // ("Fuera de la mancha urbana") no se dibuja: aparece solo si captura algo.
    (window.TORREON_ZONAS.features || []).map(GeoZonas.nombreDe).forEach(function (n) {
      var col = GeoZonas.COLOR_ZONA[n] || MUTED, k = conteoZona[n] || 0;
      it('<span class="trazo" style="border-top-color:' + col + '"></span>' + corta(n) + ' <b>(' + k + ')</b>');
    });
    var per = conteoZona[GeoZonas.ZONA_PERIFERIA] || 0;
    if (per) {
      it('<span class="trazo" style="border-top-color:' + GeoZonas.COLOR_ZONA[GeoZonas.ZONA_PERIFERIA] + '"></span>' +
         GeoZonas.ZONA_PERIFERIA + ' <b>(' + per + ')</b>');
    }
    var na = document.getElementById('nota-aprox');
    if (na) {
      na.innerHTML = aproximados
        ? 'En esta corrida son <b>' + num(aproximados) + '</b> de <b>' + num(dibujados) + '</b>.'
        : '';
    }
    if (aproximados) {
      it('<span class="pt-aprox"></span>Ubicación aproximada <b>(' + aproximados + ')</b>');
    }
  }

  /* ================= indicadores ================= */
  function pintarKpis(pts, res) {
    document.getElementById('k-total').textContent = pts.length;
    // Cuántos portales aportaron ESTA oferta, contado sobre los datos. Estaba
    // fijo en "2 portales" y seguía diciéndolo con un portal caído.
    var portales = {};
    pts.forEach(function (p) { if (p.fuente) portales[p.fuente] = 1; });
    var np = Object.keys(portales).length;
    document.getElementById('k-total-pie').textContent =
      res.fuera ? (res.fuera + ' descartado(s) por ubicarse fuera del municipio')
                : (np === 1 ? 'en 1 portal con datos hoy' : 'en ' + np + ' portales monitoreados');

    var todos = pts.map(ppm).filter(function (v) { return v > 0; });
    var buenos = todos.filter(ppmOk), atip = todos.length - buenos.length;
    document.getElementById('k-precio').textContent = buenos.length ? mxn(mediana(buenos)) : '—';
    document.getElementById('k-precio-pie').textContent =
      atip ? 'mediana por m² · ' + atip + ' atípico(s) excluido(s)' : 'mediana por m² de terreno';

    var m2 = pts.map(function (p) { return Number(p.m2); }).filter(function (v) { return v > 0; });
    document.getElementById('k-m2').textContent = m2.length ? num(mediana(m2)) : '—';

    var ds = pts.map(diasEnMercado).filter(function (v) { return v != null; });
    document.getElementById('k-dias').textContent = ds.length ? num(mediana(ds)) : '—';
    var viejos = ds.filter(function (d) { return d > 180; }).length;
    document.getElementById('k-dias-pie').textContent = viejos
      ? viejos + ' llevan más de 6 meses sin venderse'
      : 'mediana de la oferta activa';
  }

  // Las cifras de validacion ya no viven en tarjetas aparte: van dentro del
  // paso del pipeline que las produce, que es donde se entienden.
  function pintarDiagnostico(r) {
    var c = document.getElementById('diagnostico');
    if (!c) return;
    var ubicados = (r.dentro || 0) + (r.borde || 0) + (r.periferia || 0);
    var partes = [];
    partes.push('<b>' + num(r.dentro || 0) + '</b> caen dentro de una zona urbana');
    if (r.borde) partes.push('<b>' + num(r.borde) + '</b> los absorbe la zona más cercana');
    if (r.periferia) partes.push('<b>' + num(r.periferia) + '</b> quedan en la Periferia Sur');
    var t = 'De ' + num(ubicados + (r.fuera || 0) + (r.sinCoords || 0)) + ' anuncios procesados: ' +
            partes.join('; ') + '.';
    if (r.fuera) t += ' <b>' + num(r.fuera) + '</b> se descarta(n) por ubicarse fuera del municipio.';
    if (r.sinCoords) t += ' <b>' + num(r.sinCoords) + '</b> sin coordenadas.';
    c.className = 'dato';
    c.innerHTML = t;
  }

  function pintarSegmentos(pts) {
    var c = document.getElementById('segmentos');
    c.innerHTML = '';
    // Base del índice: la mediana de TODA la oferta. Cada segmento se expresa
    // contra ella, así se lee de un golpe cuál va arriba y cuál abajo del
    // mercado sin tener que comparar pesos contra pesos.
    var todos = pts.map(ppm).filter(ppmOk);
    var base = todos.length ? mediana(todos) : null;

    SEGMENTOS.forEach(function (s) {
      var v = pts.filter(function (p) {
        var m = Number(p.m2);
        return m >= s.lo && m < s.hi && ppmOk(ppm(p));
      }).map(ppm);
      var pocos = v.length > 0 && v.length < 10;
      var med = v.length ? mediana(v) : null;
      var idx = (med != null && base) ? Math.round(med / base * 100) : null;

      var d = document.createElement('div');
      d.className = 'seg' + (pocos ? ' pocos' : '');
      d.innerHTML = '<div class="n1">' + s.nombre + '</div>' +
        '<div class="n3">' + (med != null ? mxn(med) : '—') + '</div>' +
        '<div class="n4">mediana por m²</div>' +
        (idx != null
          ? '<div class="idx' + (idx >= 100 ? ' alto' : ' bajo') + '">Índice ' + idx +
            '<span>base 100 = mediana general</span></div>'
          : '') +
        '<span class="n5">n = ' + v.length + (pocos ? ' · muestra chica' : '') + '</span>';
      c.appendChild(d);
    });
  }

  /* ================= gráficas ================= */
  // Serie única = un solo color. El eje etiqueta cada barra, así que el color
  // no carga identidad y no hace falta leyenda.
  var charts = {};
  function opciones(extra) {
    var base = {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#171310', titleColor: '#fff', bodyColor: '#E8E2DC',
          padding: 11, cornerRadius: 9, displayColors: false,
          titleFont: { family: 'Archivo', weight: '700', size: 12.5 }, bodyFont: { size: 12 }
        }
      },
      scales: {
        x: { grid: { display: false }, border: { color: '#C9C2BA' },
             ticks: { color: GRIS, font: { size: 11 } } },
        y: { grid: { color: REJILLA }, border: { display: false },
             ticks: { color: MUTED, font: { size: 11 } } }
      }
    };
    return Object.assign({}, base, extra || {});
  }
  // Etiqueta de valor directo sobre cada barra, en tinta — nunca en el color de la serie.
  var etiquetas = {
    id: 'etiquetas',
    afterDatasetsDraw: function (ch, args, cfg) {
      var ctx = ch.ctx, meta = ch.getDatasetMeta(0), fmt = cfg.fmt || String;
      ctx.save();
      ctx.fillStyle = TINTA;
      ctx.font = '700 11px Archivo, sans-serif';
      meta.data.forEach(function (bar, i) {
        var v = ch.data.datasets[0].data[i];
        if (v == null) return;
        if (cfg.horizontal) {
          ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
          ctx.fillText(fmt(v), bar.x + 7, bar.y);
        } else {
          ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
          ctx.fillText(fmt(v), bar.x, bar.y - 6);
        }
      });
      ctx.restore();
    }
  };
  function dibujar(id, cfg) {
    if (!window.Chart) return;
    var el = document.getElementById(id);
    if (!el) return;
    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart(el, cfg);
  }

  var REDUCIR = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Las barras y la linea crecen desde la base, no aparecen ya dibujadas: sube
  // el nivel como agua, con un retardo por columna que lo vuelve una ola.
  var ANIM = REDUCIR ? false : {
    duration: 1500, easing: 'easeOutQuart',
    delay: function (c) {
      return (c.type === 'data' && c.mode === 'default') ? c.dataIndex * 110 : 0;
    }
  };
  // El origen del recorrido: el cero del eje, o el piso del area si el eje
  // no arranca en cero (la historica va recortada al rango de la serie).
  var DESDE_BASE = REDUCIR ? undefined : {
    y: {
      from: function (c) {
        if (c.type !== 'data' || c.mode !== 'default') return undefined;
        var s = c.chart.scales.y;
        if (!s) return undefined;
        return s.getPixelForValue(s.min > 0 ? s.min : 0);
      }
    }
  };

  /* ---------- movimiento continuo: el liquido nunca se queda quieto ----------
     Regla: la ALTURA de la barra y la posicion de los puntos NO se tocan; esas
     son el dato. Lo que se mueve es el relleno de adentro —un brillo que sube
     como corriente y una ondita en la superficie—, recortado al area de cada
     barra. Asi el tablero respira sin que ninguna cifra parezca cambiar. */
  var reloj = 0, latiendo = false;
  var vivas = [];   // graficas con liquido, en pantalla y ya asentadas

  function sheen(ctx, x, ancho, arriba, alto, fase) {
    if (alto <= 1) return;
    var recorrido = alto + 70;
    var cy = arriba + alto - ((fase % 1) * recorrido) + 35;
    var g = ctx.createLinearGradient(0, cy - 34, 0, cy + 34);
    g.addColorStop(0, 'rgba(255,255,255,0)');
    g.addColorStop(.5, 'rgba(255,255,255,.30)');
    g.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = g;
    ctx.fillRect(x, arriba, ancho, alto);
  }
  function onda(ctx, x, ancho, arriba, t, amplitud) {
    ctx.beginPath();
    for (var k = 0; k <= ancho; k += 3) {
      var y = arriba + Math.sin((k / ancho) * Math.PI * 2 + t) * amplitud;
      if (k === 0) ctx.moveTo(x + k, y); else ctx.lineTo(x + k, y);
    }
    ctx.strokeStyle = 'rgba(255,255,255,.55)';
    ctx.lineWidth = 1.6;
    ctx.stroke();
  }

  var liquido = {
    id: 'liquido',
    afterDatasetsDraw: function (ch) {
      if (REDUCIR) return;
      var ctx = ch.ctx, meta = ch.getDatasetMeta(0);
      if (!meta || !meta.data.length) return;
      var t = reloj / 1000;

      if (ch.config.type === 'line') {
        // Recorta al area bajo la linea y pasa el brillo por dentro.
        var base = ch.chartArea.bottom, ps = [];
        meta.data.forEach(function (e) { ps.push(e.getProps(['x', 'y'], true)); });
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(ps[0].x, base);
        ps.forEach(function (q) { ctx.lineTo(q.x, q.y); });
        ctx.lineTo(ps[ps.length - 1].x, base);
        ctx.closePath();
        ctx.clip();
        var top = ch.chartArea.top;
        sheen(ctx, ch.chartArea.left, ch.chartArea.right - ch.chartArea.left, top, base - top, t / 4.2);
        ctx.restore();
        return;
      }

      meta.data.forEach(function (el, i) {
        var q = el.getProps(['x', 'y', 'base', 'width'], true);
        var ancho = q.width, x = q.x - ancho / 2;
        var arriba = Math.min(q.y, q.base), alto = Math.abs(q.base - q.y);
        if (alto <= 2) return;
        ctx.save();
        ctx.beginPath();
        ctx.rect(x, arriba, ancho, alto);
        ctx.clip();
        sheen(ctx, x, ancho, arriba, alto, t / 3.4 + i * 0.17);
        // La superficie ondula apenas: es tension de agua, no ruido del dato.
        onda(ctx, x, ancho, arriba + 1.4, t * 1.5 + i * 0.9, 1.3);
        ctx.restore();
      });
    }
  };

  var ultimoCuadro = 0;
  function latir(ts) {
    reloj = ts || 0;
    // 30 c/s alcanzan de sobra para un liquido lento y no calientan la laptop.
    if (reloj - ultimoCuadro < 33) { requestAnimationFrame(latir); return; }
    ultimoCuadro = reloj;
    var alguna = false;
    vivas.forEach(function (id) {
      var ch = charts[id], el = document.getElementById(id);
      if (!ch || !el) return;
      var r = el.getBoundingClientRect();
      // Fuera de pantalla no se dibuja: no tiene sentido gastar cuadros ahi.
      if (r.bottom < 0 || r.top > (window.innerHeight || 0)) return;
      alguna = true;
      ch.draw();
    });
    if (alguna || vivas.length) requestAnimationFrame(latir);
    else latiendo = false;
  }
  function animarLiquido(id) {
    if (REDUCIR || vivas.indexOf(id) !== -1) return;
    vivas.push(id);
    if (!latiendo) { latiendo = true; requestAnimationFrame(latir); }
  }

  // Chart.js anima al construirse. Si el tablero se pinta completo al cargar,
  // las graficas de abajo terminan su recorrido antes de que nadie baje a
  // verlas. Esto lo retiene y lo dispara cuando cada una entra a pantalla.
  var yaCorrio = {};
  var mirilla = null;
  var CON_LIQUIDO = ['gZonas', 'gTamano', 'gAntiguedad', 'gTendencia'];
  // Primero sube el nivel (entrada), y ya asentado empieza a moverse.
  function liquidoTrasEntrada(id) {
    if (CON_LIQUIDO.indexOf(id) === -1) return;
    setTimeout(function () { animarLiquido(id); }, 1900);
  }
  function destaparGraficas() {
    Object.keys(charts).forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.style.opacity = '1';
    });
  }
  function observarGraficas() {
    // Sin observador o con movimiento reducido: todo visible y sin trucos.
    if (REDUCIR || !('IntersectionObserver' in window)) {
      destaparGraficas();
      Object.keys(charts).forEach(liquidoTrasEntrada);
      return;
    }
    if (!mirilla) {
      mirilla = new IntersectionObserver(function (filas) {
        filas.forEach(function (f) {
          if (!f.isIntersecting) return;
          var id = f.target.id, ch = charts[id];
          mirilla.unobserve(f.target);
          if (!ch) { f.target.style.opacity = '1'; return; }
          if (yaCorrio[id]) return;
          yaCorrio[id] = 1;
          ch.reset();                      // vuelve al piso
          f.target.style.opacity = '1';    // ya sin pixeles viejos que delaten
          ch.update();                     // y sube
          liquidoTrasEntrada(id);
        });
      }, { threshold: .3 });
    }
    Object.keys(charts).forEach(function (id) {
      var el = document.getElementById(id);
      if (!el || yaCorrio[id]) return;
      // Si ya se ve al cargar, que anime de inmediato; si no, al llegar.
      var r = el.getBoundingClientRect();
      if (r.top < (window.innerHeight || 0) && r.bottom > 0) {
        yaCorrio[id] = 1; liquidoTrasEntrada(id); return;
      }
      // El canvas guarda los pixeles de su ultimo dibujo, asi que al bajar se
      // veria la grafica ya terminada un instante antes de caer al piso. Se
      // mantiene invisible hasta que le toca subir.
      el.style.opacity = '0';
      charts[id].reset();
      mirilla.observe(el);
      // Red de seguridad: si nadie baja (impresión, captura de pantalla, un
      // navegador que no dispara el observador), a los 4 s se destapa igual.
      // Una gráfica invisible es peor que una que no animó.
      setTimeout(function () {
        if (yaCorrio[id]) return;
        yaCorrio[id] = 1;
        el.style.opacity = '1';
        if (charts[id]) charts[id].update();
        liquidoTrasEntrada(id);
      }, 4000);
    });
  }

  // Degradado vertical: el color pleno arriba, translucido abajo.
  function vGrad(area, ctx, hex) {
    var g = ctx.createLinearGradient(0, area.top, 0, area.bottom);
    g.addColorStop(0, hex); g.addColorStop(1, hex + 'AA');
    return g;
  }
  function relleno(hex) {
    return function (c) {
      var a = c.chart.chartArea;
      return a ? vGrad(a, c.chart.ctx, hex) : hex;
    };
  }
  function relleno2(cols) {
    return function (c) {
      var a = c.chart.chartArea, hex = cols[c.dataIndex] || AZUL;
      return a ? vGrad(a, c.chart.ctx, hex) : hex;
    };
  }

  var MESES = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
  function etiqMes(k) { var q = String(k).split('-'); return MESES[+q[1] - 1] + ' ' + q[0].slice(2); }

  // La serie de la grafica historica. Prioridad:
  //   1) el indice diario real, si el backend ya lo publica en DATOS_MONITOR.serie
  //   2) si no, se reconstruye por mes de publicacion con el corpus vigente
  // Se marca cual de las dos es, porque no significan lo mismo.
  function serieMercado(pts) {
    var s = window.DATOS_MONITOR && window.DATOS_MONITOR.serie;
    if (s && s.length) {
      return { origen: 'indice', filas: s.map(function (x) {
        return { k: x.fecha, et: x.fecha, v: Math.round(x.precio_m2), n: x.n || 0 };
      }) };
    }
    var g = {};
    pts.forEach(function (p) {
      var f = p.fecha_publicacion, v = ppm(p);
      if (!f || !ppmOk(v)) return;
      var k = String(f).slice(0, 7);
      (g[k] = g[k] || []).push(v);
    });
    var filas = Object.keys(g).sort().map(function (k) {
      return { k: k, et: etiqMes(k), v: Math.round(mediana(g[k])), n: g[k].length };
    });
    return { origen: 'publicacion', filas: filas };
  }

  var N_FIRME = 5;   // debajo de esto la mediana la mueve un solo anuncio

  function pintarTendencia(pts) {
    var el = document.getElementById('gTendencia');
    if (!el) return;
    var s = serieMercado(pts), filas = s.filas;
    var desc = document.getElementById('tend-desc');

    if (filas.length < 2) {
      if (desc) desc.textContent = 'Aún no hay suficientes corridas para trazar la serie.';
      return;
    }

    if (desc) {
      desc.innerHTML = s.origen === 'indice'
        ? 'Mediana de $/m² de toda la oferta vigente, corrida por corrida.'
        : 'Mediana de $/m² según el <b>mes en que se publicó</b> la oferta que sigue vigente.';
    }

    var vals = filas.map(function (f) { return f.v; });
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals), pad = Math.max(120, (hi - lo) * .35);

    dibujar('gTendencia', {
      type: 'line', plugins: [liquido],
      data: { labels: filas.map(function (f) { return f.et; }), datasets: [{
        data: vals, borderColor: NARANJA, borderWidth: 3, tension: .38, fill: true,
        pointBackgroundColor: filas.map(function (f) { return f.n < N_FIRME ? '#fff' : NARANJA; }),
        pointBorderColor: NARANJA, pointBorderWidth: 2.5,
        pointRadius: filas.map(function (f) { return f.n < N_FIRME ? 4.5 : 5.5; }),
        pointHoverRadius: 8,
        backgroundColor: function (c) {
          var a = c.chart.chartArea;
          if (!a) return 'rgba(233,80,38,.12)';
          var g = c.chart.ctx.createLinearGradient(0, a.top, 0, a.bottom);
          g.addColorStop(0, 'rgba(233,80,38,.28)'); g.addColorStop(1, 'rgba(233,80,38,0)');
          return g;
        }
      }] },
      options: opciones({
        animation: ANIM, animations: DESDE_BASE,
        plugins: { legend: { display: false }, tooltip: { callbacks: {
          label: function (c) { return mxn(c.parsed.y) + ' /m² (mediana)'; },
          afterLabel: function (c) {
            var f = filas[c.dataIndex];
            return f.n + (f.n === 1 ? ' anuncio' : ' anuncios') + (f.n < N_FIRME ? ' · muestra chica' : '');
          } } } },
        scales: {
          x: { grid: { display: false }, border: { color: '#C9C2BA' },
               ticks: { color: GRIS, font: { size: 11, weight: '600' } } },
          y: { min: Math.max(0, lo - pad), max: hi + pad, grid: { color: REJILLA },
               border: { display: false },
               ticks: { color: MUTED, font: { size: 11 }, callback: function (v) { return mxn(v); } } }
        }
      })
    });
  }

  function pintarGraficas(pts) {
    if (!window.Chart) { console.info('Chart.js no cargó; se omiten las gráficas.'); return; }
    Chart.defaults.font.family = "'Libre Franklin', system-ui, sans-serif";
    Chart.defaults.color = GRIS;

    // 1) precio mediano por zona — color por zona, el mismo del mapa
    var nz = (window.TORREON_ZONAS.features || []).map(GeoZonas.nombreDe).concat([GeoZonas.ZONA_PERIFERIA]);
    var et = [], va = [], cz = [];
    nz.forEach(function (z) {
      var v = pts.filter(function (p) { return p.zona === z && ppmOk(ppm(p)); }).map(ppm);
      if (!v.length) return;
      // Chart.js acepta un arreglo por etiqueta y lo pinta en renglones. Así
      // "Poniente y Centro Histórico" deja de necesitar el eje en diagonal.
      et.push(corta(z).split(' y ')); va.push(Math.round(mediana(v)));
      cz.push((GeoZonas.COLOR_ZONA && GeoZonas.COLOR_ZONA[z]) || AZUL);
    });
    dibujar('gZonas', {
      type: 'bar', plugins: [etiquetas, liquido],
      data: { labels: et, datasets: [{ data: va, backgroundColor: relleno2(cz),
              borderRadius: 10, borderSkipped: false, maxBarThickness: 56 }] },
      options: opciones({
        animation: ANIM, animations: DESDE_BASE, layout: { padding: { top: 22 } },
        plugins: { legend: { display: false }, etiquetas: { fmt: mxn },
                   tooltip: { callbacks: { label: function (c) { return mxn(c.parsed.y) + ' /m² (mediana)'; } } } },
        scales: { x: { grid: { display: false },
                       ticks: { color: GRIS, font: { size: 10, weight: '600' },
                                maxRotation: 0, minRotation: 0, autoSkip: false } },
                  y: { display: false, beginAtZero: true } }
      })
    });

    // 2) distribución por tamaño
    var cnt = SEGMENTOS.map(function (s) {
      return pts.filter(function (p) { var m = Number(p.m2); return m >= s.lo && m < s.hi; }).length;
    });
    dibujar('gTamano', {
      type: 'bar', plugins: [etiquetas, liquido],
      data: { labels: SEGMENTOS.map(function (s) { return s.corto; }),
              datasets: [{ data: cnt, backgroundColor: relleno(AZUL),
                           borderRadius: 10, borderSkipped: false, maxBarThickness: 56 }] },
      options: opciones({
        animation: ANIM, animations: DESDE_BASE, layout: { padding: { top: 22 } },
        plugins: { legend: { display: false }, etiquetas: { fmt: num },
                   tooltip: { callbacks: { label: function (c) { return c.parsed.y + ' terrenos · ' + SEGMENTOS[c.dataIndex].rango; } } } },
        scales: { x: { grid: { display: false }, ticks: { color: GRIS, font: { size: 10, weight: '600' } } },
                  y: { display: false, beginAtZero: true } }
      })
    });

    // 3) antigüedad — lo viejo en naranja: es el hallazgo, no decoración
    var pm = {};
    pts.forEach(function (p) { if (p.fecha_publicacion) { var m = String(p.fecha_publicacion).slice(0, 7); pm[m] = (pm[m] || 0) + 1; } });
    var meses = Object.keys(pm).sort();
    var corte = new Date(); corte.setMonth(corte.getMonth() - 6);
    var claveCorte = corte.toISOString().slice(0, 7);
    dibujar('gAntiguedad', {
      type: 'bar', plugins: [etiquetas, liquido],
      data: {
        labels: meses.map(etiqMes),
        datasets: [{ data: meses.map(function (m) { return pm[m]; }),
                     backgroundColor: relleno2(meses.map(function (m) { return m < claveCorte ? NARANJA : '#C9BFB2'; })),
                     borderRadius: 10, borderSkipped: false, maxBarThickness: 46 }]
      },
      options: opciones({
        animation: ANIM, animations: DESDE_BASE, layout: { padding: { top: 22 } },
        plugins: { legend: { display: false }, etiquetas: { fmt: num },
                   tooltip: { callbacks: { label: function (c) {
                     return c.parsed.y + ' terrenos publicados ese mes, aún en venta'; } } } },
        scales: { x: { grid: { display: false }, ticks: { color: GRIS, font: { size: 10, weight: '600' } } },
                  y: { display: false, beginAtZero: true } }
      })
    });

    // 4) por portal — dona, y el total al centro. Un portal caído se ve como
    //    hueco en la dona, no como una barra sola que no dice nada.
    var pp = {};
    pts.forEach(function (p) { var f = p.fuente || 'sin dato'; pp[f] = (pp[f] || 0) + 1; });
    var ks = Object.keys(pp).sort(function (a, b) { return pp[b] - pp[a]; });
    var COLP = [AZUL, NARANJA, '#1A7A47', '#C6881E', '#5B4B8A'];
    dibujar('gPortales', {
      type: 'doughnut',
      data: { labels: ks.map(nombrePortal),
              datasets: [{ data: ks.map(function (k) { return pp[k]; }),
                           backgroundColor: ks.map(function (_, i) { return COLP[i % COLP.length]; }),
                           borderWidth: 3, borderColor: '#fff', hoverOffset: 10, spacing: 2 }] },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: '66%',
        animation: REDUCIR ? false : { duration: 1500, easing: 'easeOutQuart',
                    animateRotate: true, animateScale: true },
        plugins: {
          legend: { position: 'bottom', labels: { padding: 14, boxWidth: 9, boxHeight: 9,
                    usePointStyle: true, font: { size: 11 } } },
          tooltip: {
            backgroundColor: '#171310', titleColor: '#fff', bodyColor: '#E8E2DC',
            padding: 11, cornerRadius: 9, displayColors: false,
            titleFont: { family: 'Archivo', weight: '700', size: 12.5 }, bodyFont: { size: 12 },
            callbacks: { label: function (c) {
              return c.parsed === 0 ? ' sin anuncios en esta corrida' : ' ' + c.parsed + ' anuncios'; } }
          }
        }
      },
      plugins: [{
        id: 'centro',
        afterDraw: function (ch) {
          var a = ch.chartArea; if (!a) return;
          var ctx = ch.ctx, cx = a.left + a.width / 2, cy = a.top + a.height / 2;
          var tot = ks.reduce(function (s, k) { return s + pp[k]; }, 0);
          ctx.save(); ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillStyle = TINTA; ctx.font = '800 30px Archivo, sans-serif';
          ctx.fillText(num(tot), cx, cy - 8);
          ctx.fillStyle = MUTED; ctx.font = '600 11px Libre Franklin, sans-serif';
          ctx.fillText('anuncios', cx, cy + 15);
          ctx.restore();
        }
      }]
    });

    // 5) la historica, a lo ancho
    pintarTendencia(pts);

    // Y que cada una espere su turno en pantalla.
    observarGraficas();
  }

  /* ================= tabla ================= */
  var TODOS = [], orden = { col: 'fecha_publicacion', asc: false }, pagina = 1, POR_PAG = 12;

  function valorCol(p, col) {
    if (col === 'ppm') return ppm(p);
    if (col === 'dias') return diasEnMercado(p) || 0;
    if (col === 'm2' || col === 'precio') return Number(p[col]) || 0;
    return String(p[col] || '').toLowerCase();
  }

  function filtrados() {
    var z = document.getElementById('f-zona').value,
        s = document.getElementById('f-seg').value,
        e = document.getElementById('f-estado').value,
        q = (document.getElementById('f-buscar').value || '').trim().toLowerCase();
    return TODOS.filter(function (p) {
      var arch = p.activo === 0 || p.activo === false;
      if (e === 'activas' && arch) return false;
      if (e === 'archivadas' && !arch) return false;
      if (z && p.zona !== z) return false;
      if (s && segDe(p) !== s) return false;
      if (q && ((p.nombre_colonia || '') + ' ' + (p.zona || '')).toLowerCase().indexOf(q) === -1) return false;
      return true;
    });
  }

  function pintarTabla() {
    var lista = filtrados();
    lista.sort(function (a, b) {
      var x = valorCol(a, orden.col), y = valorCol(b, orden.col);
      if (x < y) return orden.asc ? -1 : 1;
      if (x > y) return orden.asc ? 1 : -1;
      return 0;
    });

    var paginas = Math.max(1, Math.ceil(lista.length / POR_PAG));
    if (pagina > paginas) pagina = paginas;
    var trozo = lista.slice((pagina - 1) * POR_PAG, pagina * POR_PAG);

    document.querySelector('#tabla tbody').innerHTML = trozo.map(function (p) {
      var v = ppm(p), col = p._color || MUTED, dias = diasEnMercado(p);
      var arch = p.activo === 0 || p.activo === false;
      return '<tr>' +
        '<td>' + (p.nombre_colonia || '—') +
          (p.ubicacion_precisa === false ? '<span class="tag aprox">aprox.</span>' : '') +
          (arch ? '<span class="tag arch">archivada</span>' : '') + '</td>' +
        '<td><span class="pz" style="background:' + col + '"></span>' + corta(p.zona) + '</td>' +
        '<td class="der">' + (p.m2 ? num(p.m2) + ' m²' : '—') + '</td>' +
        '<td class="der">' + (p.precio ? mxn(p.precio) : '—') + '</td>' +
        '<td class="der">' + (v && ppmOk(v) ? mxn(v) : '—') + '</td>' +
        '<td>' + (p.fecha_publicacion || '—') + '</td>' +
        '<td class="der">' + (dias != null ? num(dias) : '—') + '</td>' +
        '<td>' + (p.fuente === 'inmuebles24' ? 'Inmuebles24' : p.fuente === 'pincali' ? 'Pincali' : (p.fuente || '—')) + '</td>' +
        '<td>' + (p.url ? '<a class="liga" href="' + p.url + '" target="_blank" rel="noopener noreferrer">Ver ↗</a>' : '') + '</td>' +
      '</tr>';
    }).join('');

    document.getElementById('pie-tabla').textContent = lista.length + ' oferta(s)';
    document.getElementById('p-num').textContent = 'Página ' + pagina + ' de ' + paginas;
    document.getElementById('p-ant').disabled = pagina <= 1;
    document.getElementById('p-sig').disabled = pagina >= paginas;

    [].forEach.call(document.querySelectorAll('#tabla th[data-col]'), function (th) {
      var act = th.dataset.col === orden.col;
      th.classList.toggle('act', act);
      th.querySelector('.flecha').textContent = act ? (orden.asc ? '↑' : '↓') : '↕';
      th.setAttribute('aria-sort', act ? (orden.asc ? 'ascending' : 'descending') : 'none');
    });
  }

  function conectarTabla() {
    [].forEach.call(document.querySelectorAll('#tabla th[data-col]'), function (th) {
      // Ordenar era solo con clic: quien navega con teclado no podía. Se
      // anuncian como botones y responden a Enter y barra espaciadora.
      th.setAttribute('role', 'button');
      th.setAttribute('tabindex', '0');
      function ordenar() {
        var c = th.dataset.col;
        if (orden.col === c) orden.asc = !orden.asc;
        else { orden.col = c; orden.asc = (c === 'nombre_colonia' || c === 'zona' || c === 'fuente'); }
        pagina = 1; pintarTabla();
      }
      th.addEventListener('click', ordenar);
      th.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') { e.preventDefault(); ordenar(); }
      });
    });
    ['f-zona', 'f-seg', 'f-estado'].forEach(function (id) {
      document.getElementById(id).addEventListener('change', function () { pagina = 1; pintarTabla(); });
    });
    document.getElementById('f-buscar').addEventListener('input', function () { pagina = 1; pintarTabla(); });
    document.getElementById('p-ant').addEventListener('click', function () { if (pagina > 1) { pagina--; pintarTabla(); } });
    document.getElementById('p-sig').addEventListener('click', function () { pagina++; pintarTabla(); });
  }

  function llenarFiltros(pts) {
    var fz = document.getElementById('f-zona');
    var nombres = (window.TORREON_ZONAS.features || []).map(GeoZonas.nombreDe).concat([GeoZonas.ZONA_PERIFERIA]);
    nombres.forEach(function (z) {
      if (!pts.some(function (p) { return p.zona === z; })) return;
      var o = document.createElement('option'); o.value = z; o.textContent = corta(z); fz.appendChild(o);
    });
    var fs = document.getElementById('f-seg');
    SEGMENTOS.forEach(function (s) {
      var o = document.createElement('option'); o.value = s.nombre;
      o.textContent = s.nombre + ' (' + s.rango + ')'; fs.appendChild(o);
    });
  }

  /* ================= interruptores ================= */
  function sw(idSw, idLbl, capa) {
    var s = document.getElementById(idSw), l = document.getElementById(idLbl);
    s.addEventListener('change', function () {
      if (s.checked) { mapa.addLayer(capa); l.classList.add('on'); }
      else { mapa.removeLayer(capa); l.classList.remove('on'); }
    });
  }
  sw('s-calor', 'l-calor', capaCalor);
  sw('s-zonas', 'l-zonas', capaZonas);
  sw('s-etq', 'l-etq', capaEtq);
  sw('s-puntos', 'l-puntos', capaPuntos);

  /* ================= arranque ================= */
  function render(anuncios, origen, fecha) {
    var r = GeoZonas.clasificarLista(anuncios, window.TORREON_ZONAS);
    conteoZona = {}; aproximados = 0; dibujados = r.dibujables.length;
    r.dibujables.forEach(function (p) {
      if (p.zona) conteoZona[p.zona] = (conteoZona[p.zona] || 0) + 1;
      if (esAprox(p)) aproximados++;
    });

    intentar('mapa de calor', function () { dibujarCalor(r.dibujables); });
    intentar('puntos', function () { dibujarPuntos(r.dibujables); });
    intentar('leyenda', function () { dibujarLeyenda(); });
    intentar('indicadores', function () { pintarKpis(r.dibujables, r.resumen); });
    intentar('validación', function () { pintarDiagnostico(r.resumen); });
    intentar('segmentos', function () { pintarSegmentos(r.dibujables); });
    intentar('gráficas', function () { pintarGraficas(r.dibujables); });
    intentar('tabla', function () {
      TODOS = r.dibujables; llenarFiltros(TODOS); conectarTabla(); pintarTabla();
    });

    var nd = document.getElementById('nota-datos');
    if (nd) {
      nd.className = 'dato';
      nd.innerHTML = 'Datos <b>reales</b> del pipeline: <b>' + num(r.dibujables.length) + '</b> ofertas activas' +
        (notaArchivadas ? ' y <b>' + num(notaArchivadas) + '</b> archivadas' : '') + notaVia;
    }
    sellarFecha(fecha);
    if (r.resumen.fuera) console.warn('Fuera del municipio (no dibujados):', r.descartados);
  }

  function conDatos(lista, fecha, fuentes) {
    var arch = lista.filter(function (p) { return p.activo === 0 || p.activo === false; }).length;
    // Los portales se leen de los datos, no se escriben a mano: con un portal
    // caído el texto decía "vía Inmuebles24 y Pincali" sin un solo anuncio de Pincali.
    var vistos = {};
    lista.forEach(function (p) { if (p.fuente) vistos[p.fuente] = 1; });
    var nombres = Object.keys(vistos).map(nombrePortal);
    var via = nombres.length ? ' vía ' + nombres.join(' y ') + '.' : '.';

    // La entrada y el alcance nombran los portales que DE VERDAD entregaron en
    // esta corrida, no una lista escrita a mano. Con un portal caído, el texto
    // decía "Inmuebles24 y Pincali" sin un solo anuncio de Pincali; al revés,
    // apagar un portal obligaba a editar el HTML a mano y se olvidaba.
    var vivos = document.getElementById('portales-vivos');
    if (vivos && nombres.length) vivos.textContent = nombres.join(' y ');
    var cob = document.getElementById('cobertura-portales');
    if (cob && nombres.length) {
      cob.innerHTML = '<b>' + (nombres.length === 1 ? 'un portal' : nombres.length + ' portales') + '</b>';
    }
    // El conteo lo pone render(), ya filtrado por el guardián municipal: aquí
    // se contaban las filas crudas y la nota decía 98 donde el indicador decía
    // 97, en la misma pantalla.
    notaVia = via;
    notaArchivadas = arch;
    render(lista, 'pipeline', fecha);
  }

  dibujarZonas();

  var incrustado = window.DATOS_MONITOR && (window.DATOS_MONITOR.terrenos || []).length
    ? window.DATOS_MONITOR : null;
  // Lo más reciente que este tablero ya pintó. Antes se comparaba siempre
  // contra la fecha del archivo, así que tras el primer refresco el atajo
  // dejaba de servir y se repintaba de más.
  var ultimaVista = incrustado ? (incrustado.generado || '') : '';

  // 1) Pinta de inmediato lo que trae el archivo: la página nunca se ve vacía
  //    esperando a la red.
  if (incrustado) conDatos(incrustado.terrenos, incrustado.generado, incrustado.fuentes);

  // 2) Y en segundo plano pregunta si hay una corrida más nueva.
  function refrescar() {
    if (!API) return;
    var ctl = new AbortController(), reloj = setTimeout(function () { ctl.abort(); }, 8000);
    fetch(API + '/api/monitor-terrenos?t=' + Date.now(), { signal: ctl.signal, cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (d) {
        clearTimeout(reloj);
        if (!(d.terrenos || []).length) throw new Error('respondió sin terrenos');
        var nueva = d.ultima_actualizacion || '';
        if (nueva && ultimaVista && nueva <= ultimaVista) {
          console.info('Ya está la corrida más reciente (' + ultimaVista + ').');
          return;
        }
        console.info('Datos actualizados desde la API:', nueva);
        if (nueva) ultimaVista = nueva;
        conDatos(d.terrenos, nueva, d.fuentes);
      })
      .catch(function (e) {
        clearTimeout(reloj);
        if (incrustado) {
          console.info('No se pudo refrescar (' + e.message + '); se conservan los datos del archivo.');
        } else {
          console.info('Sin datos del pipeline (' + e.message + '); usando puntos de ejemplo.');
          render(window.PUNTOS_DEMO || [], 'ejemplo', null);
        }
      });
  }

  /* En hosting estatico no hay API que consultar: el pipeline regenera los
     archivos y ya. Sin esto, un tablero dejado abierto en una pantalla se
     quedaba con la corrida del dia que se abrio, aunque afuera hubiera datos
     nuevos. estado.json sirve de aviso: lo escribe cada corrida, pesa nada, y
     si trae una fecha mas nueva se recarga la pagina para tomar los archivos
     regenerados. */
  function revisarEstado() {
    if (location.protocol !== 'http:' && location.protocol !== 'https:') return;
    fetch('estado.json?t=' + Date.now(), { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.corrida) return;
        if (ultimaVista && d.corrida <= ultimaVista) return;
        // Una sola recarga por corrida: si los archivos aun no se regeneran o
        // vienen de cache, esto evita quedarse recargando en circulo.
        try {
          if (sessionStorage.getItem('mt-recarga') === d.corrida) return;
          sessionStorage.setItem('mt-recarga', d.corrida);
        } catch (e) { return; }
        console.info('Hay una corrida más nueva (' + d.corrida + '); recargando.');
        location.reload();
      })
      .catch(function () { /* sin estado.json no hay nada que hacer */ });
  }

  refrescar();
  revisarEstado();
  // Si alguien deja el tablero abierto en una pantalla, que no se quede viejo.
  setInterval(function () { refrescar(); revisarEstado(); }, 60 * 60 * 1000);
})();
