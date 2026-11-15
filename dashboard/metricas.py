"""Métricas puras: no abre SQL ni carga Dash. Benchmark del período seleccionado."""
import numpy as np


def benchmark(agregados, lugares, paises, categorias, periodo):
    if lugares.sk_lugar.duplicated().any():
        raise ValueError('Metadatos de lugar duplicados: lookup no es uno a uno')
    datos = agregados[agregados.pais.isin(paises or []) &
                      agregados.categoria.isin(categorias or []) &
                      agregados.anio.between(*periodo)]
    columnas = ['n_resenas', 'n_ratings', 'suma_rating', 'n_rating_neg', 'n_pos', 'n_neu', 'n_neg']
    t = datos.groupby('sk_lugar')[columnas].sum().reset_index()
    b = lugares.merge(t, on='sk_lugar', how='inner', validate='one_to_one')
    grupo = b.groupby(['pais', 'categoria'])
    media = grupo.suma_rating.transform('sum') / grupo.n_ratings.transform('sum').replace(0, np.nan)
    b['media_grupo'] = media
    b['rating_prom'] = b.suma_rating / b.n_ratings.replace(0, np.nan)
    b['rating_suavizado'] = (b.suma_rating + 20 * media) / (b.n_ratings + 20)
    b['pct_rating_bajo'] = b.n_rating_neg / b.n_ratings.replace(0, np.nan)
    clasificados = (b.n_pos + b.n_neu + b.n_neg).replace(0, np.nan)
    b['pct_pos'] = b.n_pos / clasificados
    b['pct_neg'] = b.n_neg / clasificados
    b['pct_rank_pares'] = np.nan
    aptos = b[b.n_ratings >= 30]
    grupos = aptos.groupby(['pais', 'categoria'])
    rango = grupos.rating_suavizado.rank(method='min') - 1
    n = grupos.rating_suavizado.transform('count')
    # SQL PERCENT_RANK devuelve cero cuando solo existe un miembro.
    b.loc[aptos.index, 'pct_rank_pares'] = (rango / (n - 1).replace(0, np.nan)).fillna(0)
    b['estado_muestra'] = np.where(b.n_ratings >= 30, 'comparable', 'muestra insuficiente (<30 ratings)')
    return b
