# Revisión semántica de tópicos y sentimiento (versión 1)

Revisión por muestreo de la calidad de los 41 tópicos y del sentimiento automático, aplicada de forma
versionada sobre las dos bases. La anotación de las muestras se hizo con un modelo de lenguaje, sin
validación humana.

Los CSV de origen permanecen inmutables. `MuseosLatam_Origen.curado` conserva la revisión derivada y
`MuseosLatam_Datamart.mart.dim_dimension_latente` recibe las etiquetas y definiciones revisadas. Los 41 códigos,
las claves sustitutas, las pertenencias y el modelo `s-bert-8bcb6303e2dc` se conservan; no se reentrenó NLP.

## Qué se revisó

- **488 casos temáticos:** hasta cuatro textos únicos por país y tópico, elegidos por hash con semilla fija
  (AR 164, MX 163, PE 161; 68.284 caracteres en total).
- **54 casos de sentimiento:** dos por combinación de país, sentimiento exportado y estado NLP, incluidas
  abstenciones y casos de idioma incierto.
- Los 41 juegos de términos y etiquetas; las definiciones nuevas incluyen alcance, inclusión, exclusión y límites.
- Las etiquetas legibles de siete dimensiones, incluidos los nombres de los 32 códigos de idioma.

## Criterio y resultado

Cada caso temático se anotó contra la **etiqueta original**: C = soporte explícito, P = referencia parcial o
genérica, N = sin soporte o con interferencia contextual. Un tópico se habilita para indicadores cuando
C/n ≥ 2/3 en total, C/n ≥ 1/2 en cada país y no hay interferencia contextual grave.

Resultado: **22 tópicos aptos para indicadores y 19 de uso restringido.** Los restringidos se conservan para
trazabilidad, pero no alimentan los indicadores temáticos. El campo `apto_analisis_tematico` habilita el tópico
completo; los cocientes describen una muestra equilibrada por país y tópico.

Sentimiento (54 casos): 27 compatibles, 7 mixtos, 1 contradicción, 12 abstenciones razonables y 7 con señal no
clasificada. Es un diagnóstico; las predicciones originales se conservan.

## Consultas

- `VER_REVISION.sql`: catálogo activo, limitaciones, cobertura y acceso a los 488 textos por join con origen.
- `mart.v_catalogo_topicos`: las 41 definiciones activas y su evaluación.
- `mart.v_dimension_satisfaccion`: baseline completo con estado y bandera de uso.
- `mart.v_dimension_satisfaccion_revisada`: solo los tópicos habilitados.
- `mart.v_cobertura_tematica`: denominadores totales, con texto, asignados, habilitados y restringidos.
- `curado.v_catalogo_vigente`: fuente editorial activa en la base de origen.

## Aplicación

La carga (`../ejecutar.ps1`) aplica y verifica esta revisión. También puede ejecutarse directamente:

```powershell
& "$env:LOCALAPPDATA\MuseosLatamSQL\venv\Scripts\python.exe" .\aplicar_revision.py --ensayo   # valida y hace rollback
& "$env:LOCALAPPDATA\MuseosLatamSQL\venv\Scripts\python.exe" .\aplicar_revision.py            # aplicación transaccional
```

La aplicación es transaccional entre ambas bases y una segunda ejecución no vuelve a actualizar filas.
`aud.revision_semantica.respaldo` conserva las filas previas de las dimensiones modificadas.

| Archivo | Función |
|---|---|
| `muestrear.py` | Reproduce la selección determinista de la muestra |
| `contenido.py`, `catalogo_curado.json`, `evaluaciones_topicos.json`, `evaluaciones_sentimiento.json` | Anotaciones y catálogo revisado, congelados por SHA-256 en `manifiesto_revision.json`. El SHA-256 del manifiesto está registrado en `aud.revision_semantica` del respaldo, por eso estos archivos se conservan byte a byte tal como se aplicaron |
| `04_revision.sql`, `05_vistas_revision.sql`, `aplicar_revision.py` | Migración versionada y vistas revisadas |
| `informar.py`, `INFORME_REVISION_IA.md` | Informe de resultados con la definición de los 41 tópicos |
| `evidencia_aplicacion.json`, `evidencia_final_revision.json` | Resultado de la aplicación y controles finales de la revisión |

Los nombres de idioma se contrastaron con la [tabla ISO 639-2 de la Library of Congress](https://www.loc.gov/standards/iso639-2/php/code_list.php).
