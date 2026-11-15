# Capa analítica y decisiones de gestión

## Modelo relacional agregado: implementación ROLAP

El análisis multidimensional se implementa de forma relacional (ROLAP): agregados reutilizables en el
esquema `bi` sobre dimensiones conformadas del datamart. No se utiliza un cubo SSAS; las operaciones OLAP
se resuelven con consultas sobre los agregados y se exponen en el dashboard.

| Operación | Implementación en el dashboard |
|---|---|
| Slice | Seleccionar un país (p. ej., Perú) y mantener el resto de dimensiones. |
| Dice | Elegir dos países, la categoría museo y los años 2020–2025. |
| Roll-up | De lugar a región y país: sumar numeradores/denominadores y después dividir. |
| Drill-down | Desde el panorama a una institución (Mi museo) y a sus reseñas individuales. |
| Pivot | Matrices país × año o país × tópico en mapas de calor. |

La jerarquía geográfica es país → nivel 1 → nivel 2 → nivel 3 (solo donde existe) → lugar.
El tiempo admite año y, en el datamart, mes cuando se conoce; el dashboard usa años por la precisión
predominante. Categoría efectiva, sentimiento y tópico son otros ejes. Reseñas y sumas son aditivas
en sus granos; ratings y porcentajes se recalculan; la reputación pública no se suma como asistencia.

## Universo analítico

El datamart contiene 1.143.877 reseñas. La capa BI consume 1.096.044 tras excluir 47.833 (4,18 %)
correspondientes a lugares fuera de alcance. Los 824 lugares excluidos, 1.138 reclasificados y 419
mantenidos son decisiones de curaduría del equipo.
La reconciliación entre ambos universos se controla con `bi.v_control_reconciliacion`.

El 37,47 % de cobertura temática corresponde a los 41 tópicos sobre las reseñas con texto antes de la
curaduría; la cobertura de los 22 tópicos habilitados se calcula en el dashboard para cada filtro.

El encabezado del dashboard muestra el universo completo de la capa BI (1,10 M de reseñas) y las tarjetas
muestran el subconjunto del filtro activo (por defecto, 810.320 reseñas de museos en 2017–2026).

## Propuesta de mejora: piloto de tres acciones

Plazos y horas son estimaciones de esfuerzo; el costo de personal se calcula como horas × tarifa
acordada con la institución, en moneda local.

| Acción propuesta | Responsable propuesto | Plazo / esfuerzo | Indicador de proceso y verificación |
|---|---|---|---|
| Revisar comentarios de ratings bajos y negativos de una institución elegida por comparabilidad, no solo por ranking | Coordinación de atención + un analista | Semanas 1–2; 12 horas de revisión y 4 de consolidación | Revisar 100 casos reales estratificados; registrar tema, evidencia y decisión. Si no hay 100, revisar todos y declarar n. |
| Validar etiquetas de temas antes de intervenir por NLP | Dos revisores independientes | Semanas 1–3; 8 horas por revisor y 4 de conciliación | Muestra por país, tema/outlier y confianza; medir acuerdo y errores, sin usar el rating como etiqueta de sentimiento. |
| Pilotar una mejora de comunicación de horarios/precios solo si los comentarios revisados la sustentan | Responsable de comunicación del museo | Semanas 3–6; 8 horas de diseño + 1 hora semanal de seguimiento durante cuatro semanas | Registrar canales actualizados y consultas/reclamos recibidos por el canal institucional. Los cambios de rating se observan, no se atribuyen causalmente al piloto. |

Antes de elegir una intervención se documenta el hallazgo que la motiva: institución, período, tamaño,
categoría, benchmark, reseñas revisadas y cobertura. Una etiqueta del catálogo no basta para afirmar que
horarios o precios son el problema principal; si la evidencia no lo respalda, se cambia la acción.

## Despliegue

El dashboard se ejecuta en plataforma local (Docker Compose o SQL Server + Python), sin exponer el motor
SQL Server a internet. El usuario del dashboard tiene solo lectura sobre el esquema `bi`.
