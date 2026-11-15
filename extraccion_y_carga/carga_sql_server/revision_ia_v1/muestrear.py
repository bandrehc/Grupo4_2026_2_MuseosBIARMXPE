"""Reproduce la selección de revisión; consultas de lectura, sin volver a ejecutar NLP.
Las reseñas completas se guardan fuera de Git. Usa etiquetas raw, incluso después de curar destino.
"""
import sys,json,collections
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cargar

TOPIC_SQL="""WITH unique_text AS(
 SELECT d.nk_codigo,f.codigo_pais,s.hash_texto_nlp,MIN(f.sk_resena) sk
 FROM mart.fact_resena_dimension w JOIN mart.fact_resena f ON f.sk_resena=w.sk_resena
 JOIN mart.dim_dimension_latente d ON d.sk_dimension_latente=w.sk_dimension_latente
 JOIN MuseosLatam_Origen.stg.resena s ON s.id_review=f.nk_id_review
 GROUP BY d.nk_codigo,f.codigo_pais,s.hash_texto_nlp
),sampled AS(
 SELECT *,ROW_NUMBER() OVER(PARTITION BY nk_codigo,codigo_pais
 ORDER BY HASHBYTES('SHA2_256',CONCAT('revision-ia-20261023-v1|',hash_texto_nlp)),sk) rn FROM unique_text
)
SELECT s.nk_codigo,s.codigo_pais,s.rn,f.nk_id_review,f.texto_resena,f.estado_nlp,i.nk_codigo,f.rating
FROM sampled s JOIN mart.fact_resena f ON f.sk_resena=s.sk JOIN mart.dim_idioma i ON i.sk_idioma=f.sk_idioma
WHERE s.rn<=4 ORDER BY s.nk_codigo,s.codigo_pais,s.rn"""
SENTIMENT_SQL="""WITH q AS(
 SELECT f.nk_id_review,f.codigo_pais,f.texto_resena,s.nk_codigo sentimiento,f.estado_nlp,
 ROW_NUMBER() OVER(PARTITION BY f.codigo_pais,s.nk_codigo,f.estado_nlp
 ORDER BY HASHBYTES('SHA2_256',CONCAT('sentimiento-ia-v1|',f.nk_id_review))) rn
 FROM mart.fact_resena f JOIN mart.dim_sentimiento s ON s.sk_sentimiento=f.sk_sentimiento WHERE f.tiene_texto=1
)
SELECT nk_id_review,codigo_pais,texto_resena,sentimiento,estado_nlp,rn FROM q WHERE rn<=2
ORDER BY codigo_pais,sentimiento,estado_nlp,rn"""

def main():
    c=cargar.connect('MuseosLatam_Datamart')
    cat=[dict(zip(['codigo','etiqueta','palabras'],r)) for r in c.cursor().execute('SELECT codigo_topico,etiqueta,palabras_clave FROM MuseosLatam_Origen.stg.catalogo ORDER BY codigo_topico').fetchall()]
    cols=['codigo','pais','numero','id_review','texto','estado_nlp','idioma','rating']
    samples=[dict(zip(cols,r)) for r in c.cursor().execute(TOPIC_SQL).fetchall()]
    counts=[list(r) for r in c.cursor().execute('SELECT d.nk_codigo,f.codigo_pais,COUNT_BIG(*) FROM mart.fact_resena_dimension w JOIN mart.fact_resena f ON f.sk_resena=w.sk_resena JOIN mart.dim_dimension_latente d ON d.sk_dimension_latente=w.sk_dimension_latente GROUP BY d.nk_codigo,f.codigo_pais ORDER BY d.nk_codigo,f.codigo_pais').fetchall()]
    sent=[dict(zip(['id_review','pais','texto','sentimiento','estado','numero'],r)) for r in c.cursor().execute(SENTIMENT_SQL).fetchall()]
    cargar.jdump(cargar.PRIVATE/'revision_ia_muestras.json',{'catalogo':cat,'muestras':samples,'conteos':counts})
    cargar.jdump(cargar.PRIVATE/'revision_ia_sentimiento.json',sent)
    print('Muestreo reproducido:',len(samples),'casos temáticos y',len(sent),'de sentimiento')
    c.close()

if __name__=='__main__':main()
