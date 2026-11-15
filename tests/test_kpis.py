#!/usr/bin/env python3
"""Pruebas de reconciliación: recalcula de forma independiente desde mart.* y compara con la capa BI y con
las funciones del dashboard. Consciente de las decisiones de curaduría (exclusiones / reclasificaciones).

  python3 tests/test_kpis.py          # sale con código 1 si algo no cuadra

Conexión de administrador (lee mart.*): MUSEOS_ADMIN_PASS o MUSEOS_ADMIN_PASS_FILE (ver bi/cargar_decisiones.py).
"""
import os, sys, warnings
from pathlib import Path

warnings.filterwarnings("ignore")
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "dashboard"))
import numpy as np
import pandas as pd
import pymssql

resultados = []


def check(nombre, ok, detalle=""):
    resultados.append((nombre, bool(ok), detalle))
    print(f"  [{'OK ' if ok else 'FALLA'}] {nombre}" + (f"  — {detalle}" if detalle else ""), flush=True)


def conectar():
    pw = os.getenv("MUSEOS_ADMIN_PASS")
    if not pw and os.getenv("MUSEOS_ADMIN_PASS_FILE"):
        f = Path(os.environ["MUSEOS_ADMIN_PASS_FILE"])
        pw = f.read_text().strip() if f.exists() else None
    if not pw:
        sys.exit("Defina MUSEOS_ADMIN_PASS o MUSEOS_ADMIN_PASS_FILE")
    return pymssql.connect(os.getenv("MUSEOS_DB_HOST", "127.0.0.1"), os.getenv("MUSEOS_ADMIN_USER", "sa"), pw, "MuseosLatam_Datamart",
                           port=int(os.getenv("MUSEOS_DB_PORT", "14330")), timeout=0)


def q(c, sql, params=None):
    cur = c.cursor(as_dict=True)
    cur.execute(sql, params)
    df = pd.DataFrame(cur.fetchall())
    for col in df.columns:
        if df[col].dtype == object:
            try:
                df[col] = pd.to_numeric(df[col])
            except (ValueError, TypeError):
                pass
    return df


# Recálculo independiente desde mart.*: lugar efectivo = categoría con decisión aplicada, sin excluidos
BASE = """
FROM mart.fact_resena f
JOIN mart.dim_lugar l ON l.sk_lugar=f.sk_lugar
JOIN mart.dim_geografia g ON g.sk_geografia=l.sk_geografia
JOIN mart.dim_tiempo t ON t.sk_periodo=f.sk_periodo
JOIN mart.dim_sentimiento s ON s.sk_sentimiento=f.sk_sentimiento
LEFT JOIN bi.lugar_decision d ON d.sk_lugar=l.sk_lugar
WHERE COALESCE(d.decision,'Mantener')<>'Excluir'
"""


def main():
    c = conectar()
    print("1) Reconciliación global (vista de control)")
    ctl = q(c, "SELECT * FROM bi.v_control_reconciliacion").iloc[0]
    check("v_control_reconciliacion.ok = 1", ctl.ok == 1, f"datamart {int(ctl.resenas_datamart):,} − excluidas {int(ctl.resenas_excluidas):,} = BI {int(ctl.resenas_bi):,}")
    check("sin decisiones huérfanas", ctl.decisiones_huerfanas == 0)

    print("2) Agregado lugar × año (recalculado desde mart)")
    ref = q(c, "SELECT f.sk_lugar,ISNULL(t.anio,0) anio,COUNT(*) n,COUNT(f.rating) nr,ISNULL(SUM(CONVERT(int,f.rating)),0) sr,"
               "SUM(CONVERT(int,f.tiene_texto)) txt,SUM(CASE WHEN s.etiqueta='Positivo' THEN 1 ELSE 0 END) pos,"
               "SUM(CASE WHEN s.etiqueta='Neutro' THEN 1 ELSE 0 END) neu,SUM(CASE WHEN s.etiqueta='Negativo' THEN 1 ELSE 0 END) neg,"
               "SUM(CASE WHEN f.rating<=2 THEN 1 ELSE 0 END) bajo " + BASE + " GROUP BY f.sk_lugar,ISNULL(t.anio,0)")
    bi = q(c, "SELECT sk_lugar,anio,n_resenas n,n_ratings nr,suma_rating sr,n_con_texto txt,n_pos pos,n_neu neu,n_neg neg,n_rating_neg bajo FROM bi.agg_lugar_anio")
    m = ref.merge(bi, on=["sk_lugar", "anio"], how="outer", suffixes=("_ref", "_bi"), indicator=True)
    solo = int((m._merge != "both").sum())
    cols = ["n", "nr", "sr", "txt", "pos", "neu", "neg", "bajo"]
    # la suma de estrellas es NULL en BI cuando el lugar-año no tiene ratings (n_ratings = 0); equivale a 0
    dif = sum(int((m[k + "_ref"].fillna(0) != m[k + "_bi"].fillna(0)).sum()) for k in cols)
    check("mismas claves lugar×año", solo == 0, f"{len(m):,} filas; sin pareja: {solo}")
    check("mismos valores en las 8 métricas", dif == 0, f"celdas distintas: {dif}")

    print("3) KPI del dashboard (código real de app.py) frente a SQL directo")
    import app  # carga la capa BI como lo hace el dashboard
    P = app.PAISES
    combos = [(P, ["museo"], [2017, 2026]), (["Perú"], ["museo", "sitio_arqueologico"], [2019, 2024]), (["México", "Argentina"], app.CATS, [1900, 2100])]
    for paises, cats, rng in combos:
        l = app.sel(app.LUG_ANIO, paises, cats, rng)
        tot = app.agrega(l.assign(k=1), "k").iloc[0] if len(l) else None
        sql = ("SELECT COUNT(*) n,COUNT(f.rating) nr,ISNULL(SUM(CONVERT(int,f.rating)),0) sr,"
               "SUM(CASE WHEN s.etiqueta='Negativo' THEN 1 ELSE 0 END) neg,SUM(CASE WHEN s.etiqueta IN ('Positivo','Neutro','Negativo') THEN 1 ELSE 0 END) cl "
               + BASE + " AND g.pais_nombre IN (" + ",".join("N'" + x + "'" for x in paises) + ") AND COALESCE(d.categoria_nueva,l.categoria_normalizada) IN ("
               + ",".join("N'" + x + "'" for x in cats) + ") AND t.anio BETWEEN %d AND %d")
        r = q(c, sql, (rng[0], rng[1])).iloc[0]
        etq = f"{'+'.join(x[:2] for x in paises)} | {len(cats)} cat | {rng[0]}–{rng[1]}"
        ok = tot is not None and int(tot.n) == int(r.n) and int(tot.r) == int(r.nr) and int(tot.s) == int(r.sr) and abs(tot.pct_neg - r.neg / r.cl) < 1e-12
        check(f"KPI panorama [{etq}]", ok, f"reseñas {int(r.n):,}, rating {r.sr / r.nr:.4f}, %neg {r.neg / r.cl:.4%}")

    print("4) Tópicos (menciones por país × tópico)")
    rt = q(c, "SELECT g.pais_nombre pais,dl.etiqueta topico,COUNT(*) n FROM mart.fact_resena_dimension w JOIN mart.fact_resena f ON f.sk_resena=w.sk_resena "
              "JOIN mart.dim_lugar l ON l.sk_lugar=f.sk_lugar JOIN mart.dim_geografia g ON g.sk_geografia=l.sk_geografia "
              "JOIN mart.dim_dimension_latente dl ON dl.sk_dimension_latente=w.sk_dimension_latente AND dl.apto_analisis_tematico=1 "
              "LEFT JOIN bi.lugar_decision d ON d.sk_lugar=l.sk_lugar WHERE COALESCE(d.decision,'Mantener')<>'Excluir' GROUP BY g.pais_nombre,dl.etiqueta")
    bt = app.TOPL.groupby(["pais", "topico"], as_index=False).n_resenas.sum()
    mt = rt.merge(bt, on=["pais", "topico"], how="outer")
    check("menciones por país × tópico coinciden", (mt.n.fillna(-1) == mt.n_resenas.fillna(-1)).all(), f"{len(mt)} combinaciones; total {int(rt.n.sum()):,}")
    ts = app.TSENT.groupby(["pais", "topico"], as_index=False).n.sum().merge(bt, on=["pais", "topico"])
    check("tópico × sentimiento suma lo mismo que tópico", (ts.n == ts.n_resenas).all())

    print("5) Benchmark (rating suavizado y percentil recalculados)")
    pl = q(c, "SELECT f.sk_lugar,COUNT(*) n,COUNT(f.rating) nr,SUM(CONVERT(int,f.rating)) sr,g.pais_nombre pais,COALESCE(d.categoria_nueva,l.categoria_normalizada) cat "
              + BASE + " GROUP BY f.sk_lugar,g.pais_nombre,COALESCE(d.categoria_nueva,l.categoria_normalizada)")
    grp = pl.groupby(["pais", "cat"]).apply(lambda x: x.sr.sum() / x.nr.sum(), include_groups=False).rename("mg").reset_index()
    pl = pl.merge(grp, on=["pais", "cat"])
    pl["rs"] = (pl.sr + 20 * pl.mg) / (pl.nr + 20)
    cmp_ = pl[pl.nr >= 30].copy()
    cmp_["pr"] = cmp_.groupby(["pais", "cat"]).rs.rank(method="min").sub(1).div(cmp_.groupby(["pais", "cat"]).rs.transform("count").sub(1).replace(0, np.nan))
    b = app.BENCH.merge(pl[["sk_lugar", "rs"]], on="sk_lugar", how="outer", indicator=True)
    check("mismos lugares en BENCH y en el recálculo", (b._merge == "both").all(), f"{len(b):,} lugares")
    check("rating suavizado coincide (|Δ| < 1e-6)", float((b.rating_suavizado - b.rs).abs().max()) < 1e-6, f"máx |Δ| = {float((b.rating_suavizado - b.rs).abs().max()):.2e}")
    bp = app.BENCH.merge(cmp_[["sk_lugar", "pr"]], on="sk_lugar")
    ds = (bp.pct_rank_pares - bp.pr).abs()
    check("percentil vs pares coincide (|Δ| < 1e-6)", float(ds.fillna(0).max()) < 1e-6 and bp.pct_rank_pares.notna().all(), f"{len(bp):,} comparables")

    print("6) Reseñas individuales")
    nv = int(q(c, "SELECT COUNT_BIG(*) n FROM bi.v_resena").n.iloc[0])
    ne = int(q(c, "SELECT COUNT_BIG(*) n " + BASE + " AND f.tiene_texto=1").n.iloc[0])
    check("bi.v_resena = reseñas con texto no excluidas", nv == ne, f"{nv:,}")
    muestra = q(c, "SELECT TOP 25 v.sk_resena,v.texto_resena a,f.texto_resena b FROM bi.v_resena v JOIN mart.fact_resena f ON f.sk_resena=v.sk_resena ORDER BY NEWID()")
    check("texto idéntico al del datamart (25 al azar)", (muestra.a == muestra.b).all())

    print("7) Decisiones aplicadas se reflejan en todas las capas")
    excl = set(q(c, "SELECT sk_lugar FROM bi.lugar_decision WHERE decision='Excluir'").get("sk_lugar", pd.Series(dtype=int)).astype(int))
    opc = {o["value"] for o in app.OPCIONES}
    en = {"LUGAR": set(app.LUGAR.sk_lugar), "LUG_ANIO": set(app.LUG_ANIO.sk_lugar), "TOPL": set(app.TOPL.sk_lugar), "BENCH": set(app.BENCH.sk_lugar), "selector": opc}
    check(f"{len(excl)} lugares excluidos ausentes en dashboard", all(not (excl & v) for v in en.values()))
    rec = q(c, "SELECT d.sk_lugar,d.categoria_nueva FROM bi.lugar_decision d WHERE d.decision='Reclasificar'")
    okr = all(app.LUGAR.loc[app.LUGAR.sk_lugar == r.sk_lugar, "categoria"].iloc[0] == r.categoria_nueva for r in rec.itertuples()) if len(rec) else True
    check(f"{len(rec)} lugares reclasificados con su categoría efectiva", okr)

    fallos = [r for r in resultados if not r[1]]
    print(f"\n{len(resultados) - len(fallos)}/{len(resultados)} pruebas OK" + ("" if not fallos else "  —  FALLAN: " + "; ".join(n for n, _, _ in fallos)))
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
