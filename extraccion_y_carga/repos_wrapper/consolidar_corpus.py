"""consolidar_corpus.py — Une todas las corridas (Perú, Argentina y México) en un corpus unico, sin duplicados.

Entradas (data/resenas/):
    comentarios_museos_crudo.csv       corrida I   — los 1081 museos de category=="Museo"
    comentarios_museos_crudo-II.csv    corrida II  — los 581 del delta (toda categoria con "museo")
    comentarios_museos_crudo-III.csv   corrida III — los 79 masivos, con pasadas multi-orden
    comentarios_museos_crudo-IV.csv    corrida IV  — los 24 que fallaron en la III, con el
                                       timeout de script ampliado y poda agresiva
    comentarios_museos_crudo_argentina.csv   corrida AR — Argentina (scrape_museos_v2.py)
    comentarios_museos_crudo_mexico*.csv     corrida MX — México (opcional: se incluye si existe)
    Si el CSV no esta en data/resenas/, se lee su paquete en data/resenas/paquetes/ (*.csv.gz, ver
    empaquetar_resenas.py), de modo que el consolidado se reconstruye desde lo versionado en Git.

Salida:
    comentarios_museos_consolidado.csv       (incluye la columna `pais`: PE, AR, MX)
    comentarios_museos_consolidado.parquet   (particionado por departamento)
    _consolidado_procedencia.csv             de que corrida vino cada reseña

CLAVE DE DEDUPLICACION: id_review.

Por que id_review y no (google_place_id, id_review): hay reseñas que Google sirve bajo DOS
fichas distintas del mismo lugar fisico (ej. "Museo Huacas de Moche" y "Museo Santiago Uceda
Castillo", a 30 m de distancia). Son la MISMA reseña; deduplicar por id_review las colapsa
correctamente.

QUE COPIA SE CONSERVA cuando una reseña aparece en varias corridas:
la de texto mas completo. Medido sobre los datos: de 842 reseñas con texto distinto entre
copias, 841 son casos de TRUNCAMIENTO (ninguna tiene el texto vacio), y quedarse con la mas
larga gana 192 caracteres de mediana. Ademas se penaliza el texto cortado con "…", que indica
que el boton "Mas" no llego a expandirse en esa corrida.
"""
import argparse
import shutil
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
R = PROJECT_ROOT / "data" / "resenas"

# (corrida, pais, patron del archivo). Las corridas sin archivo (p. ej. México aun no entregado) se omiten.
FUENTES = [("I", "PE", "comentarios_museos_crudo.csv"),
           ("II", "PE", "comentarios_museos_crudo-II.csv"),
           ("III", "PE", "comentarios_museos_crudo-III.csv"),
           ("IV", "PE", "comentarios_museos_crudo-IV.csv"),
           ("AR", "AR", "comentarios_museos_crudo_argentina.csv"),
           ("MX", "MX", "comentarios_museos_crudo_mexico*.csv")]


def localizar(patron):
    """Archivos de la fuente: CSV en data/resenas/ o, si no esta, sus paquetes .csv.gz."""
    base = patron[: -len(".csv")]
    return sorted(R.glob(patron)) or sorted((R / "paquetes").glob(base + "*.csv.gz"))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(R / "comentarios_museos_consolidado"))
    ap.add_argument("--desde-consolidado", action="store_true",
                    help="Parte del consolidado ya publicado (data/resenas/comentarios_museos_consolidado.csv o sus "
                         "paquetes .csv.gz) y le suma las fuentes que existan (p. ej. México). Úsalo cuando no "
                         "tengas en disco los crudos de Perú II-IV, que no están en Git.")
    args = ap.parse_args()

    partes = []
    if args.desde_consolidado:
        rutas = sorted(R.glob("comentarios_museos_consolidado.csv")) or \
            sorted((R / "paquetes").glob("comentarios_museos_consolidado*.csv.gz"))
        if not rutas:
            raise SystemExit("No hay consolidado previo (csv ni paquetes/*.csv.gz).")
        base = pd.concat((pd.read_csv(p, low_memory=False) for p in rutas), ignore_index=True)
        base = base.drop(columns=["registro_completo"], errors="ignore")
        print(f"Base publicada: {len(base):,} reseñas ({', '.join(f'{k}={v:,}' for k, v in base.pais.value_counts().items())})")
        partes.append(base)
    print("=" * 74)
    print(f"{'corrida':<10}{'filas':>12}{'museos':>10}{'dup internos':>16}")
    print("-" * 74)
    for nombre, pais, archivo in FUENTES:
        rutas = localizar(archivo)
        if not rutas:
            print(f"{nombre:<10}{'(no existe)':>12}")
            continue
        d = pd.concat((pd.read_csv(p, low_memory=False) for p in rutas), ignore_index=True)
        d["corrida"] = nombre
        d["pais"] = pais
        print(f"{nombre:<10}{len(d):>12,}{d.google_place_id.nunique():>10}"
              f"{int(d.id_review.duplicated().sum()):>16,}")
        partes.append(d)

    todo = pd.concat(partes, ignore_index=True)
    n_bruto = len(todo)

    # --- calidad del texto: completo > truncado, y a igual estado, mas largo mejor ---
    cap = todo["caption"].fillna("")
    todo["_completo"] = (~cap.str.rstrip().str.endswith(("…", "..."))).astype(int)
    todo["_largo"] = cap.str.len()

    # Orden de preferencia: primero el texto completo, luego el mas largo.
    todo = todo.sort_values(["id_review", "_completo", "_largo"],
                            ascending=[True, False, False], kind="mergesort")
    cons = todo.drop_duplicates(subset=["id_review"], keep="first").copy()

    # --- reportes ---
    print("-" * 74)
    print(f"{'bruto':<10}{n_bruto:>12,}")
    print(f"{'duplicados':<10}{n_bruto - len(cons):>12,}")
    print(f"{'CONSOLIDADO':<10}{len(cons):>12,}{cons.google_place_id.nunique():>10}")
    print("=" * 74)

    print("\nProcedencia de la copia conservada:")
    for c, n in cons.corrida.value_counts().items():
        print(f"  corrida {c:<4} {n:>8,}  ({100*n/len(cons):>5.1f}%)")

    multi = cons.merge(
        todo.groupby("id_review").google_place_id.nunique().rename("n_fichas"),
        left_on="id_review", right_index=True)
    n_multi = int((multi.n_fichas > 1).sum())
    print(f"\nReseñas servidas bajo mas de una ficha de Google: {n_multi:,}")
    print("  (mismo lugar fisico con dos entradas; se conserva una sola copia)")

    proc = todo[["id_review", "corrida", "google_place_id"]].drop_duplicates()
    if args.desde_consolidado and (R / "_consolidado_procedencia.csv").exists():
        proc = pd.concat([pd.read_csv(R / "_consolidado_procedencia.csv"), proc]).drop_duplicates()
    proc.to_csv(R / "_consolidado_procedencia.csv", index=False)

    # --- bandera de validez ---
    # Una reseña sin rating NI fecha relativa no es analizable. Se marca en vez de
    # descartarla: el corpus consolidado debe ser un registro fiel de lo extraido, y
    # que el filtro lo aplique quien analice, de forma explicita.
    cons["registro_completo"] = cons.rating.isin([1, 2, 3, 4, 5]) & cons.relative_date.notna()
    n_incompletos = int((~cons.registro_completo).sum())
    if n_incompletos:
        afectados = cons.loc[~cons.registro_completo, "nombre_lugar"].value_counts()
        print(f"\nAviso: {n_incompletos:,} reseñas sin rating ni fecha (marcadas registro_completo=False)")
        print(f"  museos afectados: {len(afectados)}")
        for nom, n in afectados.head(5).items():
            print(f"    {str(nom)[:46]:<48}{n:>6}")

    # --- escritura ---
    cons = cons.drop(columns=["_completo", "_largo"])
    cons = cons[[c for c in cons.columns if c not in ("registro_completo", "pais")] + ["registro_completo", "pais"]]
    print("\nReseñas por pais:")
    for c, n in cons.pais.value_counts().items():
        print(f"  {c}  {n:>9,}")
    out = Path(args.out)
    cons.to_csv(out.with_suffix(".csv"), index=False, encoding="utf-8")
    pq = out.with_suffix(".parquet")
    if pq.exists():
        shutil.rmtree(pq)
    cons.to_parquet(pq, index=False, partition_cols=["departamento"])

    print(f"\n  -> {out.with_suffix('.csv').name}  ({len(cons):,} reseñas)")
    print(f"  -> {pq.name}  (particionado por departamento)")
    print(f"  -> _consolidado_procedencia.csv")

    # --- verificaciones de integridad ---
    print("\nVerificaciones:")
    print(f"  id_review unicos      : {cons.id_review.is_unique}")
    print(f"  id_review nulos       : {int(cons.id_review.isna().sum())}")
    print(f"  registros completos   : {int(cons.registro_completo.sum()):,} "
          f"({100*cons.registro_completo.mean():.2f}%)")
    print(f"  con texto             : {int(cons.caption.notna().sum()):,} "
          f"({100*cons.caption.notna().mean():.1f}%)")
    print(f"  departamentos         : {cons.departamento.nunique()}")


if __name__ == "__main__":
    main()
