"""Controles SQL de solo lectura. No restaura ni depura bases. Produce evidencia fechada."""
import argparse
import datetime
import json
import os
from pathlib import Path

QUERIES = {
    'conteos': "SELECT (SELECT COUNT_BIG(*) FROM mart.fact_resena) resenas,(SELECT COUNT_BIG(*) FROM mart.fact_resena_dimension) puente,(SELECT COUNT_BIG(*) FROM mart.fact_reputacion_lugar) reputaciones,(SELECT COUNT(*) FROM sys.tables WHERE schema_id=SCHEMA_ID('mart') AND name LIKE 'dim[_]%') dimensiones",
    'control_bi': 'SELECT * FROM bi.v_control_reconciliacion',
    'duplicados_resena': 'SELECT COUNT_BIG(*) n FROM (SELECT nk_id_review FROM mart.fact_resena GROUP BY nk_id_review HAVING COUNT_BIG(*)>1) d',
    'duplicados_puente': 'SELECT COUNT_BIG(*) n FROM (SELECT sk_resena,sk_dimension_latente FROM mart.fact_resena_dimension GROUP BY sk_resena,sk_dimension_latente HAVING COUNT_BIG(*)>1) d',
    'multitopico': 'SELECT COUNT_BIG(*) n FROM (SELECT sk_resena FROM mart.fact_resena_dimension GROUP BY sk_resena HAVING COUNT_BIG(*)>1) d',
    'rating_null': 'SELECT COUNT_BIG(*) n FROM mart.fact_resena WHERE rating IS NULL',
    'huérfanos_puente': 'SELECT COUNT_BIG(*) n FROM mart.fact_resena_dimension w LEFT JOIN mart.fact_resena r ON r.sk_resena=w.sk_resena LEFT JOIN mart.dim_dimension_latente d ON d.sk_dimension_latente=w.sk_dimension_latente WHERE r.sk_resena IS NULL OR d.sk_dimension_latente IS NULL',
    'cobertura': 'SELECT l.pais,SUM(CONVERT(bigint,a.n_resenas)) resenas,SUM(CONVERT(bigint,a.n_con_texto)) con_texto,SUM(CONVERT(bigint,a.n_pos+a.n_neu+a.n_neg)) clasificados FROM bi.agg_lugar_anio a JOIN bi.lugar l ON l.sk_lugar=a.sk_lugar GROUP BY l.pais',
    'temas_habilitados': 'SELECT l.pais,SUM(CONVERT(bigint,a.n_resenas)) menciones FROM bi.agg_lugar_topico_anio a JOIN bi.lugar l ON l.sk_lugar=a.sk_lugar GROUP BY l.pais',
    'sin_fecha': 'SELECT SUM(CONVERT(bigint,n_resenas)) n FROM bi.agg_lugar_anio WHERE anio=0',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--salida', default='evidencias_locales/control_entrega.json')
    args = parser.parse_args()
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bi'))
    from cargar_decisiones import conectar
    results = {}
    c = conectar()
    try:
        cur = c.cursor(as_dict=True)
        for name, sql in QUERIES.items():
            cur.execute(sql); results[name] = cur.fetchall()
    finally: c.close()
    counts = results['conteos'][0]
    checks = {'conteos': counts['resenas']==1143877 and counts['puente']==233556 and counts['reputaciones']==6286,
              'dimensiones_minimo_8':counts['dimensiones']>=8,
              'reconciliacion':results['control_bi'][0]['ok']==1,
              'decisiones_no_huerfanas':results['control_bi'][0]['decisiones_huerfanas']==0,
              'ratings_null':results['rating_null'][0]['n']==945}
    for name in ('duplicados_resena','duplicados_puente','multitopico','huérfanos_puente'):
        checks[name] = results[name][0]['n']==0
    report = dict(estado='SQL_VERIFICADO' if all(checks.values()) else 'SQL_CON_FALLOS',
                  utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), checks=checks, results=results,
                  aviso='No valida semántica humana, integridad completa del motor ni pruebas UI. No se modificó la base.')
    target=Path(args.salida);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(dict(estado=report['estado'],checks=checks,informe=str(target)),ensure_ascii=False,indent=2))
    raise SystemExit(0 if all(checks.values()) else 1)


if __name__=='__main__': main()
