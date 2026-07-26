-- schema.sql — Monitor de Suelo IMPLAN Torreón
--
-- Base el esquema de Víctor, más los campos que pidió el proyecto:
--   zona              -> una de las 5 zonas del geojson (asignada por zonas.py)
--   nombre_colonia    -> texto del geocoding (Nominatim) o del propio anuncio
--   fecha_publicacion -> cuándo se publicó en el portal (no cuándo lo vimos)

CREATE TABLE IF NOT EXISTS anuncios (
    id_anuncio          TEXT PRIMARY KEY,
    fuente              TEXT NOT NULL,          -- 'inmuebles24' | 'pincali'
    titulo              TEXT NOT NULL,
    precio              REAL,
    m2                  REAL,
    precio_m2           REAL,                   -- derivado; se guarda para no recalcular en la API
    ubicacion           TEXT,
    ciudad              TEXT,                   -- municipio declarado por el portal
    estado              TEXT,                   -- entidad federativa
    nombre_colonia      TEXT,
    zona                TEXT,                   -- 'Zona 1 - ...' o NULL si quedó fuera
    zona_estado         TEXT,                   -- 'dentro' | 'borde' | 'fuera' | 'sin_coords'
    zona_motivo         TEXT,                   -- por qué se asignó así (auditoría)
    lat                 REAL,
    lon                 REAL,
    coords_origen       TEXT,                   -- 'portal' | 'nominatim' | 'centroide_zona'
    tipo_propiedad      TEXT,
    url                 TEXT,
    fecha_publicacion   DATE,
    fecha_primera_vista DATE NOT NULL,
    fecha_ultima_vista  DATE NOT NULL,
    activo              BOOLEAN DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_anuncios_activo   ON anuncios(activo);
CREATE INDEX IF NOT EXISTS idx_anuncios_zona     ON anuncios(zona);
CREATE INDEX IF NOT EXISTS idx_anuncios_fuente   ON anuncios(fuente);
CREATE INDEX IF NOT EXISTS idx_anuncios_vista    ON anuncios(fecha_ultima_vista);

-- Bitácora de corridas: sirve para saber si el scheduler está vivo y para
-- detectar el día en que una fuente se cae (0 resultados) antes de que el
-- dashboard muestre una baja falsa.
CREATE TABLE IF NOT EXISTS corridas (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio              TIMESTAMP NOT NULL,
    fin                 TIMESTAMP,
    estatus             TEXT NOT NULL,          -- 'ok' | 'error' | 'parcial'
    total_crudos        INTEGER DEFAULT 0,
    total_terrenos      INTEGER DEFAULT 0,
    nuevos              INTEGER DEFAULT 0,
    actualizados        INTEGER DEFAULT 0,
    dados_de_baja       INTEGER DEFAULT 0,
    descartados_zona    INTEGER DEFAULT 0,
    detalle             TEXT                    -- JSON con el desglose por fuente
);

-- Historial de precios: sin esto no se puede decir "bajó de precio",
-- que es justo lo que hace útil a un monitor frente a una foto del día.
CREATE TABLE IF NOT EXISTS historial_precios (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    id_anuncio  TEXT NOT NULL REFERENCES anuncios(id_anuncio),
    precio      REAL NOT NULL,
    fecha       DATE NOT NULL,
    UNIQUE(id_anuncio, precio, fecha)
);

CREATE INDEX IF NOT EXISTS idx_historial_anuncio ON historial_precios(id_anuncio);
