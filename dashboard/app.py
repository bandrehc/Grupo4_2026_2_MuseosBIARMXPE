"""Dashboard Museos LATAM (Plotly Dash). Lee solo el esquema bi de MuseosLatam_Datamart."""
import os, sys
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pymssql
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
from dash import Dash, dcc, html, dash_table, Input, Output
from metricas import benchmark

HOST = os.getenv("MUSEOS_DB_HOST", "127.0.0.1")
PORT = int(os.getenv("MUSEOS_DB_PORT", "14330"))
USER = os.getenv("MUSEOS_DB_USER", "dashly_ro")
PWD = os.getenv("MUSEOS_DB_PASS") or (Path(os.environ["MUSEOS_DB_PASS_FILE"]).read_text().strip() if os.getenv("MUSEOS_DB_PASS_FILE") else None)
if not PWD:
    sys.exit("Defina MUSEOS_DB_PASS (contraseña del usuario de solo lectura dashly_ro). Ver README.md, sección «Ejecución local».")


def q(sql, params=None):
    c = pymssql.connect(HOST, USER, PWD, "MuseosLatam_Datamart", port=PORT)
    try:
        cur = c.cursor(as_dict=True)
        cur.execute(sql, params)
        df = pd.DataFrame(cur.fetchall())
        # pymssql entrega DECIMAL/NUMERIC como decimal.Decimal: numpy (mapas, medias) necesita float.
        for col in df.columns:
            if df[col].map(lambda v: isinstance(v, Decimal)).any():
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    finally:
        c.close()


# ---------- datos (tablas bi pequeñas, cargadas al arrancar) ----------
LUGAR = q("SELECT * FROM bi.lugar")
LUG_ANIO = q("SELECT a.*, l.nombre, l.pais, l.categoria FROM bi.agg_lugar_anio a JOIN bi.lugar l ON l.sk_lugar=a.sk_lugar")
TOPL = q("SELECT a.*, l.pais, l.categoria FROM bi.agg_lugar_topico_anio a JOIN bi.lugar l ON l.sk_lugar=a.sk_lugar")
BENCH = q("SELECT * FROM bi.v_benchmark_lugar")
TSENT = q("SELECT * FROM bi.agg_topico_sent_anio")
TCAT = q("SELECT * FROM bi.topico_catalogo")
META = dict(zip(*[q("SELECT clave,valor FROM bi.meta")[c] for c in ("clave", "valor")]))


def texto_curaduria():
    ne, nr, nm = (int(META.get(k, 0) or 0) for k in ("n_excluidos", "n_reclasificados", "n_mantener_revisados"))
    if ne == nr == nm == 0:
        return "Sin ajustes de curaduría de lugares: se muestran todos los lugares del datamart con su categoría original."
    return (f"Curaduría de lugares (lote #{META.get('ultimo_lote')}): {ne} lugares excluidos, {nr} reclasificados y {nm} revisados y mantenidos. "
            f"Capa construida el {META.get('construido_utc')} UTC.")
_reg = LUGAR[["sk_lugar", "region"]]
LUG_ANIO = LUG_ANIO.merge(_reg, on="sk_lugar", how="left")
TOPL = TOPL.merge(_reg, on="sk_lugar", how="left")
for d in (LUG_ANIO, TOPL, TSENT):
    d["anio"] = d["anio"].astype(int)
for c in LUG_ANIO.columns:
    if c not in ("nombre", "pais", "categoria", "region"):
        LUG_ANIO[c] = pd.to_numeric(LUG_ANIO[c])
for c in ("rating_prom", "rating_suavizado", "pct_rating_bajo", "pct_pos", "pct_neg", "pct_rank_pares", "latitud", "longitud", "media_grupo"):
    BENCH[c] = pd.to_numeric(BENCH[c], errors="coerce")
PAISES = sorted(LUGAR.pais.unique())
CATS = sorted(LUGAR.categoria.unique())
MILLONES = f"{LUG_ANIO.n_resenas.sum() / 1e6:.2f}".replace(".", ",")
ANIOS = sorted(int(a) for a in LUG_ANIO.anio.unique() if a > 0)

# ---------- estilo ----------
PCOLOR = {"Argentina": "#1f9fb5", "México": "#f2a03d", "Perú": "#c0485a"}
PAL = ["#5b3f8c", "#1f9fb5", "#f2a03d", "#c0485a", "#2fa56b", "#8d99ae", "#e76f9a", "#7fb069", "#3d5a80", "#d4a373", "#9b5de5"]
SENT = {"Positivo": "#2fa56b", "Neutro": "#b9b3a6", "Negativo": "#c0485a"}
tpl = go.layout.Template(pio.templates["plotly_white"])
tpl.layout.update(font=dict(family="Inter, Segoe UI, system-ui, sans-serif", color="#1c2733", size=12),
                  paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                  title=dict(font=dict(size=15, color="#1c2733"), x=0.02, xanchor="left"),
                  xaxis=dict(gridcolor="#eee8de", linecolor="#d9d2c5", zeroline=False),
                  yaxis=dict(gridcolor="#eee8de", linecolor="#d9d2c5", zeroline=False),
                  legend=dict(orientation="h", y=-0.2, title=None), margin=dict(l=10, r=10, t=50, b=10),
                  colorway=list(PCOLOR.values()) + ["#5b3f8c", "#2fa56b", "#8d99ae"])
pio.templates["museos"] = tpl
pio.templates.default = "museos"

app = Dash(__name__, title="Museos LATAM · Percepción de visitantes", suppress_callback_exceptions=True,
           meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}])
server = app.server


TIPS = {
    "Reseñas": "Número de reseñas (con o sin texto) del filtro actual.",
    "Rating promedio": "Promedio de estrellas (1-5) de las reseñas con rating. Tiene efecto techo (~4,5).",
    "Sentimiento negativo": "% de reseñas con sentimiento negativo sobre las reseñas clasificadas (excluye sin texto y no clasificadas). El sentimiento es automático.",
    "Reseñas con texto": "% de reseñas que incluyen comentario escrito.",
    "Lugares": "Lugares con al menos una reseña en el filtro.",
    "Lugares comparables": "Lugares con ≥30 ratings; solo ellos entran en rankings y percentiles.",
    "Percentil vs pares": "Posición del rating suavizado frente a lugares de su mismo país y categoría (100 % = el mejor).",
    "Ratings bajos": "% de ratings de 1 o 2 estrellas.",
    "Tópicos aptos": "22 de 41 tópicos con soporte muestral suficiente; los otros 19 son de uso restringido.",
    "Menciones de tópico": "Baseline: un tópico dominante por reseña asignada; se muestran solo los habilitados por revisión IA.",
    "Brecha top–fondo": "Diferencia entre el rating suavizado medio del top 15 y del fondo 15.",
}


def kpi(titulo, valor, sub=None, color="#5b3f8c"):
    return html.Div([html.Div(titulo, className="t"), html.Div(valor, className="v" + (" long" if len(str(valor)) > 12 else "")), html.Div(sub or "", className="s")],
                    className="kpi", style={"--c": color}, title=TIPS.get(titulo, ""))


def panel(fig, h=None):
    """Gráfico responsive: la altura de escritorio va en el style y el CSS la reduce en móvil (ver style.css)."""
    h = h or fig.layout.height or 400
    fig.update_layout(height=None, autosize=True)
    return html.Div(dcc.Graph(figure=fig, responsive=True, style={"height": f"{h}px"}, className="g",
                              config={"displaylogo": False, "displayModeBar": False}), className="panel")


def _vista(df, lat="latitud", lon="longitud", alto=500, ancho=560):
    """Centro y zoom (Web Mercator) para que todos los puntos de df entren en un mapa de alto×ancho px."""
    merc = lambda la: np.log(np.tan(np.pi / 4 + np.radians(la) / 2))
    la0, la1, lo0, lo1 = df[lat].min(), df[lat].max(), df[lon].min(), df[lon].max()
    dx = max(np.radians(lo1 - lo0), 0.01)  # radianes de longitud
    dy = max(merc(la1) - merc(la0), 0.01)  # radianes mercator
    z = min(np.log2(ancho * 2 * np.pi / (512 * dx)), np.log2(alto * 2 * np.pi / (512 * dy))) - 0.25
    cy = np.degrees(2 * np.arctan(np.exp((merc(la0) + merc(la1)) / 2)) - np.pi / 2)
    return dict(center=dict(lat=float(cy), lon=float((lo0 + lo1) / 2)), zoom=float(max(1, min(z, 12))))


def mapa(fig, df, lat="latitud", lon="longitud", alto=560):
    """Mapa base vectorial (CARTO, sin token) con zoom automático y botones por país. Solo se descargan los puntos ya agregados."""
    df = df.dropna(subset=[lat, lon])
    if df.empty:
        fig.add_annotation(text='Sin coordenadas disponibles para estos filtros', showarrow=False)
        return fig
    fig.update_traces(marker=dict(opacity=0.85, sizemin=4))
    fig.update_layout(map_style="carto-positron", map=_vista(df, lat, lon, alto), margin=dict(l=0, r=0, t=46, b=0))
    botones = [dict(label="Todos", method="relayout", args=[{"map.center": _vista(df, lat, lon, alto)["center"], "map.zoom": _vista(df, lat, lon, alto)["zoom"]}])]
    for p in sorted(df.pais.unique()):
        v = _vista(df[df.pais == p], lat, lon, alto)
        botones.append(dict(label=p, method="relayout", args=[{"map.center": v["center"], "map.zoom": v["zoom"]}]))
    fig.update_layout(updatemenus=[dict(type="buttons", direction="right", x=0.01, y=0.99, xanchor="left", yanchor="top", buttons=botones,
                                        bgcolor="rgba(255,255,255,.92)", bordercolor="#d9d2c5", pad=dict(r=4, t=2, b=2))])
    return fig


def note(txt):
    return html.Div(txt, className="note")


app.layout = html.Div([
    html.Div([
        html.H1("Museos y patrimonio · Percepción de visitantes"),
        html.P(f"Tablero estratégico sobre {MILLONES} M de reseñas de museos y sitios patrimoniales de Argentina, México y Perú: "
               "tendencias de opinión, tópicos y comparación entre instituciones."),
        html.Div([html.Span(p, className="pill", style={"background": c}) for p, c in PCOLOR.items()], className="pills"),
    ], className="hero"),
    html.Div([
        html.Div([
            html.Div([html.Label("País"), dcc.Dropdown(PAISES, PAISES, multi=True, id="f-pais", clearable=False, persistence=True, persistence_type="session")], style={"flex": 2}),
            html.Div([html.Label("Categoría de lugar"), dcc.Dropdown(CATS, ["museo"], multi=True, id="f-cat", clearable=False, persistence=True, persistence_type="session")], style={"flex": 2}),
            html.Div([html.Label("Años"), dcc.RangeSlider(min(ANIOS), max(ANIOS), 1, value=[2017, max(ANIOS)], id="f-anio", persistence=True, persistence_type="session",
                      marks={a: str(a) for a in ANIOS if a % 3 == 0 and a < max(ANIOS) - 1 or a == max(ANIOS)})], style={"flex": 3}),
            html.Div([html.Label("Volumen en gráficos"), dcc.RadioItems(
                [{"label": " Cantidad", "value": "n"}, {"label": " % dentro de cada país", "value": "pct"}], os.getenv("MUSEOS_VOL", "n"), id="f-vol", inline=True, persistence=True, persistence_type="session",
                inputStyle={"marginLeft": "10px", "marginRight": "3px"})], style={"flex": 2}),
        ], className="filters", id="filtros"),
        dcc.Tabs(id="tabs", value=os.getenv("MUSEOS_TAB", "panorama"), persistence=True, persistence_type="session", parent_className="tabs-bar", children=[
            dcc.Tab(label="Panorama regional", value="panorama", className="tab", selected_className="tab--selected"),
            dcc.Tab(label="Nacional y benchmarking", value="museos", className="tab", selected_className="tab--selected"),
            dcc.Tab(label="Tópicos", value="topicos", className="tab", selected_className="tab--selected"),
            dcc.Tab(label="Mi museo", value="inst", className="tab", selected_className="tab--selected"),
            dcc.Tab(label="Reseñas", value="resenas", className="tab", selected_className="tab--selected"),
            dcc.Tab(label="Metodología", value="metodo", className="tab", selected_className="tab--selected"),
        ]),
        html.Div(id="contenido", style={"marginTop": "14px"}),
        html.Div(["Reseñas públicas autoseleccionadas; cobertura distinta por país. 89 % de las reseñas tiene fecha solo a nivel año. "
                  "El sentimiento y los tópicos son automáticos y con errores conocidos.", html.Br(), texto_curaduria()],
                 style={"fontSize": "11.5px", "color": "#8a8f98", "marginTop": "30px"}),
    ], className="wrap"),
], className="app")


@app.callback(Output("filtros", "style"), Input("tabs", "value"))
def mostrar_filtros(tab):
    return {} if tab in ("panorama", "museos", "topicos") else {"display": "none"}


def sel(df, paises, cats, rng):
    return df[df.pais.isin(paises or []) & df.categoria.isin(cats or []) & df.anio.between(rng[0], rng[1])]


def agrega(l, by):
    g = l.groupby(by).agg(n=("n_resenas", "sum"), s=("suma_rating", "sum"), r=("n_ratings", "sum"), bajo=("n_rating_neg", "sum"),
                          pos=("n_pos", "sum"), neu=("n_neu", "sum"), neg=("n_neg", "sum"), txt=("n_con_texto", "sum")).reset_index()
    cl = (g.pos + g.neu + g.neg).replace(0, np.nan)
    g["rating"] = g.s / g.r.replace(0, np.nan)
    g["pct_neg"] = g.neg / cl
    g["pct_pos"] = g.pos / cl
    g["pct_bajo"] = g.bajo / g.r.replace(0, np.nan)
    return g


def fmt(x, f="{:.1%}"):
    return "n/d" if pd.isna(x) else f.format(x)


# ---------------- páginas ----------------
def page_panorama(paises, cats, rng, vol="n"):
    l = sel(LUG_ANIO, paises, cats, rng)
    if l.empty:
        return note("Sin datos para los filtros elegidos.")
    tot = agrega(l.assign(k=1), "k").iloc[0]
    ser = agrega(l, ["pais", "anio"])
    ser = ser[ser.anio > 0]
    f1 = px.line(ser, x="anio", y="rating", color="pais", markers=True, color_discrete_map=PCOLOR, title="Rating promedio por año")
    f1.update_yaxes(range=[1, 5]); f1.update_traces(line_width=3, marker_size=8)
    if vol == "pct":
        ser["pct_pais"] = ser.n / ser.groupby("pais").n.transform("sum")
        f2 = px.bar(ser, x="anio", y="pct_pais", color="pais", barmode="group", color_discrete_map=PCOLOR,
                    title="Distribución anual de las reseñas de cada país (% del total del país)")
        f2.update_yaxes(tickformat=".0%", title="% de las reseñas del país")
    else:
        f2 = px.bar(ser, x="anio", y="n", color="pais", color_discrete_map=PCOLOR, title="Volumen de reseñas por año (cantidad)")
        f2.update_yaxes(title="reseñas")
    f3 = px.line(ser, x="anio", y="pct_neg", color="pais", markers=True, color_discrete_map=PCOLOR, title="% de sentimiento negativo")
    f3.update_yaxes(tickformat=".0%"); f3.update_traces(line_width=3, marker_size=8)
    p = agrega(l, "pais").sort_values("n", ascending=False)
    f4 = go.Figure()
    for k, nm in (("pct_pos", "Positivo"), ("pct_neg", "Negativo")):
        f4.add_bar(x=p.pais, y=p[k], name=nm, marker_color=SENT[nm], text=p[k].map("{:.1%}".format), textposition="outside")
    f4.update_layout(barmode="group", title="Sentimiento por país (reseñas clasificadas)", yaxis_tickformat=".0%")
    f5 = px.bar(p, x="pais", y="pct_bajo", color="pais", color_discrete_map=PCOLOR, title="% de ratings bajos (1–2 estrellas)", text=p.pct_bajo.map("{:.1%}".format))
    f5.update_layout(showlegend=False, yaxis_tickformat=".0%"); f5.update_traces(textposition="outside")
    tm = agrega(l, ["pais", "region", "categoria"])
    tm = tm[tm.n > 0]
    ftm = px.treemap(tm, path=[px.Constant("LATAM"), "pais", "region", "categoria"], values="n", color="rating", color_continuous_scale="RdYlGn",
                     range_color=[4.2, 4.8], title="Mapa de árbol: tamaño = reseñas · color = rating (país › región › categoría)")
    ftm.update_traces(root_color="#f4f1ec", marker_line_width=1)
    hm = ser.pivot(index="pais", columns="anio", values="pct_neg")
    fhm = px.imshow(hm, aspect="auto", color_continuous_scale="OrRd", title="% sentimiento negativo: país × año", text_auto=".1%")
    fhm.update_layout(coloraxis_colorbar_tickformat=".1%", xaxis_title=None, yaxis_title=None)
    bv = benchmark(LUG_ANIO, LUGAR, paises, cats, rng)
    bv = bv[bv.estado_muestra == 'comparable']
    fvi = px.violin(bv, x="pais", y="rating_suavizado", color="pais", box=True, points=False, color_discrete_map=PCOLOR,
                    title="Dispersión del rating entre instituciones (lugares con ≥30 ratings)")
    fvi.update_layout(showlegend=False, xaxis_title=None, yaxis_title="rating suavizado"); fvi.update_yaxes(range=[1, 5])
    return html.Div([
        html.Div([kpi("Reseñas", f"{int(tot.n):,}", "en el periodo filtrado"), kpi("Rating promedio", f"{tot.rating:.2f}", "de 5 estrellas", "#2fa56b"),
                  kpi("Sentimiento negativo", fmt(tot.pct_neg), "de reseñas clasificadas", "#c0485a"),
                  kpi("Reseñas con texto", f"{tot.txt / tot.n:.0%}", f"{int(tot.txt):,} comentarios", "#1f9fb5"),
                  kpi("Lugares", f"{l.sk_lugar.nunique():,}", "con al menos una reseña", "#f2a03d")], className="kpis"),
        note("Vista de volumen en % : cada país se normaliza sobre su propio total del periodo filtrado, de modo que países con volúmenes muy distintos (p. ej. Perú tiene ~4 veces menos reseñas que México) sean comparables.") if vol == "pct" else html.Div(),
        html.Div([panel(f1, 380), panel(f2, 380)], className="grid2"),
        html.Div([panel(f3, 380), panel(f4, 380)], className="grid2"),
        html.Div([panel(f5, 340), panel(fvi, 340)], className="grid2"),
        html.Div([panel(ftm, 520), panel(fhm, 520)], className="grid2"),
        note("El rating tiene efecto techo (promedio ≈ 4,5): para distinguir instituciones conviene mirar también ratings bajos y sentimiento negativo."),
    ])


def page_museos(paises, cats, rng, vol="n"):
    b = benchmark(LUG_ANIO, LUGAR, paises, cats, rng)
    c = b[b.estado_muestra == "comparable"].sort_values("rating_suavizado", ascending=False)
    if c.empty:
        return note("Sin lugares comparables (≥30 ratings) para los filtros.")
    reg = c.groupby(["pais", "region"]).agg(n=("sk_lugar", "count"), rating=("rating_suavizado", "mean"), res=("n_resenas", "sum")).reset_index()
    reg = reg[reg.n >= 3].sort_values("rating")
    freg = px.bar(reg.tail(15), x="rating", y="region", color="pais", orientation="h", color_discrete_map=PCOLOR,
                  title="Regiones con mejor rating medio (≥3 lugares)", hover_data=["n", "res"])
    freg2 = px.bar(reg.head(15), x="rating", y="region", color="pais", orientation="h", color_discrete_map=PCOLOR,
                   title="Regiones con menor rating medio (≥3 lugares)", hover_data=["n", "res"])
    for f in (freg, freg2):
        f.update_xaxes(range=[1, 5]); f.update_layout(yaxis_title=None, xaxis_title="rating medio de sus lugares")
    top, bot = c.head(15), c.tail(15).sort_values("rating_suavizado")
    ft = px.bar(top[::-1], x="rating_suavizado", y="nombre", color="pais", color_discrete_map=PCOLOR, orientation="h", title="Mejor valorados", hover_data=["n_ratings", "pct_neg"])
    fb = px.bar(bot[::-1], x="rating_suavizado", y="nombre", color="pais", color_discrete_map=PCOLOR, orientation="h", title="Peor valorados", hover_data=["n_ratings", "pct_neg"])
    for f in (ft, fb):
        f.update_xaxes(range=[1, 5]); f.update_layout(yaxis_title=None, xaxis_title="rating suavizado")
    cm = c.dropna(subset=["latitud"])
    fm = px.scatter_map(cm, lat="latitud", lon="longitud", color="rating_suavizado", size="n_ratings", size_max=16, hover_name="nombre",
                        hover_data={"pais": True, "region": True, "n_ratings": True, "latitud": False, "longitud": False},
                        color_continuous_scale="RdYlGn", range_color=[3.5, 5], title="Mapa de lugares comparables (zoom con la rueda; botones por país)")
    mapa(fm, cm)
    tabla = c[["nombre", "pais", "region", "categoria", "n_ratings", "rating_prom", "rating_suavizado", "pct_rating_bajo", "pct_neg", "pct_rank_pares"]].round(3)
    for col in ('pct_rating_bajo','pct_neg','pct_rank_pares'):
        tabla[col] = (tabla[col] * 100).round(1)
    tabla.columns = ["Lugar", "País", "Región", "Categoría", "Ratings", "Rating", "Rating suavizado", "% rating bajo", "% negativo", "Percentil vs pares"]
    fsc = px.scatter(c, x="n_ratings", y="rating_suavizado", color="pais", color_discrete_map=PCOLOR, log_x=True, opacity=0.65, hover_name="nombre",
                     hover_data=["region", "n_ratings", "rating_prom"], title="Tamaño de muestra vs rating suavizado (cada punto = un lugar)")
    fsc.update_layout(xaxis_title="ratings (escala log)", yaxis_title="rating suavizado"); fsc.update_yaxes(range=[1, 5])
    ly = sel(LUG_ANIO, paises, cats, rng)
    ly = ly[ly.anio > 0]
    ry = ly.groupby(["pais", "region", "anio"]).agg(s=("suma_rating", "sum"), r=("n_ratings", "sum")).reset_index()
    ry = ry[ry.r >= 200]
    ry["rating"] = ry.s / ry.r
    topr = ly.groupby(["pais", "region"]).n_resenas.sum().nlargest(8).reset_index()
    ry = ry.merge(topr[["pais", "region"]], on=["pais", "region"])
    ry["rank"] = ry.groupby("anio").rating.rank(ascending=False, method="min")
    ry["reg"] = ry.region + " (" + ry.pais.str[:2] + ")"
    fbump = px.line(ry, x="anio", y="rank", color="reg", markers=True, title="Ranking anual de las 8 regiones con más reseñas (1 = mejor rating)")
    fbump.update_yaxes(autorange="reversed", dtick=1, title="posición"); fbump.update_traces(line_width=3, marker_size=9)
    rm = c.groupby(["pais", "region"]).apply(lambda d: pd.Series({"lat": d.latitud.mean(), "lon": d.longitud.mean(), "res": d.n_resenas.sum(),
                  "rating": (d.rating_prom * d.n_ratings).sum() / d.n_ratings.sum(), "lugares": len(d)}), include_groups=False).reset_index().dropna(subset=["lat"])
    frm = px.scatter_map(rm, lat="lat", lon="lon", size="res", size_max=38, color="rating", hover_name="region", hover_data=["pais", "lugares", "res"],
                         color_continuous_scale="RdYlGn", range_color=[4.2, 4.8], title="Regiones: burbuja = reseñas · color = rating medio")
    mapa(frm, rm, "lat", "lon", 520)
    return html.Div([
        html.Div([kpi("Lugares comparables", f"{len(c):,}", f"de {len(b):,} (≥30 ratings)"),
                  kpi("Mejor lugar", top.iloc[0].nombre[:28], f"rating suavizado {top.iloc[0].rating_suavizado:.2f}", "#2fa56b"),
                  kpi("Brecha top–fondo", f"{top.rating_suavizado.mean() - bot.rating_suavizado.mean():.2f} pts" if len(c)>=30 else 'n/d', "top 15 vs últimos 15; requiere 30 lugares sin solapamiento", "#c0485a")], className="kpis"),
        note("El rating suavizado acerca a la media del grupo (país + categoría) a los lugares con pocas reseñas, para que 5 reseñas de 5★ no superen a un lugar con miles. Los lugares sin categoría 'museo' (p. ej. sitios arqueológicos) se activan en el filtro de categoría."),
        html.Div([panel(ft, 520), panel(fb, 520)], className="grid2"),
        html.Div([panel(freg, 480), panel(freg2, 480)], className="grid2"),
        html.Div([panel(fm, 560)], className="grid1"),
        html.Div([panel(frm, 520), panel(fsc, 520)], className="grid2"),
        html.Div([panel(fbump, 480)], className="grid1"),
        html.Div([html.Span("Ficha y percentil frente a pares (país + categoría)", className="h", style={"margin": "0"}),
                  html.Button("⬇ Exportar CSV", id="dl-bench-btn", className="btn")], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginTop": "22px"}),
        dcc.Download(id="dl-bench"),
        html.Div(dash_table.DataTable(tabla.to_dict("records"), [{"name": k, "id": k} for k in tabla.columns], page_size=15, filter_action="native", sort_action="native",
                 style_header={"backgroundColor": "#2c2a4a", "color": "white", "fontWeight": "700", "border": "none"},
                 style_cell={"fontFamily": "inherit", "fontSize": "13px", "padding": "8px 10px", "border": "none", "borderBottom": "1px solid #eee8de", "textAlign": "left"},
                 style_data_conditional=[{"if": {"row_index": "odd"}, "backgroundColor": "#fbf8f2"}], style_table={"overflowX": "auto"}), className="panel", style={"marginTop": "8px"}),
    ])


def page_topicos(paises, cats, rng, vol="n"):
    t = sel(TOPL, paises, cats, rng)
    if t.empty:
        return note("Sin datos de tópicos para los filtros.")
    g = t.groupby("topico", as_index=False).agg(n=("n_resenas", "sum")).sort_values("n")
    base = sel(LUG_ANIO, paises, cats, rng)
    n_texto = int(base.n_con_texto.sum())
    cobertura = fmt(g.n.sum() / n_texto if n_texto else np.nan)
    orden = g.topico.tolist()
    gp = t.groupby(["pais", "topico"], as_index=False).n_resenas.sum()
    if vol == "pct":
        gp["v"] = gp.n_resenas / gp.groupby("pais").n_resenas.transform("sum")
        f1 = px.bar(gp, x="v", y="topico", color="pais", orientation="h", barmode="group", color_discrete_map=PCOLOR,
                    title="Tópicos: % de las menciones de cada país", category_orders={"topico": orden})
        f1.update_layout(xaxis_tickformat=".0%", xaxis_title="% de menciones del país")
    else:
        f1 = px.bar(gp, x="n_resenas", y="topico", color="pais", orientation="h", color_discrete_map=PCOLOR,
                    title="Menciones por tópico (cantidad, 22 tópicos aptos)", category_orders={"topico": orden})
        f1.update_layout(xaxis_title="menciones")
    f1.update_layout(yaxis_title=None)
    h = t.groupby(["pais", "topico"], as_index=False).n_resenas.sum()
    h["cuota"] = h.n_resenas / h.groupby("pais").n_resenas.transform("sum")
    f2 = px.imshow(h.pivot(index="topico", columns="pais", values="cuota").fillna(0), aspect="auto", color_continuous_scale="Purples", title="Cuota del tópico dentro de cada país")
    f2.update_layout(coloraxis_colorbar_tickformat=".0%", yaxis_title=None)
    tt = t[t.anio > 0]
    tot_anio = tt.groupby("anio").n_resenas.sum()
    ev = tt[tt.topico.isin(g.tail(6).topico)].groupby(["anio", "topico"], as_index=False).n_resenas.sum()
    ev["cuota"] = ev.n_resenas / ev.anio.map(tot_anio)
    f3 = px.line(ev, x="anio", y="cuota", color="topico", markers=True, title="Evolución anual de los 6 tópicos principales (% de menciones)", color_discrete_sequence=PAL)
    f3.update_yaxes(tickformat=".0%"); f3.update_traces(line_width=3)
    top8 = g.tail(8).topico.tolist()
    ar = tt.assign(topico=np.where(tt.topico.isin(top8), tt.topico, "Otros tópicos")).groupby(["anio", "topico"], as_index=False).n_resenas.sum()
    far = px.area(ar, x="anio", y="n_resenas", color="topico", groupnorm="percent", title="Composición temática por año (8 principales + otros, 100 %)", color_discrete_sequence=PAL)
    far.update_layout(yaxis_title="% de menciones", xaxis_title=None)
    regs = t.groupby("region").n_resenas.sum().nlargest(12).index
    hr = t[t.region.isin(regs)].groupby(["region", "topico"], as_index=False).n_resenas.sum()
    hr["cuota"] = hr.n_resenas / hr.groupby("region").n_resenas.transform("sum")
    fhr = px.imshow(hr.pivot(index="topico", columns="region", values="cuota").fillna(0), aspect="auto", color_continuous_scale="Purples",
                    title="Cuota del tópico por región (12 regiones con más menciones)")
    fhr.update_layout(coloraxis_colorbar_tickformat=".0%", yaxis_title=None, xaxis_title=None); fhr.update_xaxes(tickangle=-40)
    ts = TSENT[TSENT.pais.isin(paises) & TSENT.categoria.isin(cats) & TSENT.anio.between(rng[0], rng[1])]
    ts = ts[ts.sentimiento.isin(["Positivo", "Neutro", "Negativo"])].groupby(["topico", "sentimiento"], as_index=False).n.sum()
    top10 = ts.groupby("topico").n.sum().nlargest(10).index
    ts = ts[ts.topico.isin(top10)]
    fsb = px.sunburst(ts, path=["topico", "sentimiento"], values="n", color="sentimiento", color_discrete_map=SENT, title="Tópico → sentimiento de la reseña (10 tópicos principales)")
    fsb.update_traces(insidetextorientation="radial")
    return html.Div([
        html.Div([kpi("Tópicos aptos", "22", "de 41; soporte de revisión IA, no validación humana"), kpi("Menciones de tópico", f"{int(g.n.sum()):,}", "tópico dominante; solo grupos habilitados", "#1f9fb5"),
                  kpi("Tópico más frecuente", g.iloc[-1].topico[:26], f"{int(g.iloc[-1].n):,} menciones", "#f2a03d")], className="kpis"),
        note(f"Cobertura temática habilitada del filtro: {cobertura} sobre {n_texto:,} reseñas con texto. No es precisión del modelo. Las restantes pueden ser outliers, textos breves, idiomas fuera de alcance o tópicos restringidos; no se borran del datamart. Etiquetas revisadas por IA sobre muestras, sin validación humana."),
        html.Div([panel(f1, 760 if vol == "pct" else 640), panel(f2, 760 if vol == "pct" else 640)], className="grid2"),
        html.Div([panel(f3, 420)], className="grid1"),
        html.Div([panel(far, 460), panel(fsb, 560)], className="grid2"),
        html.Div([panel(fhr, 700)], className="grid1"),
    ])


# ---- Mi museo ----
LUG_OPC = (LUG_ANIO.groupby(["sk_lugar", "nombre", "pais", "categoria"], as_index=False).n_resenas.sum().query("n_resenas>=10")
           .merge(LUGAR[["sk_lugar", "region"]], on="sk_lugar").sort_values("n_resenas", ascending=False))
OPCIONES = [{"label": f"{r.nombre} — {r.region}, {r.pais} ({int(r.n_resenas):,})", "value": int(r.sk_lugar)} for r in LUG_OPC.itertuples()]
DEFAULT_LUG = OPCIONES[0]["value"]


def selector(id_, extra=None):
    return html.Div([html.Div([html.Label("Institución (escriba para buscar)"), dcc.Dropdown(OPCIONES, DEFAULT_LUG, id=id_, clearable=False)], style={"flex": 4})]
                    + (extra or []), className="filters", style={"marginTop": "0"})


def page_inst():
    return html.Div([
        selector("i-lugar", [html.Div([html.Label("Comparar con"), dcc.RadioItems(
            [{"label": " Mismo país y categoría", "value": "pais"}, {"label": " Misma categoría, toda LATAM", "value": "latam"}], "pais", id="i-ambito", inline=True,
            inputStyle={"marginLeft": "12px"})], style={"flex": 3})]),
        html.Div(id="inst-out"),
    ])


@app.callback(Output("inst-out", "children"), Input("i-lugar", "value"), Input("i-ambito", "value"))
def render_inst(sk, ambito):
    me = LUG_ANIO[LUG_ANIO.sk_lugar == sk]
    info = LUGAR[LUGAR.sk_lugar == sk].iloc[0]
    peers = LUG_ANIO[(LUG_ANIO.categoria == info.categoria) & (LUG_ANIO.sk_lugar != sk)]
    if ambito == "pais":
        peers = peers[peers.pais == info.pais]
    if peers.empty:
        return note('No hay otras instituciones de la misma categoría en el ámbito elegido. Amplíe el ámbito para comparar.')
    m = agrega(me.assign(k=1), "k").iloc[0]
    pm = agrega(peers.assign(k=1), "k").iloc[0]
    sm = agrega(me[me.anio > 0], "anio"); sp = agrega(peers[peers.anio > 0], "anio")
    f1 = go.Figure()
    f1.add_scatter(x=sm.anio, y=sm.rating, name="Esta institución", mode="lines+markers", line=dict(color="#5b3f8c", width=4), marker_size=9)
    f1.add_scatter(x=sp.anio, y=sp.rating, name="Pares", mode="lines", line=dict(color="#b9b3a6", width=3, dash="dash"))
    f1.update_layout(title="Rating promedio por año vs pares"); f1.update_yaxes(range=[1, 5])
    f2 = go.Figure()
    for k, nm in (("pos", "Positivo"), ("neu", "Neutro"), ("neg", "Negativo")):
        f2.add_bar(x=sm.anio, y=sm[k], name=nm, marker_color=SENT[nm])
    f2.update_layout(barmode="stack", title="Sentimiento por año (reseñas clasificadas)")
    tm = TOPL[TOPL.sk_lugar == sk].groupby("topico").n_resenas.sum()
    tp = TOPL[TOPL.sk_lugar.isin(peers.sk_lugar.unique())].groupby("topico").n_resenas.sum()
    sh = pd.DataFrame({"yo": tm / max(m.txt, 1), "pares": tp / max(pm.txt, 1)}).fillna(0)
    sh["dif"] = sh.yo - sh.pares
    sh["n_yo"] = tm.reindex(sh.index).fillna(0)
    dd = sh[sh.n_yo >= 5].sort_values("dif")
    if len(dd) >= 2:
        dd = pd.concat([dd.head(6), dd.tail(6)])
        dd = dd[~dd.index.duplicated()]
        f3 = px.bar(dd, x="dif", y=dd.index, orientation="h", title="Tópicos: más/menos mencionados que los pares (puntos porcentuales de reseñas con texto)",
                    color=np.where(dd.dif >= 0, "Más que pares", "Menos que pares"), color_discrete_map={"Más que pares": "#1f9fb5", "Menos que pares": "#f2a03d"})
        f3.update_layout(yaxis_title=None, xaxis_tickformat=".1%", xaxis_title="diferencia vs pares", legend_title=None)
        p3 = panel(f3, 440)
    else:
        p3 = note("Tópicos: menos de 5 menciones por tópico en esta institución; no hay base suficiente para comparar.")
    # radar: percentil dentro de los pares (lugares con >=30 ratings + esta institución)
    def met(df):
        a = df.groupby("sk_lugar").agg(n=("n_resenas", "sum"), r=("n_ratings", "sum"), s=("suma_rating", "sum"), pos=("n_pos", "sum"), neu=("n_neu", "sum"),
                                       neg=("n_neg", "sum"), txt=("n_con_texto", "sum"))
        a["rating"] = a.s / a.r.replace(0, np.nan); cl = (a.pos + a.neu + a.neg).replace(0, np.nan)
        a["pos_"] = a.pos / cl; a["neg_"] = 1 - a.neg / cl; a["txt_"] = a.txt / a.n; a["vol_"] = np.log10(a.n)
        return a
    allm = met(pd.concat([peers, me]))
    base = allm[(allm.r >= 30) | (allm.index == sk)]
    cats_r = {"Rating": "rating", "% positivo": "pos_", "Pocos negativos": "neg_", "% con texto": "txt_", "Volumen": "vol_"}
    if sk in base.index and len(base) >= 10 and m.r >= 30:
        pr = [float((base[v] <= base.loc[sk, v]).mean()) for v in cats_r.values()]
        frad = go.Figure(go.Scatterpolar(r=pr + pr[:1], theta=list(cats_r) + [list(cats_r)[0]], fill="toself", line_color="#5b3f8c", fillcolor="rgba(91,63,140,.30)", name="Institución"))
        frad.add_trace(go.Scatterpolar(r=[0.5] * 6, theta=list(cats_r) + [list(cats_r)[0]], line=dict(color="#b9b3a6", dash="dash"), name="Mediana de pares"))
        frad.update_layout(title="Perfil frente a pares (percentil de 0 a 100 %)", polar=dict(radialaxis=dict(range=[0, 1], tickformat=".0%")))
        prad = panel(frad, 420)
    else:
        prad = note("Radar no disponible: menos de 30 ratings o pocos pares comparables.")
    # waterfall: descomposición exacta de la brecha de rating por nivel de estrellas
    ms = me[["n_r1", "n_r2", "n_r3", "n_r4", "n_r5"]].sum(); ps = peers[["n_r1", "n_r2", "n_r3", "n_r4", "n_r5"]].sum()
    contrib = [k * (ms.iloc[k - 1] / max(ms.sum(), 1) - ps.iloc[k - 1] / max(ps.sum(), 1)) for k in range(1, 6)]
    fwf = go.Figure(go.Waterfall(x=[f"{k}★" for k in range(1, 6)] + ["Brecha total"], measure=["relative"] * 5 + ["total"], y=contrib + [None],
                                 increasing=dict(marker_color="#2fa56b"), decreasing=dict(marker_color="#c0485a"), totals=dict(marker_color="#5b3f8c"),
                                 text=[f"{v:+.2f}" for v in contrib] + [f"{sum(contrib):+.2f}"], textposition="outside"))
    fwf.update_layout(title="Brecha de rating vs pares, explicada por nivel de estrellas", yaxis_title="puntos de rating")
    # pares más parecidos: misma región primero, luego volumen más cercano
    pl = peers.groupby("sk_lugar").agg(nombre=("nombre", "first"), region=("region", "first"), pais=("pais", "first"), n=("n_resenas", "sum"), r=("n_ratings", "sum"), s=("suma_rating", "sum"),
                                         neg=("n_neg", "sum"), pos=("n_pos", "sum"), neu=("n_neu", "sum")).reset_index()
    pl = pl[pl.r >= 30].copy()
    pl["rating"] = pl.s / pl.r.replace(0, np.nan); pl["% neg"] = pl.neg / (pl.pos + pl.neu + pl.neg).replace(0, np.nan)
    pl["dist"] = (pl.region != info.region).astype(int) * 10 + (np.log10(pl.n) - np.log10(max(m.n, 1))).abs()
    pt = pl.sort_values("dist").head(10)[["nombre", "region", "pais", "n", "rating", "% neg"]].round(3)
    pt['% neg'] = (pt['% neg'] * 100).round(1)
    pt.columns = ["Institución similar", "Región", "País", "Reseñas", "Rating", "% negativo"]
    tpares = html.Div(dash_table.DataTable(pt.to_dict("records"), [{"name": k, "id": k} for k in pt.columns], page_size=10,
                      style_header={"backgroundColor": "#2c2a4a", "color": "white", "fontWeight": "700", "border": "none"},
                      style_cell={"fontSize": "13px", "padding": "8px 10px", "border": "none", "borderBottom": "1px solid #eee8de", "textAlign": "left"},
                      style_data_conditional=[{"if": {"row_index": "odd"}, "backgroundColor": "#fbf8f2"}]), className="panel")
    ratio = m.rating - pm.rating
    rk = BENCH[BENCH.sk_lugar == sk]
    pct = "n/d" if rk.empty or pd.isna(rk.iloc[0].pct_rank_pares) else f"{rk.iloc[0].pct_rank_pares:.0%}"
    return html.Div([
        html.Div(f"{info.nombre} · {info.region}, {info.pais} · {info.categoria.replace('_', ' ')}", className="h"),
        note(f"Esta institución fue reclasificada por curaduría: {info.categoria_original.replace('_', ' ')} → {info.categoria.replace('_', ' ')}. Se compara con los pares de su nueva categoría.") if bool(info.reclasificado) else html.Div(),
        html.Div([kpi("Reseñas", f"{int(m.n):,}", f"{int(m.txt):,} con texto"),
                  kpi("Rating", fmt(m.rating, "{:.2f}"), f"pares {pm.rating:.2f} ({ratio:+.2f})" if pd.notna(ratio) else "", "#2fa56b" if (pd.notna(ratio) and ratio >= 0) else "#c0485a"),
                  kpi("Sentimiento negativo", fmt(m.pct_neg), f"pares {fmt(pm.pct_neg)}", "#c0485a"),
                  kpi("Ratings bajos", fmt(m.pct_bajo), f"pares {fmt(pm.pct_bajo)}", "#f2a03d"),
                  kpi("Percentil vs pares", pct, "rating suavizado (país + categoría)", "#1f9fb5")], className="kpis"),
        note("Menos de 30 ratings: las cifras son orientativas y no hay percentil.") if m.r < 30 else html.Div(),
        html.Div([panel(f1, 400), panel(f2, 400)], className="grid2"),
        html.Div([p3], className="grid1"),
        html.Div([prad, panel(fwf, 420)], className="grid2"),
        html.Div("Las 10 instituciones más parecidas (misma región y tamaño similar)", className="h"),
        html.Div(tpares, style={"marginTop": "8px"}),
        note(f"Ámbito temporal de esta ficha: histórico completo, incluidos años desconocidos en los totales. Pares: {peers.sk_lugar.nunique():,} lugares de la misma categoría" + (f" en {info.pais}" if ambito == "pais" else " en toda LATAM") + ". La comparación de tópicos usa solo los habilitados por revisión IA."),
    ])


# ---- Reseñas ----
def page_resenas():
    return html.Div([
        selector("r-lugar", [html.Div([html.Label("Sentimiento"), dcc.Dropdown(["Todos", "Positivo", "Neutro", "Negativo"], "Todos", id="r-sent", clearable=False)], style={"flex": 1}),
                             html.Div([html.Label("Rating"), dcc.Dropdown(["Todos", 1, 2, 3, 4, 5], "Todos", id="r-rat", clearable=False)], style={"flex": 1})]),
        html.Div(id="res-out"),
    ])


@app.callback(Output("res-out", "children"), Input("r-lugar", "value"), Input("r-sent", "value"), Input("r-rat", "value"))
def render_res(sk, sent, rat):
    sql = "SELECT TOP 300 anio,rating,sentimiento,topicos,texto_resena FROM bi.v_resena WHERE sk_lugar=%s"
    par = [sk]
    if sent != "Todos":
        sql += " AND sentimiento=%s"; par.append(sent)
    if rat != "Todos":
        sql += " AND rating=%s"; par.append(int(rat))
    sql += " ORDER BY anio DESC, sk_resena DESC"
    d = q(sql, tuple(par))
    if d.empty:
        return note("Sin reseñas con texto para este filtro.")
    d["texto_resena"] = d.texto_resena.str.slice(0, 700)
    d["topicos"] = d.topicos.fillna("—")
    d = d[["anio", "rating", "sentimiento", "topicos", "texto_resena"]]
    d.columns = ["Año", "Rating", "Sentimiento", "Tópicos (aptos)", "Comentario"]
    return html.Div([
        html.Div([html.Button("⬇ Exportar CSV", id="dl-res-btn", className="btn")], style={"textAlign": "right", "marginTop": "10px"}), dcc.Download(id="dl-res"),
        note("Hasta 300 reseñas con texto, ordenadas por año y clave técnica; no hay orden cronológico exacto dentro de cada año. Sentimiento y tópicos son automáticos; 'Año 0' = fecha no determinada. No se muestran autores."),
        html.Div(dash_table.DataTable(d.to_dict("records"), [{"name": k, "id": k} for k in d.columns], page_size=12, sort_action="native", filter_action="native",
                 style_header={"backgroundColor": "#2c2a4a", "color": "white", "fontWeight": "700", "border": "none"},
                 style_cell={"fontFamily": "inherit", "fontSize": "13px", "padding": "10px", "border": "none", "borderBottom": "1px solid #eee8de", "textAlign": "left", "whiteSpace": "normal", "height": "auto"},
                 style_cell_conditional=[{"if": {"column_id": "Comentario"}, "minWidth": "420px", "width": "50%"}, {"if": {"column_id": "Tópicos (aptos)"}, "minWidth": "180px"}],
                 style_data_conditional=[{"if": {"filter_query": '{Sentimiento} = "Negativo"', "column_id": "Sentimiento"}, "color": "#c0485a", "fontWeight": "700"},
                                         {"if": {"filter_query": '{Sentimiento} = "Positivo"', "column_id": "Sentimiento"}, "color": "#1b8a5a", "fontWeight": "700"}]),
                 className="panel", style={"marginTop": "12px"}),
    ])


@app.callback(Output("dl-bench", "data"), Input("dl-bench-btn", "n_clicks"), Input("f-pais", "value"), Input("f-cat", "value"), Input("f-anio", "value"), prevent_initial_call=True)
def dl_bench(n, paises, cats, rng):
    from dash import ctx
    if ctx.triggered_id != "dl-bench-btn":
        return None
    b = benchmark(LUG_ANIO, LUGAR, paises, cats, rng)
    b = b[b.estado_muestra == 'comparable']
    cols = ["nombre", "pais", "region", "subregion", "categoria", "n_resenas", "n_ratings", "rating_prom", "rating_suavizado", "pct_rating_bajo", "pct_neg", "pct_rank_pares"]
    return dcc.send_data_frame(b[cols].to_csv, "benchmark_museos.csv", index=False)


@app.callback(Output("dl-res", "data"), Input("dl-res-btn", "n_clicks"), Input("r-lugar", "value"), Input("r-sent", "value"), Input("r-rat", "value"), prevent_initial_call=True)
def dl_res(n, sk, sent, rat):
    from dash import ctx
    if ctx.triggered_id != "dl-res-btn":
        return None
    sql = "SELECT TOP 300 anio,rating,sentimiento,topicos,texto_resena FROM bi.v_resena WHERE sk_lugar=%s"
    par = [sk]
    if sent != "Todos":
        sql += " AND sentimiento=%s"; par.append(sent)
    if rat != "Todos":
        sql += " AND rating=%s"; par.append(int(rat))
    return dcc.send_data_frame(q(sql + " ORDER BY anio DESC, sk_resena DESC", tuple(par)).to_csv, "resenas.csv", index=False)


# ---- Metodología ----
def page_metodo():
    tot = LUG_ANIO.n_resenas.sum(); sin_rating = tot - LUG_ANIO.n_ratings.sum(); txt = LUG_ANIO.n_con_texto.sum()
    pp = LUG_ANIO.groupby("pais").agg(n=("n_resenas", "sum"), t=("n_con_texto", "sum"), lugares=("sk_lugar", "nunique")).reset_index()
    cat = LUGAR.categoria.value_counts()
    nr = TCAT[TCAT.apto == False].copy() if TCAT.apto.dtype == bool else TCAT[TCAT.apto.astype(int) == 0].copy()
    nr["lim"] = nr.limitaciones.fillna("").str.slice(0, 260)
    nr["sop"] = nr.soporte_muestral.astype(float).map(lambda v: "" if pd.isna(v) else f"{v:.0%}")
    t_nr = dash_table.DataTable(
        [{"Tópico": r.etiqueta, "Soporte en muestra": f"{r.sop} ({int(r.muestra_revisada)} textos)" if pd.notna(r.muestra_revisada) else r.sop, "Limitación documentada": r.lim} for r in nr.itertuples()],
        [{"name": c, "id": c} for c in ("Tópico", "Soporte en muestra", "Limitación documentada")], page_size=8,
        style_header={"backgroundColor": "#2c2a4a", "color": "white", "fontWeight": "700", "border": "none"},
        style_cell={"fontSize": "12.5px", "padding": "8px 10px", "border": "none", "borderBottom": "1px solid #eee8de", "textAlign": "left", "whiteSpace": "normal", "height": "auto"},
        style_cell_conditional=[{"if": {"column_id": "Limitación documentada"}, "minWidth": "420px", "width": "55%"}])
    tp = html.Table([html.Thead(html.Tr([html.Th(h) for h in ("País", "Reseñas", "Con texto", "Lugares")]))] +
                    [html.Tbody([html.Tr([html.Td(r.pais), html.Td(f"{int(r.n):,}"), html.Td(f"{r.t / r.n:.0%}"), html.Td(f"{int(r.lugares):,}")]) for r in pp.itertuples()])], className="mtab")
    sec = lambda titulo, *c: html.Div([html.H3(titulo)] + list(c), className="panel doc")
    p = html.P
    return html.Div([
        sec("Qué muestra este tablero",
            p(f"Percepción de visitantes a museos y sitios patrimoniales de Argentina, México y Perú, a partir de reseñas públicas publicadas en línea ({MILLONES} M de reseñas tras la curaduría de lugares). "
              "Combina indicadores numéricos (estrellas) con análisis automático de texto (sentimiento y tópicos). Cada cifra sale de agregados precalculados del datamart; el detalle de cada reseña se consulta aparte."),
            p(f"Cobertura actual: {int(tot):,} reseñas en {LUGAR.sk_lugar.nunique():,} lugares ({int(txt):,} con comentario escrito; {int(sin_rating):,} sin rating).")),
        sec("Cobertura y representatividad", tp,
            p("Las reseñas son opiniones autoseleccionadas: reflejan a quien decide publicar, no una muestra representativa de visitantes. La cobertura por país es muy distinta, "
              "así que conviene comparar países con cautela y usar la vista en % dentro de cada país para evitar que el volumen domine. "
              "Una reseña no equivale a una visita: este tablero no mide asistencia ni aforo, y no permite inferir causas.")),
        sec("Cómo se calculan los indicadores",
            html.Ul([
                html.Li([html.B("Rating promedio: "), "promedio de estrellas (1-5) de reseñas con rating. Tiene efecto techo (≈ 4,5): casi todo el mundo califica alto, por eso se acompaña con otros indicadores."]),
                html.Li([html.B("% de ratings bajos: "), "proporción de calificaciones de 1 o 2 estrellas."]),
                html.Li([html.B("% de sentimiento negativo / positivo: "), "sobre las reseñas clasificadas por el modelo (se excluyen las sin texto y las no clasificadas)."]),
                html.Li([html.B("Rating suavizado: "), "(suma de estrellas + 20 × media del grupo) ÷ (n.º de ratings + 20). Acerca a la media de su grupo (país + categoría) a los lugares con pocas reseñas, para que 5 reseñas de 5★ no superen a un lugar con miles."]),
                html.Li([html.B("Percentil vs pares: "), "posición del rating suavizado dentro del grupo (país + categoría), solo entre lugares con al menos 30 ratings. Los demás figuran como 'muestra insuficiente'."]),
                html.Li([html.B("Pares más parecidos: "), "misma categoría y país, priorizando la misma región y un volumen de reseñas cercano."]),
            ])),
        sec("Fechas",
            p("Las fechas son estimadas desde etiquetas relativas. Cerca del 89 % solo tiene precisión anual, por eso las series son anuales. Los registros con año desconocido se incluyen en los totales históricos de metodología, pero no en los KPI sujetos al rango de años ni en las series. "
              "Los años recientes pueden estar incompletos si el periodo todavía está en curso.")),
        sec("Sentimiento",
            p("El sentimiento lo asigna un modelo automático; no hay validación individual de cada reseña. En una revisión de 54 casos, 27 fueron compatibles con la polaridad asignada, 7 mixtos o ambiguos, "
              "1 contradicción clara, 12 abstenciones razonables y 7 con señal interpretable pero sin clasificar. Esa muestra no permite estimar una precisión poblacional: úsese como orientación de tendencias, no como medida exacta.")),
        sec("Tópicos",
            p(f"El modelo agrupa los comentarios en {len(TCAT)} tópicos. Solo {int((TCAT.apto.astype(int) == 1).sum())} están habilitados para indicadores (soporte suficiente en una revisión muestral); "
              f"los otros {len(nr)} son de uso restringido porque sus agrupaciones mezclan sentidos o contenidos. Este tablero solo usa los habilitados."),
            p("El esquema admite varios tópicos, pero este baseline exporta un único tópico dominante por reseña asignada. La revisión muestral fue realizada por IA, sin validación humana. Las menciones solo cubren los grupos habilitados, no todas las reseñas con texto. "
              "El país y la ubicación provienen siempre de la geografía del lugar, nunca del tópico."),
            html.Details([html.Summary("Ver los tópicos restringidos y sus limitaciones"), html.Div(t_nr, style={"marginTop": "10px"})])),
        sec("Lugares y categorías",
            p("Categorías de lugar: " + ", ".join(f"{k.replace('_', ' ')} ({v:,})" for k, v in cat.items()) + ". La categoría proviene del datamart; algunos nombres sugieren otra categoría o no corresponden a un museo, "
              "y están en revisión de curaduría."),
            p(texto_curaduria())),
        sec("Qué no se puede concluir",
            html.Ul([html.Li("Asistencia, aforo, ingresos o satisfacción de toda la población de visitantes: los datos son reseñas, no registros de visita."),
                     html.Li("Diferencias pequeñas entre lugares con pocas reseñas: pueden ser ruido (por eso se exige un mínimo de ratings)."),
                     html.Li("Causas: los tópicos describen de qué se habla, no por qué una experiencia es buena o mala."),
                     html.Li("Comparaciones directas entre países sin considerar la distinta cobertura y composición de categorías (p. ej., los sitios arqueológicos pesan mucho más en Perú que en Argentina).")])),
    ])


@app.callback(Output("contenido", "children"), Input("tabs", "value"), Input("f-pais", "value"), Input("f-cat", "value"), Input("f-anio", "value"), Input("f-vol", "value"))
def render(tab, paises, cats, rng, vol):
    if tab == "inst":
        return page_inst()
    if tab == "resenas":
        return page_resenas()
    if tab == "metodo":
        return page_metodo()
    if not paises or not cats:
        return note("Elija al menos un país y una categoría.")
    return {"panorama": page_panorama, "museos": page_museos, "topicos": page_topicos}[tab](paises, cats, rng, vol)


if __name__ == "__main__":
    app.run(host=os.getenv("MUSEOS_HOST", "127.0.0.1"), port=int(os.getenv("MUSEOS_PORT", "8050")), debug=False)
