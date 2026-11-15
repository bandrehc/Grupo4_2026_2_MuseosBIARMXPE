# Capa BI y curaduría de lugares
- `00_decisiones_setup.sql`: tablas de decisiones (nunca se borran). `01_bi_setup.sql`: reconstruye por completo el esquema `bi` que lee el dashboard.
- `decisiones_vigentes.csv`: estado final de la curaduría. `insumos_curaduria/`: los Excel de revisión originales (solo referencia).

## Decisiones de curaduría de lugares

Flujo: Excel marcado → `cargar_decisiones.py` → tablas `bi.lugar_decision*` → `01_bi_setup.sql` reconstruye toda la capa BI → reiniciar el dashboard.

    cd bi   # desde la raíz del proyecto; con MUSEOS_ADMIN_PASS definida
    python3 cargar_decisiones.py lugares_dudosos.xlsx                      # 1) simulación: valida y muestra impacto; no escribe
    python3 cargar_decisiones.py lugares_dudosos.xlsx --aplicar --reconstruir   # 2) guarda un lote auditable y reconstruye bi.*
    # 3) reiniciar el dashboard (carga los datos al arrancar)

Requiere conexión de administrador (no la del dashboard): `MUSEOS_ADMIN_PASS` o `MUSEOS_ADMIN_PASS_FILE`.

## Semántica
- **Excluir**: el lugar sale de `bi.lugar` y de todos los agregados y vistas (sus reseñas dejan de contarse). No se borra nada de `mart.*`.
- **Reclasificar**: `bi.lugar.categoria` toma la categoría nueva (columna NUEVA CATEGORÍA; si está vacía, la sugerida). La original queda en `categoria_original`. Benchmark, percentiles y filtros usan la efectiva.
- **Mantener** (o decisión vacía): sin cambios. 'Mantener' explícito deshace un Excluir/Reclasificar previo.
- Una decisión vacía en un archivo posterior NO borra una decisión previa.

## Garantías
- Cualquier error de validación (ID inexistente o repetido, nombre que no coincide con el ID, decisión o categoría no válida, Reclasificar sin categoría) aborta todo el lote.
- Salvaguarda: si se excluiría más del 5 % de las reseñas se exige `--forzar`.
- Auditoría: `bi.decision_lote` (un registro por archivo, con sha256) y `bi.lugar_decision_hist` (cada cambio, solo inserción).
- `bi.v_control_reconciliacion` debe dar `ok = 1`: reseñas del datamart − excluidas = reseñas en BI; igual para menciones de tópico y reseñas con texto. El cargador falla si no cuadra.
- Re-ejecutar es seguro: el script 01 reconstruye completo y recargar el mismo archivo no cambia nada. Si una reconstrucción se interrumpe, basta volver a ejecutar `--reconstruir`.
- Sin decisiones, la capa BI es idéntica a la anterior (verificado con huella de las tablas).
- El usuario del dashboard (`dashly_ro`) no puede leer las tablas de decisiones; solo `bi.meta`, `bi.lugar`, etc.
- `bi.v_decision_huerfana` lista decisiones sobre lugares que ya no existen o no tienen reseñas.

## Curaduría vigente reproducible
`decisiones_vigentes.csv` es el estado final de `bi.lugar_decision` (824 Excluir, 1.138 Reclasificar, 419 Mantener; 4,18 % de las reseñas excluidas). Mismo formato que la hoja "Lugares dudosos"; el cargador acepta `.csv` o `.xlsx`:

    python3 cargar_decisiones.py decisiones_vigentes.csv                      # simulación: debe dar 0 cambios sobre la base actual
    python3 cargar_decisiones.py decisiones_vigentes.csv --aplicar --reconstruir

`deploy/init_db.py` lo carga automáticamente cuando `bi.lugar_decision` está vacía, de modo que un despliegue nuevo reproduce el mismo dashboard (el historial de lotes queda como un único lote). Los Excel originales (`lugares_dudosos.xlsx`, `exclusiones_automaticas.xlsx`) son el insumo de revisión, no el estado final: el estado final es este CSV. Tras cambiar decisiones, volver a exportarlo desde `bi.lugar_decision`.
