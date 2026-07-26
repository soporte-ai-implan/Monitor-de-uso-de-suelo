# database.py

Guarda la corrida, detecta altas y bajas, y aplica los filtros de código.

## Los dos blindajes contra bajas falsas

Un dashboard que dice "se vendieron 84 terrenos esta semana" porque el scraper
tronó es **peor** que un dashboard sin actualizar. De ahí estos dos candados.

### Blindaje 1 — lista vacía

El código original armaba el UPDATE así:

```python
placeholders = ",".join("?" * len(ids_vistos_hoy))   # con lista vacía -> ""
conn.execute(f"UPDATE anuncios SET activo = 0 WHERE id_anuncio NOT IN ({placeholders})", ids_vistos_hoy)
```

Con `ids_vistos_hoy` vacío queda `WHERE id_anuncio NOT IN ()`, que no empata con
nada y por lo tanto **marca la tabla entera como inactiva**. Un solo fallo del
scraper vaciaba el monitor.

Ahora, si la lista llega vacía se regresa temprano sin ejecutar ningún UPDATE, y
el resultado incluye un `aviso` explícito. `main.py` además cierra la corrida como
`error`, no como `ok`.

### Blindaje 2 — bajas solo en fuentes que respondieron

Extensión del mismo problema, un nivel más arriba. Si Pincali funciona e
Inmuebles24 truena, los anuncios de Inmuebles24 no aparecen en la corrida — pero
eso **no significa que se vendieron**, significa que no sabemos nada de ellos hoy.

El UPDATE está acotado a las fuentes que respondieron bien:

```sql
UPDATE anuncios SET activo = 0
 WHERE activo = 1
   AND fuente IN (:fuentes_ok)      -- solo donde sí tenemos información
   AND id_anuncio NOT IN (:ids_vistos)
```

## Filtros del lado del código

No se confía en el filtro del Actor. `es_terreno()` revisa `tipo_propiedad` y
`titulo` contra dos listas:

- **Sí:** terreno, lote, predio, parcela, solar, land
- **No:** casa, departamento, bodega, local, oficina, edificio, nave industrial…

El orden importa: `"Casa con terreno amplio"` contiene "terreno" pero **no** es
oferta de suelo, así que las palabras de exclusión ganan.

`es_venta()` descarta rentas. Si el portal no declara operación se asume venta,
porque la URL de búsqueda ya filtra por eso.

`filtrar()` además descarta lo que quedó `zona_estado = 'fuera'` (otro municipio
o lejos de toda zona) y lo que no trae precio, y regresa el conteo por motivo
para que el descarte quede auditable en la bitácora.

## Tablas más allá de `anuncios`

- **`corridas`** — bitácora de cada ejecución: cuántos crudos, cuántos válidos,
  altas, bajas, y un JSON con el desglose por fuente. Sirve para saber si el
  scheduler está vivo y para detectar el día en que una fuente se cayó **antes**
  de que el dashboard muestre una baja falsa.
- **`historial_precios`** — un renglón por (anuncio, precio, fecha). Sin esto no
  se puede decir "bajó de precio", que es justo lo que hace útil a un monitor
  frente a una foto del día.

## Verificación

```bash
python tests/test_database.py
```

Prueba los dos blindajes, la detección de cambios de precio, el historial y los
filtros de tipo y operación. Usa una base temporal, no toca `terrenos.db`.
