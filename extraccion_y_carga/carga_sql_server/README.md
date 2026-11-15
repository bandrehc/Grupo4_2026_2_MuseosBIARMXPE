# Carga ETL a SQL Server (Python + T-SQL)

Carga los seis CSV finales del corpus (reseñas, lugares, catálogo de tópicos, puente reseña–tópico y dos
controles) en dos bases SQL Server:

- **MuseosLatam_Origen**: `stg` conserva las fuentes literales; `curado` contiene la revisión semántica
  derivada; `aud` registra hashes, lotes e incidencias.
- **MuseosLatam_Datamart**: `mart` contiene dimensiones, hechos y vistas; `aud` registra ejecuciones y la
  revisión semántica versionada.

Resultados y pruebas: [INFORME_EJECUCION.md](INFORME_EJECUCION.md). Diccionario físico de ambas bases:
[DICCIONARIO_SQL_SERVER.md](DICCIONARIO_SQL_SERVER.md). Trazabilidad campo a campo: `mapa_campos.csv`.

## Ejecución

Requisitos: Python 3.12, Microsoft ODBC Driver 17, los seis CSV finales (verificables con
[`validacion_final.json`](../docs/controles_corpus/validacion_final.json)) y un archivo de conexión privado
con el formato de [`config.example.json`](config.example.json), guardado como
`%LOCALAPPDATA%\MuseosLatamSQL\connection.json` (o en la ruta indicada por `MUSEOS_SQL_CONFIG`).

```powershell
python -m venv $env:LOCALAPPDATA\MuseosLatamSQL\venv
& $env:LOCALAPPDATA\MuseosLatamSQL\venv\Scripts\python.exe -m pip install -r requirements.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\ejecutar.ps1 -Piloto   # piloto en bases separadas
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\ejecutar.ps1           # carga completa
```

`EJECUTAR.cmd` es el equivalente con doble clic. La carga ejecuta dos pasadas idempotentes y valida al final.

## Archivos

| Archivo | Función |
|---|---|
| `cargar.py` | Entrada única: creación protegida de bases, lectura CSV, checkpoints, dimensiones, hechos, validación y lectura de vuelta |
| `01_origen.sql`, `02_datamart.sql` | DDL de las dos bases (los aplica `cargar.py`) |
| `03_vistas.sql` | Vistas analíticas con denominadores válidos |
| `00_ver_resultados.sql` | Consultas de solo lectura para revisar los resultados en SSMS |
| `perfilar.py`, `perfil_fuentes.json` | Perfil independiente de las fuentes (longitudes, claves, controles) y selección del piloto |
| `documentar.py` | Genera `DICCIONARIO_SQL_SERVER.md` desde `sys.columns` de las bases creadas |
| `pruebas_driver.py` | Pruebas del driver con tablas temporales (Unicode, texto largo, rollback, concurrencia) |
| `revision_ia_v1/` | Revisión semántica de tópicos y sentimiento por muestreo, aplicada sobre las bases cargadas |
| `evidencia_*.json`, `prueba_*.json`, `preflight.json`, `cobertura_piloto.json` | Resultados de ejecución en formato de máquina |

## Diseño de la carga

- **Idempotencia y reanudación.** Cada lote inserta filas y su checkpoint en una sola transacción. Si la
  carga se interrumpe, se reanuda desde el último lote confirmado, sin borrar ni truncar tablas.
- **Un solo escritor.** Un bloqueo de sesión (`sp_getapplock`) impide dos cargas concurrentes.
- **Fuente versionada.** La fuente tiene una versión fija y hashes conocidos; una fuente distinta exige una
  versión nueva y no reutiliza checkpoints.
- **Fidelidad.** Los valores se cargan como Unicode literal; las claves de negocio usan colación binaria.
  Cada dimensión tiene un miembro desconocido (SK -1) y las FK permanecen habilitadas y confiables.
- **Reputación.** Una observación por ficha con alguna métrica publicada (6.286). Los tres hechos tienen granos
  distintos y no se suman entre sí. La media de rating es `SUM(rating)/COUNT(rating)`.
