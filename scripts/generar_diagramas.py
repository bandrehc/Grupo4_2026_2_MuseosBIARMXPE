#!/usr/bin/env python3
"""Genera los diagramas de docs/img leyendo el esquema REAL de SQL Server (tablas, tipos, PK, FK).

  python3 scripts/generar_diagramas.py      # requiere: pip install pymssql, Graphviz (comando `dot`) y MUSEOS_ADMIN_PASS

Salida: docs/img/modelo_relacional_mart.{svg,png}, docs/img/capa_bi.{svg,png}, docs/img/arquitectura.{svg,png}
Conexión: MUSEOS_DB_HOST (127.0.0.1) · MUSEOS_DB_PORT (14330) · MUSEOS_ADMIN_USER (sa) · MUSEOS_ADMIN_PASS
"""
import html, os, subprocess, sys
from pathlib import Path
import pymssql

OUT = Path(__file__).resolve().parent.parent / "docs" / "img"
OUT.mkdir(parents=True, exist_ok=True)

FACT, DIM, BI = "#fde9cf", "#dfeaf7", "#e6f2e3"
HDR_F, HDR_D, HDR_B = "#e08a1e", "#3b6ea8", "#3f8f4f"


def conectar():
    pw = os.getenv("MUSEOS_ADMIN_PASS")
    if not pw:
        sys.exit("Defina MUSEOS_ADMIN_PASS")
    return pymssql.connect(os.getenv("MUSEOS_DB_HOST", "127.0.0.1"), os.getenv("MUSEOS_ADMIN_USER", "sa"), pw, "MuseosLatam_Datamart",
                           port=int(os.getenv("MUSEOS_DB_PORT", "14330")), timeout=0)


def esquema(cur, schema):
    cur.execute("""SELECT t.name,c.name,ty.name,c.max_length,c.precision,c.scale,c.is_nullable,c.column_id
                   FROM sys.tables t JOIN sys.columns c ON c.object_id=t.object_id JOIN sys.types ty ON ty.user_type_id=c.user_type_id
                   WHERE SCHEMA_NAME(t.schema_id)=%s ORDER BY t.name,c.column_id""", (schema,))
    tablas = {}
    for t, c, ty, ml, pr, sc, nul, _ in cur.fetchall():
        if ty in ("nvarchar", "varchar", "char", "nchar", "varbinary"):
            n = "max" if ml == -1 else (ml // 2 if ty.startswith("n") else ml)
            ty = f"{ty}({n})"
        elif ty in ("decimal", "numeric"):
            ty = f"{ty}({pr},{sc})"
        tablas.setdefault(t, []).append(dict(nombre=c, tipo=ty, nulo=bool(nul), pk=False, fk=None))
    cur.execute("""SELECT t.name,c.name FROM sys.indexes i JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
                   JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id JOIN sys.tables t ON t.object_id=i.object_id
                   WHERE i.is_primary_key=1 AND SCHEMA_NAME(t.schema_id)=%s""", (schema,))
    for t, c in cur.fetchall():
        for col in tablas[t]:
            if col["nombre"] == c:
                col["pk"] = True
    cur.execute("""SELECT pt.name,pc.name,rt.name,rc.name,SCHEMA_NAME(rt.schema_id)
                   FROM sys.foreign_key_columns k JOIN sys.tables pt ON pt.object_id=k.parent_object_id JOIN sys.columns pc ON pc.object_id=k.parent_object_id AND pc.column_id=k.parent_column_id
                   JOIN sys.tables rt ON rt.object_id=k.referenced_object_id JOIN sys.columns rc ON rc.object_id=k.referenced_object_id AND rc.column_id=k.referenced_column_id
                   WHERE SCHEMA_NAME(pt.schema_id)=%s""", (schema,))
    fks = cur.fetchall()
    for t, c, rt, rc, _ in fks:
        for col in tablas[t]:
            if col["nombre"] == c:
                col["fk"] = rt
    return tablas, fks


def tabla_html(nombre, cols, color, hdr, filas=None):
    f = [f'<TR><TD COLSPAN="3" BGCOLOR="{hdr}"><FONT COLOR="white"><B>{html.escape(nombre)}</B></FONT></TD></TR>']
    for c in cols:
        marca = "PK" if c["pk"] else ("FK" if c["fk"] else "")
        txt = html.escape(c["nombre"]) if not c["pk"] else f'<B>{html.escape(c["nombre"])}</B>'
        f.append(f'<TR><TD ALIGN="LEFT" PORT="{c["nombre"]}" BGCOLOR="{color}"><FONT POINT-SIZE="9">{txt}</FONT></TD>'
                 f'<TD ALIGN="LEFT" BGCOLOR="{color}"><FONT POINT-SIZE="8" COLOR="#555555">{html.escape(c["tipo"])}{"" if c["nulo"] else " NN"}</FONT></TD>'
                 f'<TD PORT="{c["nombre"]}_m" BGCOLOR="{color}">{('<FONT POINT-SIZE="8" COLOR="#b03030"><B>' + marca + '</B></FONT>') if marca else ""}</TD></TR>')
    if filas is not None:
        f.append(f'<TR><TD COLSPAN="3" BGCOLOR="white"><FONT POINT-SIZE="8" COLOR="#555555">{filas:,} filas</FONT></TD></TR>')
    return f'<<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="3">{"".join(f)}</TABLE>>'


def dot_er(tablas, fks, titulo, es_hecho, color_dim=DIM, hdr_dim=HDR_D, conteos=None, rankdir="LR"):
    L = [f'digraph G {{ rankdir={rankdir}; labelloc=t; fontsize=22; fontname="Helvetica-Bold"; label=<{titulo}<BR/><FONT POINT-SIZE="12" COLOR="#555555">Naranja = tabla de hechos · Azul/verde = dimensión · PK clave primaria · FK clave foránea · NN = no nulo · la pata de gallo marca el lado «muchos» de cada relación N:1</FONT>>; nodesep=0.35; ranksep=2.4; splines=true;',
         'node [shape=plain, fontname="Helvetica"]; edge [color="#5a6b7d", arrowsize=0.8, fontname="Helvetica", fontsize=8];']
    for t, cols in tablas.items():
        c, h = (FACT, HDR_F) if es_hecho(t) else (color_dim, hdr_dim)
        L.append(f'"{t}" [label={tabla_html(t, cols, c, h, (conteos or {}).get(t))}];')
    for t, c, rt, rc, _ in fks:
        if rt in tablas:
            L.append(f'"{t}":"{c}_m":e -> "{rt}":"{rc}":w [arrowhead=tee, arrowtail=crow, dir=both];')
    L.append("}")
    return "\n".join(L)


def render(dot_src, nombre):
    for fmt, extra in (("svg", []), ("png", ["-Gdpi=110"])):
        subprocess.run(["dot", f"-T{fmt}", *extra, "-o", str(OUT / f"{nombre}.{fmt}")], input=dot_src.encode(), check=True, stderr=subprocess.PIPE)
    print("generado", nombre)


def arquitectura():
    src = '''digraph A { rankdir=LR; fontname="Helvetica"; node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, margin="0.18,0.12"]; edge [color="#5a6b7d"];
    labelloc=t; fontsize=20; label="Arquitectura de la solución BI · Museos LATAM";
    csv [label="Reseñas públicas\\n(1,14 M · AR, MX, PE)\\n+ NLP: sentimiento y tópicos", fillcolor="#eeeeee"];
    ori [label="MuseosLatam_Origen\\nstg.* · curado.*\\n(opcional, 1,2 GB)", fillcolor="#eeeeee"];
    subgraph cluster_dm { label="MuseosLatam_Datamart  (SQL Server 2019 · respaldo en data/)"; style="rounded,dashed"; color="#3b6ea8"; fontname="Helvetica";
      mart [label="mart.*\\nmodelo dimensional\\n3 hechos · 10 dimensiones", fillcolor="#dfeaf7"];
      bi0 [label="bi.lugar_decision\\ncuraduría de lugares\\n(824 excl. · 1.138 reclas.)", fillcolor="#fff4cc"];
      bi [label="bi.*\\ncapa de agregados\\nagg_lugar_anio · agg_lugar_topico_anio\\nv_benchmark_lugar · v_resena", fillcolor="#e6f2e3"];
      aud [label="aud.*\\nauditoría de carga", fillcolor="#eeeeee"]; }
    dash [label="Dashboard Plotly Dash\\n6 pestañas · móvil · mapas\\n(usuario de solo lectura dashly_ro)", fillcolor="#f3e3f3"];
    csv -> ori [label=" carga Python/T-SQL"]; ori -> mart [label=" ETL"]; mart -> bi [label=" 01_bi_setup.sql"]; bi0 -> bi [label=" aplica decisiones"]; bi -> dash [label=" solo bi.*"]; mart -> aud [style=dotted, arrowhead=none]; }'''
    render(src, "arquitectura")


def main():
    c = conectar()
    cur = c.cursor()
    tm, fm = esquema(cur, "mart")
    cur.execute("SELECT t.name,SUM(p.row_count) FROM sys.tables t JOIN sys.dm_db_partition_stats p ON p.object_id=t.object_id AND p.index_id<2 WHERE SCHEMA_NAME(t.schema_id)='mart' GROUP BY t.name")
    cont = {a: int(b) for a, b in cur.fetchall()}
    render(dot_er(tm, fm, "Modelo relacional · esquema mart (datamart de reseñas)", lambda t: t.startswith("fact_"), conteos=cont), "modelo_relacional_mart")
    tb, fb = esquema(cur, "bi")
    cur.execute("SELECT t.name,SUM(p.row_count) FROM sys.tables t JOIN sys.dm_db_partition_stats p ON p.object_id=t.object_id AND p.index_id<2 WHERE SCHEMA_NAME(t.schema_id)='bi' GROUP BY t.name")
    contb = {a: int(b) for a, b in cur.fetchall()}
    render(dot_er(tb, fb, "Capa BI · esquema bi (tablas que lee el dashboard)", lambda t: t.startswith("agg_"), HDR_B and BI, HDR_B, contb, "TB"), "capa_bi")
    arquitectura()
    print(f"mart: {len(tm)} tablas, {len(fm)} FK · bi: {len(tb)} tablas, {len(fb)} FK")


if __name__ == "__main__":
    main()
