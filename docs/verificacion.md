# Verificación de la entrega

Pruebas ejecutadas sobre el contenido de este repositorio y el respaldo del Release v1.0, restaurado en
SQL Server 2022 con Python 3.12 y las versiones de `requirements.txt` (14 de noviembre de 2026).

| Prueba | Comando | Resultado |
|---|---|---|
| Integridad del respaldo | `Get-FileHash` / `sha256sum -c data/SHA256SUMS.txt` | SHA-256 `5392c86a…2334` coincide |
| Verificación del respaldo | `RESTORE VERIFYONLY … WITH CHECKSUM` | OK (datos 968 MB + log 264 MB) |
| Inicialización | `python deploy/init_db.py` | Restauración, usuario de solo lectura y capa BI; reconciliación datamart 1.143.877 / BI 1.096.044 → **OK** |
| Reconciliación de KPI | `python tests/test_kpis.py` | **16/16 pruebas OK** |
| Métricas sin SQL | `python -m unittest discover -s tests -p test_metricas.py` | **7/7 OK** |
| Controles del datamart | `python scripts/verificar_entrega.py` | **SQL_VERIFICADO**, 9/9 controles → [`evidencias/control_entrega.json`](evidencias/control_entrega.json) |
| Dashboard | Las 6 pestañas, 7 combinaciones de filtros, Mi museo, Reseñas y exportaciones CSV | Todas responden correctamente |

## Qué comprueban las 16 pruebas de KPI

1. Reconciliación global: datamart − excluidas = BI, sin decisiones huérfanas.
2. Agregado lugar × año recalculado desde `mart`: mismas claves (24.656 filas) y mismos valores en las 8 métricas.
3. KPI del dashboard, calculados con el código de `app.py`, frente a SQL directo en tres combinaciones de filtros.
4. Menciones por país × tópico (118.092) y tópico × sentimiento.
5. Benchmark: mismos 4.172 lugares, rating suavizado y percentil con diferencia < 1e-6.
6. Reseñas individuales: 598.502 con texto y texto idéntico al del datamart.
7. Curaduría: 824 lugares excluidos ausentes y 1.138 reclasificados con su categoría efectiva.

## Cifras de referencia

Con el filtro por defecto (Argentina + México + Perú · museo · 2017–2026), Panorama muestra
**810.320 reseñas · 4,54 ★ · 9,3 % negativo · 55 % con texto · 2.834 lugares**.

El mapa base del dashboard requiere conexión a internet en el navegador.
