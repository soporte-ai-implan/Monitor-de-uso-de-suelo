/*
 * geo.js — asignacion de zona por geometria real, no por rectangulo.
 *
 * Reemplaza el `enLimite()` del diseno original, que recortaba a un bbox
 * (lat 25.483..25.579, lon -103.463..-103.356) y por eso empujaba puntos
 * legitimos hasta el borde: las zonas reales llegan a lat 25.6257 al norte,
 * lon -103.4944 al oeste y lon -103.3057 al este, o sea el bbox recortaba
 * ~5.2 km del norte, ~3.1 km del oeste y ~5.0 km del este del municipio.
 *
 * Regla de oro: nunca movemos las coordenadas de un anuncio real. Si un punto
 * cae fuera de las 5 zonas lo etiquetamos, no lo reubicamos.
 */
(function (global) {
  'use strict';

  // Colores por zona, tomados de la paleta del diseno aprobado.
  var COLOR_ZONA = {
    'Zona 1 - Poniente y Centro Histórico': '#5B4B8A',
    'Zona 2 - Zona Norte': '#E95026',
    'Zona 3 - Centro-Norte': '#15467A',
    'Zona 4 - Oriente': '#C9881E',
    'Zona 5 - Sur Oriente': '#1A7A47'
  };

  // Un punto fuera de todas las zonas pero a menos de esto se considera borde
  // de la mancha urbana (ejidos, rustico) y se asigna a la zona mas cercana.
  //
  // Por que la distancia NO puede ser el guardian principal: Torreon y Gomez
  // Palacio son contiguas, separadas por el Rio Nazas. Medido contra este
  // mismo geojson:
  //     Gomez Palacio (col. Filadelfia)  -> 0.25 km del borde de Zona 1
  //     Torreon zona industrial oriente  -> 2.29 km  (legitimo)
  // Hay puntos de Durango MAS CERCA que puntos validos de Torreon: los rangos
  // se traslapan y ningun umbral los separa. Por eso el guardian principal es
  // el nombre del municipio en el texto del anuncio, no la geometria.
  //
  // Con ese guardian puesto, la distancia si puede hacer su verdadero trabajo
  // (alcanzar la periferia rural que las zonas SEPOMEX no cubren) y se subio
  // de 1.5 a 3.0 km. Sobre 20 anuncios reales eso recupera predios legitimos
  // a ~2 km sin dejar entrar nada de Durango.
  var TOLERANCIA_KM = 3.0;

  // Municipios vecinos. Si alguno aparece por su nombre en el texto de
  // ubicacion, el anuncio NO es de Torreon y se descarta.
  //
  // La regla mira TODO el texto, no un solo campo: Inmuebles24 recorre su
  // jerarquia de ubicacion segun el anuncio. Medido sobre 20 anuncios reales,
  // 14 mandaban city='Coahuila' (el estado) y neighborhood='Torreón' (el
  // municipio). Leer solo `city` los rechazaba a todos, y 11 de ellos caian
  // dentro o al borde de una zona real.
  var MUNICIPIOS_VECINOS = [
    'gomez palacio', 'lerdo',
    'matamoros', 'viesca', 'san pedro',
    'francisco i madero', 'fco i madero',
    // Torreon es Coahuila: si dice Durango, no es de aqui.
    'durango'
  ];

  var MUNICIPIO_PROPIO = 'torreon';

  var KM_POR_GRADO_LAT = 111.32;

  function kmPorGradoLon(lat) {
    return KM_POR_GRADO_LAT * Math.cos((lat * Math.PI) / 180);
  }

  /* ---------- primitivas de geometria ---------- */

  // Devuelve [[exterior, [huecos...]], ...] en coordenadas [lon, lat].
  function anillosDe(geom) {
    if (!geom) return [];
    if (geom.type === 'Polygon') {
      return [[geom.coordinates[0], geom.coordinates.slice(1)]];
    }
    if (geom.type === 'MultiPolygon') {
      return geom.coordinates.map(function (poly) {
        return [poly[0], poly.slice(1)];
      });
    }
    return [];
  }

  // Ray casting. `ring` es [[lon, lat], ...].
  function enAnillo(lon, lat, ring) {
    var dentro = false;
    var n = ring.length;
    for (var i = 0, j = n - 1; i < n; j = i++) {
      var xi = ring[i][0], yi = ring[i][1];
      var xj = ring[j][0], yj = ring[j][1];
      if ((yi > lat) !== (yj > lat) &&
          lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) {
        dentro = !dentro;
      }
    }
    return dentro;
  }

  // Dentro del exterior y fuera de los huecos.
  function enGeometria(lon, lat, geom) {
    var anillos = anillosDe(geom);
    for (var a = 0; a < anillos.length; a++) {
      if (!enAnillo(lon, lat, anillos[a][0])) continue;
      var huecos = anillos[a][1];
      var enHueco = false;
      for (var h = 0; h < huecos.length; h++) {
        if (enAnillo(lon, lat, huecos[h])) { enHueco = true; break; }
      }
      if (!enHueco) return true;
    }
    return false;
  }

  // Distancia en km de un punto al segmento a-b (proyeccion plana local).
  function distanciaASegmento(lon, lat, a, b) {
    var kx = kmPorGradoLon(lat);
    var px = (lon - a[0]) * kx,        py = (lat - a[1]) * KM_POR_GRADO_LAT;
    var bx = (b[0] - a[0]) * kx,       by = (b[1] - a[1]) * KM_POR_GRADO_LAT;
    var largo2 = bx * bx + by * by;
    var t = largo2 === 0 ? 0 : Math.max(0, Math.min(1, (px * bx + py * by) / largo2));
    var dx = px - t * bx, dy = py - t * by;
    return Math.sqrt(dx * dx + dy * dy);
  }

  // Distancia en km al borde de la geometria (0 si esta dentro).
  function distanciaAGeometria(lon, lat, geom) {
    if (enGeometria(lon, lat, geom)) return 0;
    var min = Infinity;
    var anillos = anillosDe(geom);
    for (var a = 0; a < anillos.length; a++) {
      var todos = [anillos[a][0]].concat(anillos[a][1]);
      for (var r = 0; r < todos.length; r++) {
        var ring = todos[r];
        for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
          var d = distanciaASegmento(lon, lat, ring[j], ring[i]);
          if (d < min) min = d;
        }
      }
    }
    return min;
  }

  /* ---------- API publica ---------- */

  function features(geojson) {
    return (geojson && geojson.features) || [];
  }

  function nombreDe(feature) {
    return (feature.properties && feature.properties.zona) || '(sin nombre)';
  }

  // "Gómez Palacio" -> "gomez palacio"
  function normalizar(txt) {
    if (!txt) return '';
    var s = String(txt).normalize('NFD');
    var out = '';
    for (var i = 0; i < s.length; i++) {
      var code = s.charCodeAt(i);
      // saltar marcas diacriticas combinantes (U+0300..U+036F)
      if (code >= 768 && code <= 879) continue;
      out += s.charAt(i);
    }
    return out.toLowerCase().trim();
  }

  // Todos los campos con pistas de ubicacion de un anuncio, en un solo lugar.
  function textosDe(a) {
    return [a.ciudad || a.city, a.nombre_colonia, a.ubicacion, a.titulo];
  }

  /**
   * Guardian de municipio. Mira TODO el texto de ubicacion, no un solo campo.
   * Regresa true (es de Torreon), false (es de otro municipio) o null (no hay
   * forma de saberlo; que decida la geometria).
   *
   * Se descarta solo si aparece un municipio VECINO con nombre propio. Un
   * vecino nombrado gana sobre la mencion de Torreon, porque "a 10 min de
   * Torreon, en Gomez Palacio" es un anuncio de Gomez Palacio.
   */
  function municipioValido(textos) {
    var lista = Array.isArray(textos) ? textos : [textos];
    var blob = normalizar(lista.filter(Boolean).join(' | '));
    if (!blob) return null;
    for (var i = 0; i < MUNICIPIOS_VECINOS.length; i++) {
      if (blob.indexOf(MUNICIPIOS_VECINOS[i]) !== -1) return false;
    }
    if (blob.indexOf(MUNICIPIO_PROPIO) !== -1) return true;
    return null;
  }

  /**
   * Clasifica un punto contra las zonas reales.
   * `ciudad` es opcional: si el anuncio trae municipio y NO es Torreon, se
   * descarta sin importar la geometria (asi se frena Gomez Palacio / Lerdo).
   *
   * Regresa { zona, color, estado, distanciaKm, motivo }.
   *   estado 'dentro' -> point-in-polygon exacto
   *   estado 'borde'  -> fuera de todo pero a <= TOLERANCIA_KM, se asigna la mas cercana
   *   estado 'fuera'  -> otro municipio; NO se dibuja en el mapa
   */
  function clasificar(lon, lat, geojson, textos) {
    var fs = features(geojson);

    // Guardian de municipio antes que nada.
    if (municipioValido(textos) === false) {
      var lista = Array.isArray(textos) ? textos : [textos];
      var blob = normalizar(lista.filter(Boolean).join(' '));
      var vecino = 'otro municipio';
      for (var v = 0; v < MUNICIPIOS_VECINOS.length; v++) {
        if (blob.indexOf(MUNICIPIOS_VECINOS[v]) !== -1) { vecino = MUNICIPIOS_VECINOS[v]; break; }
      }
      return {
        zona: null, color: '#8A8178', estado: 'fuera', distanciaKm: null,
        motivo: 'el anuncio menciona ' + vecino + ', no Torreón'
      };
    }

    for (var i = 0; i < fs.length; i++) {
      if (enGeometria(lon, lat, fs[i].geometry)) {
        var n = nombreDe(fs[i]);
        return {
          zona: n, color: COLOR_ZONA[n] || '#8A8178',
          estado: 'dentro', distanciaKm: 0, motivo: 'point-in-polygon'
        };
      }
    }

    var mejor = null, mejorD = Infinity;
    for (var k = 0; k < fs.length; k++) {
      var d = distanciaAGeometria(lon, lat, fs[k].geometry);
      if (d < mejorD) { mejorD = d; mejor = fs[k]; }
    }

    if (mejor && mejorD <= TOLERANCIA_KM) {
      var nb = nombreDe(mejor);
      return {
        zona: nb, color: COLOR_ZONA[nb] || '#8A8178',
        estado: 'borde', distanciaKm: mejorD,
        motivo: 'zona más cercana (' + mejorD.toFixed(1) + ' km)'
      };
    }

    return {
      zona: null, color: '#8A8178', estado: 'fuera', distanciaKm: mejorD,
      motivo: 'a ' + mejorD.toFixed(1) + ' km de cualquier zona'
    };
  }

  /**
   * Clasifica una lista de anuncios. Espera objetos con lat y lon (o lng).
   * Regresa { dibujables, descartados, resumen }.
   */
  function clasificarLista(anuncios, geojson) {
    var dibujables = [], descartados = [];
    var resumen = {
      dentro: 0, borde: 0, fuera: 0, sinCoords: 0,
      otroMunicipio: 0, total: anuncios.length
    };

    anuncios.forEach(function (a) {
      var lat = a.lat, lon = (a.lon !== undefined ? a.lon : a.lng);
      if (typeof lat !== 'number' || typeof lon !== 'number' || isNaN(lat) || isNaN(lon)) {
        resumen.sinCoords++;
        descartados.push(Object.assign({}, a, { _estado: 'sin_coords' }));
        return;
      }
      var c = clasificar(lon, lat, geojson, textosDe(a));
      resumen[c.estado]++;
      if (c.motivo && c.motivo.indexOf('el anuncio menciona') === 0) resumen.otroMunicipio++;
      var enriquecido = Object.assign({}, a, {
        lat: lat,
        lon: lon,
        zona: c.zona || a.zona || null,
        _color: c.color,
        _estado: c.estado,
        _distanciaKm: c.distanciaKm,
        _motivo: c.motivo
      });
      if (c.estado === 'fuera') descartados.push(enriquecido);
      else dibujables.push(enriquecido);
    });

    return { dibujables: dibujables, descartados: descartados, resumen: resumen };
  }

  // Bounds [[latMin, lonMin], [latMax, lonMax]] de todas las zonas, para fitBounds.
  function boundsDe(geojson) {
    var latMin = Infinity, latMax = -Infinity, lonMin = Infinity, lonMax = -Infinity;
    features(geojson).forEach(function (f) {
      anillosDe(f.geometry).forEach(function (par) {
        par[0].forEach(function (c) {
          if (c[1] < latMin) latMin = c[1];
          if (c[1] > latMax) latMax = c[1];
          if (c[0] < lonMin) lonMin = c[0];
          if (c[0] > lonMax) lonMax = c[0];
        });
      });
    });
    return [[latMin, lonMin], [latMax, lonMax]];
  }

  global.GeoZonas = {
    COLOR_ZONA: COLOR_ZONA,
    TOLERANCIA_KM: TOLERANCIA_KM,
    MUNICIPIOS_VECINOS: MUNICIPIOS_VECINOS,
    normalizar: normalizar,
    municipioValido: municipioValido,
    textosDe: textosDe,
    enGeometria: enGeometria,
    distanciaAGeometria: distanciaAGeometria,
    clasificar: clasificar,
    clasificarLista: clasificarLista,
    boundsDe: boundsDe,
    nombreDe: nombreDe
  };
})(typeof window !== 'undefined' ? window : globalThis);
