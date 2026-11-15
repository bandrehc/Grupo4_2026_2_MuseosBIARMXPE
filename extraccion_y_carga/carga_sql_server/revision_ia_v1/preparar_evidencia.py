"""Congela las anotaciones de la revisión semántica. Las muestras completas de texto no se versionan."""
import sys,json,hashlib,collections
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cargar import PRIVATE,jdump
from contenido import TOPICOS,REVISION,MODELO,CONTEXTUALES,SENTIMIENTO
HERE=Path(__file__).resolve().parent

def main():
    raw=json.loads((PRIVATE/'revision_ia_muestras.json').read_text(encoding='utf-8'))
    assert len(TOPICOS)==41 and len(raw['muestras'])==488
    catalog=[];annotated=[]
    for i,entry in enumerate(TOPICOS):
        label,definition,include,exclude,limits,grades=entry;code=f'{MODELO}-T{i:03}'
        old=raw['catalogo'][i];assert old['codigo']==code
        sample=[r for r in raw['muestras'] if r['codigo']==code]
        for country,grade in zip(['AR','MX','PE'],grades):
            subset=[r for r in sample if r['pais']==country]
            assert len(grade)==len(subset),(i,country)
            for row,g in zip(subset,grade):
                assert g in 'CPN'
                annotated.append(dict(version_revision=REVISION,codigo_topico=code,version_modelo=MODELO,codigo_pais=country,numero=row['numero'],id_review=row['id_review'],sha256_texto=hashlib.sha256(row['texto'].encode('utf-8')).hexdigest(),juicio=g,criterio='Soporte explícito de etiqueta ORIGINAL' if g=='C' else 'Referencia general, adyacente o insuficiente para etiqueta ORIGINAL' if g=='P' else 'Sin soporte del tema ORIGINAL o interferencia contextual'))
        n=len(sample);counts=collections.Counter(''.join(grades));rate=counts['C']/n
        by_country={p:{'n':len(g),'C':g.count('C'),'P':g.count('P'),'N':g.count('N')} for p,g in zip(['AR','MX','PE'],grades)}
        eligible=rate>=2/3 and all(g.count('C')/len(g)>=0.5 for g in grades) and i not in CONTEXTUALES
        status='REVISADO_IA_SOPORTE_MUESTRAL' if eligible else 'REVISADO_IA_USO_RESTRINGIDO'
        catalog.append(dict(codigo_topico=code,version_modelo=MODELO,version_revision=REVISION,etiqueta_anterior=old['etiqueta'],etiqueta=label,
          descripcion=definition+' Incluye: '+include+' Exclusiones: '+exclude,
          criterios_inclusion=include,criterios_exclusion=exclude,limitaciones=limits,palabras_clave=old['palabras'],validacion_etiqueta=status,
          apto_analisis_tematico=eligible,muestra_n=n,coherentes_n=counts['C'],parciales_n=counts['P'],no_coherentes_n=counts['N'],soporte_muestral=rate,
          detalle_paises=by_country,riesgo_contextual=i in CONTEXTUALES,
          metodo_revision='Lectura semántica por agente IA; muestreo determinista de textos únicos por tópico y país; no validación humana',
          criterio_uso='C/n >= 2/3 global, C/n >= 1/2 en cada país y sin riesgo contextual grave; diagnóstico muestral, no exactitud poblacional'))
    assert len(annotated)==488
    sentiment=json.loads((PRIVATE/'revision_ia_sentimiento.json').read_text(encoding='utf-8'));assert len(sentiment)==len(SENTIMIENTO)==54
    sentiment_out=[]
    meanings={'C':'Compatible con polaridad textual','P':'Mixto o ambiguo; no confirma una polaridad única','N':'Polaridad incompatible con la interpretación del agente','A':'Abstención razonable o señal insuficiente','S':'Señal interpretable que el pipeline dejó sin clasificar'}
    for i,(r,g) in enumerate(zip(sentiment,SENTIMIENTO),1):
        sentiment_out.append(dict(numero=i,id_review=r['id_review'],codigo_pais=r['pais'],sentimiento_original=r['sentimiento'],estado_original=r['estado'],sha256_texto=hashlib.sha256(r['texto'].encode('utf-8')).hexdigest(),juicio=g,dictamen=meanings[g],accion='Conservar predicción original; registrar diagnóstico, sin extrapolar corrección al corpus'))
    jdump(HERE/'catalogo_curado.json',catalog);jdump(HERE/'evaluaciones_topicos.json',annotated);jdump(HERE/'evaluaciones_sentimiento.json',sentiment_out)
    manifest={'version_revision':REVISION,'version_modelo':MODELO,'revisor':'Agente IA Codex','validacion_humana':False,
      'autorizacion':'Usuario autorizó revisión por IA sin validación humana en esta conversación',
      'semilla_muestreo':'revision-ia-20261023-v1| + hash_texto_nlp; SHA2_256 en SQL Server',
      'muestreo':'Hasta 4 textos únicos por tópico y país. Sin exigir presencia de palabras clave. Menos de 4 cuando no hay más textos únicos.',
      'exclusion_entrenamiento':'No verificada; no se afirma conjunto externo al entrenamiento ni prueba ciega independiente.',
      'juicios':'C/P/N respecto a etiqueta ORIGINAL; las nuevas descripciones no se usan para inflar el puntaje.',
      'muestras_topicos':488,'muestras_sentimiento':54,'topicos':41,'uso_habilitado':sum(r['apto_analisis_tematico'] for r in catalog),
      'uso_restringido':sum(not r['apto_analisis_tematico'] for r in catalog),
      'archivos':{f:hashlib.sha256((HERE/f).read_bytes()).hexdigest() for f in ['catalogo_curado.json','evaluaciones_topicos.json','evaluaciones_sentimiento.json','contenido.py']}}
    jdump(HERE/'manifiesto_revision.json',manifest)
    print(json.dumps({k:v for k,v in manifest.items() if k in ['topicos','muestras_topicos','muestras_sentimiento','uso_habilitado','uso_restringido']},ensure_ascii=False))

if __name__=='__main__':main()
