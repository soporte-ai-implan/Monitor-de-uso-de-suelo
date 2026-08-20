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
      GRIS = '#5C554D', MUTED = '#8A8178', REJILLA = '#EFEAE3';

  var mxn = function (v) { return '$' + Number(v).toLocaleString('es-MX', { maximumFractionDigits: 0 }); };
  var num = function (v) { return Number(v).toLocaleString('es-MX', { maximumFractionDigits: 0 }); };

  var UMBR = (window.DATOS_MONITOR && window.DATOS_MONITOR.umbrales) || {};
  var PPM_MIN = UMBR.precio_m2_min != null ? UMBR.precio_m2_min : 10;
  var PPM_MAX = UMBR.precio_m2_max != null ? UMBR.precio_m2_max : 50000;
  function ppmOk(v) { return v >= PPM_MIN && v <= PPM_MAX; }

  var SEGMENTOS = [
    { nombre: 'Lote chico', rango: 'menos de 300 m²', lo: 0, hi: 300 },
    { nombre: 'Lote medio', rango: '300 a 600 m²', lo: 300, hi: 600 },
    { nombre: 'Lote grande', rango: '600 a 1,500 m²', lo: 600, hi: 1500 },
    { nombre: 'Predio', rango: '1,500 a 10,000 m²', lo: 1500, hi: 10000 },
    { nombre: 'Rústico/ejidal', rango: 'más de 10,000 m²', lo: 10000, hi: Infinity }
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
  function segDe(p) {
    var m = Number(p.m2);
    for (var i = 0; i < SEGMENTOS.length; i++) {
      if (m >= SEGMENTOS[i].lo && m < SEGMENTOS[i].hi) return SEGMENTOS[i].nombre;
    }
    return null;
  }
  function corta(z) { return String(z || '').replace(/^Zona \d+ - /, ''); }

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
      var ref = document.querySelector('main .aviso');
      ref.parentNode.insertBefore(c, ref);
    }
    var s = c.querySelector('span');
    var v = s.textContent ? s.textContent.split(', ') : [];
    if (v.indexOf(nombre) === -1) v.push(nombre);
    s.textContent = v.join(', ');
  }

  var NOMBRE_PORTAL = { inmuebles24: 'Inmuebles24', pincali: 'Pincali', vivanuncios: 'Vivanuncios' };
  function nombrePortal(k) { return NOMBRE_PORTAL[k] || k; }

  // Un portal puede terminar la corrida "bien" y devolver cero anuncios. Si el
  // tablero no lo dice, la caída de oferta se lee como mercado: "bajó la oferta
  // de suelo" cuando en realidad se cayó un scraper. Esto lo hace visible.
  function avisarFuentes(fuentes) {
    var c = document.getElementById('aviso-fuentes');
    var caidas = [];
    Object.keys(fuentes || {}).forEach(function (k) {
      var e = (fuentes[k] || {}).estatus;
      if (e === 'vacia' || e === 'error') caidas.push(nombrePortal(k));
    });

    if (!caidas.length) { if (c) c.parentNode.removeChild(c); return; }

    if (!c) {
      c = document.createElement('div');
      c.id = 'aviso-fuentes';
      c.className = 'aviso';
      c.style.cssText = 'background:#FFF6E5;border-color:#EFD9AE;border-left-color:#C6881E;color:#7A5410';
      var ref = document.querySelector('main .aviso');
      ref.parentNode.insertBefore(c, ref);
    }
    c.innerHTML = '<b>Cobertura incompleta en esta corrida.</b> ' +
      (caidas.length === 1 ? 'El portal ' : 'Los portales ') + caidas.join(' y ') +
      (caidas.length === 1 ? ' no devolvió' : ' no devolvieron') + ' anuncios. ' +
      'Las cifras de abajo cubren solo el resto de las fuentes; ' +
      'la oferta de ese portal <b>no se dio por vendida</b>, quedó en pausa hasta que vuelva a responder.';
  }

  /* ================= mapa ================= */
  var mapa = L.map('mapa', { scrollWheelZoom: false, zoomControl: true });
  L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
    { maxZoom: 19, attribution: '&copy; OpenStreetMap &copy; CARTO' }).addTo(mapa);

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

  function dibujarZonas() {
    capaZonas.clearLayers(); capaEtq.clearLayers();

    if (window.TORREON_MUNICIPIO) {
      L.geoJSON(window.TORREON_MUNICIPIO, {
        style: { color: MUTED, weight: 1.6, opacity: .65, dashArray: '5,4', fill: false }
      }).addTo(capaZonas);
    }

    (window.TORREON_ZONAS.features || []).forEach(function (f) {
      var n = GeoZonas.nombreDe(f), col = GeoZonas.COLOR_ZONA[n] || MUTED;
      L.geoJSON(f, { style: { color: col, weight: 2.6, opacity: .9, fill: false,
                              lineJoin: 'round', lineCap: 'round' } }).addTo(capaZonas);
      // El NOMBRE es lo que identifica la zona; el color solo refuerza.
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
      L.heatLayer(pts.map(function (p) {
        var x = ppm(p);
        return [p.lat, p.lon, (x > 0 && tope > 0) ? Math.min(1, Math.max(.3, x / tope)) : .5];
      }), { radius: 34, blur: 26, maxZoom: 15, minOpacity: .32,
            gradient: { .2: '#c9d9ea', .4: '#7fa8cf', .6: '#e9a26f', .8: NARANJA, 1: '#b5341a' } }).addTo(capaCalor);
    });
  }

  function dibujarPuntos(pts) {
    capaPuntos.clearLayers();
    pts.forEach(function (p) {
      var col = p._color || MUTED, arch = p.activo === 0 || p.activo === false;
      var icono = L.divIcon({
        className: 'mk',
        html: '<div style="position:relative;width:14px;height:14px">' +
              (arch ? '' : '<div class="anillo" style="background:' + col + '"></div>' +
                           '<div class="anillo" style="background:' + col + ';animation-delay:900ms"></div>') +
              '<div class="nucleo" style="background:' + col + (arch ? ';opacity:.45' : '') + '"></div></div>',
        iconSize: [14, 14], iconAnchor: [7, 7]
      });
      var v = ppm(p), meta = [];
      if (p.m2) meta.push(num(p.m2) + ' m²');
      if (p.precio) meta.push(mxn(p.precio) + ' total');
      if (p.nombre_colonia) meta.unshift(p.nombre_colonia);
      var dias = diasEnMercado(p);
      var portal = p.fuente === 'inmuebles24' ? 'Inmuebles24' : p.fuente === 'pincali' ? 'Pincali' : (p.fuente || '—');

      var globo = '<span class="z" style="color:' + col + '">' + (p.zona || 'Sin zona') + '</span>' +
        '<div class="p">' + (v && ppmOk(v) ? mxn(v) + ' /m²' : (p.precio ? mxn(p.precio) : 'Precio no publicado')) + '</div>' +
        '<div class="m">' + (meta.join(' · ') || 'Sin datos de superficie') + '</div>' +
        '<div class="m">' + portal + (dias != null ? ' · ' + dias + ' días publicado' : '') + '</div>' +
        (p.ubicacion_precisa === false ? '<div class="h">Ubicación aproximada</div>' : '') +
        (arch ? '<div class="h">Oferta archivada: ya no aparece en el portal</div>' : '') +
        (p.url ? '<div class="h">Clic para abrir el anuncio</div>' : '');

      var ficha = '<div class="emg"><div class="t">' +
        '<span class="z" style="color:' + col + '">' + (p.zona || 'Sin zona') + '</span>' +
        '<span class="chip">' + portal + '</span></div>' +
        (p.nombre_colonia ? '<div style="font-weight:600;font-size:.85rem;margin-bottom:5px">' + p.nombre_colonia + '</div>' : '') +
        '<div class="pr">' + (v && ppmOk(v) ? mxn(v) + ' /m²' : (p.precio ? mxn(p.precio) : 'Precio no publicado')) + '</div>' +
        '<div class="me">' + (meta.join(' · ') || 'Sin superficie') +
        (p.fecha_publicacion ? '<br>Publicado: ' + p.fecha_publicacion + (dias != null ? ' (' + dias + ' días)' : '') : '') + '</div>' +
        (p.url ? '<a class="btn" href="' + p.url + '" target="_blank" rel="noopener noreferrer">Ver anuncio ↗</a>'
               : '<span class="sutil">Sin liga al anuncio</span>') + '</div>';

      L.marker([p.lat, p.lon], { icon: icono, riseOnHover: true })
        .bindTooltip(globo, { className: 'globo', direction: 'top', offset: [0, -10], sticky: true, opacity: 1 })
        .bindPopup(ficha).addTo(capaPuntos);
    });
  }

  function dibujarLeyenda() {
    var c = document.getElementById('leyenda');
    c.innerHTML = '';
    if (window.TORREON_MUNICIPIO) {
      var m = document.createElement('span');
      m.className = 'it-ley';
      m.innerHTML = '<span class="trazo" style="border-top:2px dashed ' + MUTED + '"></span>Límite municipal';
      c.appendChild(m);
    }
    var nombres = (window.TORREON_ZONAS.features || []).map(GeoZonas.nombreDe);
    nombres.push(GeoZonas.ZONA_PERIFERIA);
    nombres.forEach(function (n) {
      var col = GeoZonas.COLOR_ZONA[n] || MUTED, k = conteoZona[n] || 0;
      var e = document.createElement('span');
      e.className = 'it-ley';
      e.innerHTML = '<span class="trazo" style="border-top-color:' + col + '"></span>' + corta(n) + ' <b>(' + k + ')</b>';
      c.appendChild(e);
    });
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
      res.fuera ? (res.fuera + ' descartado(s) fuera del municipio')
                : (np === 1 ? 'en 1 portal con datos hoy' : 'en ' + np + ' portales monitoreados');

    var todos = pts.map(ppm).filter(function (v) { return v > 0; });
    var buenos = todos.filter(ppmOk), atip = todos.length - buenos.length;
    document.getElementById('k-precio').textContent = buenos.length ? mxn(mediana(buenos)) : '—';
    document.getElementById('k-precio-pie').textContent =
      atip ? 'por m² · ' + atip + ' atípico(s) excluido(s)' : 'por m² de terreno';

    var m2 = pts.map(function (p) { return Number(p.m2); }).filter(function (v) { return v > 0; });
    document.getElementById('k-m2').textContent = m2.length ? num(mediana(m2)) : '—';

    var ds = pts.map(diasEnMercado).filter(function (v) { return v != null; });
    document.getElementById('k-dias').textContent = ds.length ? num(mediana(ds)) : '—';
    var viejos = ds.filter(function (d) { return d > 180; }).length;
    document.getElementById('k-dias-pie').textContent = viejos
      ? viejos + ' llevan más de 6 meses sin venderse'
      : 'mediana de la oferta activa';
  }

  function pintarDiagnostico(r) {
    var celdas = [
      { t: 'Dentro de una zona urbana', n: r.dentro, c: 'bien' },
      { t: 'Absorbidos por la zona más cercana', n: r.borde, c: 'ojo' },
      { t: 'En la Periferia Sur', n: r.periferia || 0, c: 'ojo' },
      { t: 'Descartados: fuera del municipio', n: r.fuera, c: 'mal' },
      { t: 'Sin coordenadas', n: r.sinCoords, c: 'mal' }
    ];
    var c = document.getElementById('diagnostico');
    c.innerHTML = '';
    celdas.forEach(function (x) {
      var d = document.createElement('div');
      d.className = 'd-cel ' + x.c;
      d.innerHTML = '<div class="n">' + x.n + '</div><div class="t">' + x.t + '</div>';
      c.appendChild(d);
    });
  }

  function pintarSegmentos(pts) {
    var c = document.getElementById('segmentos');
    c.innerHTML = '';
    SEGMENTOS.forEach(function (s) {
      var v = pts.filter(function (p) {
        var m = Number(p.m2);
        return m >= s.lo && m < s.hi && ppmOk(ppm(p));
      }).map(ppm);
      var pocos = v.length > 0 && v.length < 10;
      var d = document.createElement('div');
      d.className = 'seg' + (pocos ? ' pocos' : '');
      d.innerHTML = '<div class="n1">' + s.nombre + '</div><div class="n2">' + s.rango + '</div>' +
        '<div class="n3">' + (v.length ? mxn(mediana(v)) : '—') + '</div>' +
        '<div class="n4">mediana por m²</div>' +
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

  function pintarGraficas(pts) {
    if (!window.Chart) { console.info('Chart.js no cargó; se omiten las gráficas.'); return; }
    Chart.defaults.font.family = "'Libre Franklin', system-ui, sans-serif";
    Chart.defaults.color = GRIS;

    // 1) precio mediano por zona
    var nz = (window.TORREON_ZONAS.features || []).map(GeoZonas.nombreDe).concat([GeoZonas.ZONA_PERIFERIA]);
    var et = [], va = [];
    nz.forEach(function (z) {
      var v = pts.filter(function (p) { return p.zona === z && ppmOk(ppm(p)); }).map(ppm);
      if (!v.length) return;
      et.push(corta(z)); va.push(Math.round(mediana(v)));
    });
    dibujar('gZonas', {
      type: 'bar', plugins: [etiquetas],
      data: { labels: et, datasets: [{ data: va, backgroundColor: AZUL, borderRadius: 4, maxBarThickness: 46 }] },
      options: opciones({
        layout: { padding: { top: 18 } },
        plugins: { legend: { display: false }, etiquetas: { fmt: mxn },
                   tooltip: { callbacks: { label: function (c) { return mxn(c.parsed.y) + ' /m² (mediana)'; } } } },
        scales: { x: { grid: { display: false }, ticks: { color: GRIS, font: { size: 10 } } },
                  y: { display: false, beginAtZero: true } }
      })
    });

    // 2) distribución por tamaño
    var cnt = SEGMENTOS.map(function (s) {
      return pts.filter(function (p) { var m = Number(p.m2); return m >= s.lo && m < s.hi; }).length;
    });
    dibujar('gTamano', {
      type: 'bar', plugins: [etiquetas],
      data: { labels: SEGMENTOS.map(function (s) { return s.nombre; }),
              datasets: [{ data: cnt, backgroundColor: AZUL, borderRadius: 4, maxBarThickness: 46 }] },
      options: opciones({
        layout: { padding: { top: 18 } },
        plugins: { legend: { display: false }, etiquetas: { fmt: num },
                   tooltip: { callbacks: { label: function (c) { return c.parsed.y + ' terrenos · ' + SEGMENTOS[c.dataIndex].rango; } } } },
        scales: { x: { grid: { display: false }, ticks: { color: GRIS, font: { size: 10 } } },
                  y: { display: false, beginAtZero: true } }
      })
    });

    // 3) antigüedad — lo viejo en naranja: es el hallazgo, no decoración
    var pm = {};
    pts.forEach(function (p) { if (p.fecha_publicacion) { var m = String(p.fecha_publicacion).slice(0, 7); pm[m] = (pm[m] || 0) + 1; } });
    var meses = Object.keys(pm).sort(), MN = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
    var corte = new Date(); corte.setMonth(corte.getMonth() - 6);
    var claveCorte = corte.toISOString().slice(0, 7);
    dibujar('gAntiguedad', {
      type: 'bar', plugins: [etiquetas],
      data: {
        labels: meses.map(function (m) { var p = m.split('-'); return MN[+p[1] - 1] + ' ' + p[0].slice(2); }),
        datasets: [{ data: meses.map(function (m) { return pm[m]; }),
                     backgroundColor: meses.map(function (m) { return m < claveCorte ? NARANJA : '#C9BFB2'; }),
                     borderRadius: 4, maxBarThickness: 40 }]
      },
      options: opciones({
        layout: { padding: { top: 18 } },
        plugins: { legend: { display: false }, etiquetas: { fmt: num },
                   tooltip: { callbacks: { label: function (c) {
                     return c.parsed.y + ' terrenos publicados ese mes, aún en venta'; } } } },
        scales: { x: { grid: { display: false }, ticks: { color: GRIS, font: { size: 10 } } },
                  y: { display: false, beginAtZero: true } }
      })
    });

    // 4) por portal
    var pp = {};
    pts.forEach(function (p) { var f = p.fuente || 'sin dato'; pp[f] = (pp[f] || 0) + 1; });
    var ks = Object.keys(pp).sort(function (a, b) { return pp[b] - pp[a]; });
    dibujar('gPortales', {
      type: 'bar', plugins: [etiquetas],
      data: { labels: ks.map(function (k) { return k === 'inmuebles24' ? 'Inmuebles24' : k === 'pincali' ? 'Pincali' : k; }),
              datasets: [{ data: ks.map(function (k) { return pp[k]; }), backgroundColor: AZUL,
                           borderRadius: 4, maxBarThickness: 34 }] },
      options: opciones({
        indexAxis: 'y', layout: { padding: { right: 44 } },
        plugins: { legend: { display: false }, etiquetas: { fmt: num, horizontal: true } },
        scales: { x: { display: false, beginAtZero: true },
                  y: { grid: { display: false }, border: { display: false }, ticks: { color: GRIS, font: { size: 11 } } } }
      })
    });
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
    });
  }

  function conectarTabla() {
    [].forEach.call(document.querySelectorAll('#tabla th[data-col]'), function (th) {
      th.addEventListener('click', function () {
        var c = th.dataset.col;
        if (orden.col === c) orden.asc = !orden.asc;
        else { orden.col = c; orden.asc = (c === 'nombre_colonia' || c === 'zona' || c === 'fuente'); }
        pagina = 1; pintarTabla();
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
    conteoZona = {};
    r.dibujables.forEach(function (p) { if (p.zona) conteoZona[p.zona] = (conteoZona[p.zona] || 0) + 1; });

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

    document.getElementById('sello-fecha').textContent = fechaLegible(fecha);
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
    document.getElementById('nota-datos').innerHTML =
      'Datos <b>reales</b> del pipeline: ' + (lista.length - arch) + ' ofertas activas' +
      (arch ? ' y ' + arch + ' archivadas' : '') + via;
    intentar('aviso de fuentes', function () { avisarFuentes(fuentes); });
    render(lista, 'pipeline', fecha);
  }

  dibujarZonas();

  var incrustado = window.DATOS_MONITOR && (window.DATOS_MONITOR.terrenos || []).length
    ? window.DATOS_MONITOR : null;

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
        var actual = incrustado ? (incrustado.generado || '') : '';
        if (incrustado && nueva && actual && nueva <= actual) {
          console.info('El archivo ya tiene la corrida más reciente (' + actual + ').');
          return;
        }
        console.info('Datos actualizados desde la API:', nueva);
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

  refrescar();
  // Si alguien deja el tablero abierto en una pantalla, que no se quede viejo.
  setInterval(refrescar, 60 * 60 * 1000);
})();
