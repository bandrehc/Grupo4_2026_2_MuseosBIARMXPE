"""Genera el diccionario físico (DICCIONARIO_SQL_SERVER.md) desde sys.columns y la trazabilidad de campos CSV."""
import csv,json
from cargar import HERE,connect

REVIEW_MAP={
 'google_place_id':'mart.dim_lugar.nk_place_id (lookup con país)',
 'id_review':'mart.fact_resena.nk_id_review', 'caption':'mart.fact_resena.texto_resena',
 'codigo_pais':'mart.fact_resena.codigo_pais', 'pais':'mart.dim_geografia.pais_nombre (desde lugar)',
 'pais_iso3':'mart.dim_geografia.pais_iso3 (desde lugar)',
 'clave_lugar':'mart.dim_lugar.clave_lugar → fact_resena.sk_lugar',
 'cantidad_palabras':'mart.fact_resena.cantidad_palabras', 'tiene_texto':'mart.fact_resena.tiene_texto',
 'n_resenas_autor_asof':'mart.fact_resena.n_resenas_autor_asof',
 'segmento_perfil_autor':'mart.dim_perfil_autor → fact_resena.sk_perfil_autor',
 'segmento_extension':'mart.dim_extension_resena → fact_resena.sk_extension_resena',
 'segmento_antiguedad':'mart.dim_antiguedad_resena → fact_resena.sk_antiguedad_resena',
 'segmento_presencia_digital':'mart.dim_presencia_digital → fact_resena.sk_presencia_digital',
 'periodo_codigo':'mart.dim_tiempo.sk_periodo → fact_resena.sk_periodo',
 'precision_fecha_resena':'mart.fact_resena.precision_fecha_resena',
 'codigo_idioma':'mart.dim_idioma.nk_codigo → fact_resena.sk_idioma',
 'sentimiento':'mart.dim_sentimiento.nk_codigo → fact_resena.sk_sentimiento',
 'rating':'mart.fact_resena.rating; mart.dim_rating (vacío a desconocido/medida NULL)',
 'topico_dominante':'conciliado con stg.puente y fact_resena_dimension; no crear puente desde texto',
 'banderas_calidad':'aud.incidencia y origen literal',
 **{k:'mart.fact_resena.'+k for k in ['puntaje_sentimiento','confianza_sentimiento','p_negativo','p_neutro','p_positivo','estado_nlp','estado_topicos','version_modelo_sentimiento','version_modelo_topicos']}}
PLACE_MAP={
 'clave_lugar':'mart.dim_lugar.clave_lugar','id':'mart.dim_lugar.nk_place_id',
 'title':'mart.dim_lugar.nombre','codigo_pais':'mart.dim_lugar.codigo_pais; mart.dim_geografia.codigo_pais',
 'pais':'mart.dim_geografia.pais_nombre','pais_iso3':'mart.dim_geografia.pais_iso3',
 'categoria_normalizada':'mart.dim_lugar.categoria_normalizada','lat':'mart.dim_lugar.latitud','lon':'mart.dim_lugar.longitud',
 'departamento_final':'mart.dim_geografia.nivel1_nombre','provincia_final':'mart.dim_geografia.nivel2_nombre','distrito_final':'mart.dim_geografia.nivel3_nombre','inei_real':'mart.dim_geografia.codigo_nativo',
 'stars':'mart.fact_reputacion_lugar.rating_promedio_google','reviews':'mart.fact_reputacion_lugar.n_valoraciones_google',
 'fecha_observacion_reputacion':'mart.fact_reputacion_lugar.fecha_observacion (NULL)',
 'precision_observacion_reputacion':'mart.fact_reputacion_lugar.precision_observacion',
 **{k:'mart.dim_lugar.tiene_sitio_web; mart.dim_presencia_digital (presencia declarada)' for k in ['domain','url']},
 **{k:'mart.dim_lugar.tiene_telefono; mart.dim_presencia_digital (contacto declarado)' for k in ['phoneNumber','completePhoneNumber']}}
DESCRIPTIONS={
 'version_revision':'Versión de la revisión semántica aplicada al catálogo de tópicos.',
 'criterios_inclusion':'Contenido que corresponde al tópico.',
 'criterios_exclusion':'Contenido que no corresponde al tópico.',
 'limitaciones':'Ambigüedades detectadas en la muestra revisada.',
 'apto_analisis_tematico':'1 si el tópico se usa en los indicadores temáticos (22 de 41).',
 'muestra_revisada':'Casos de la muestra revisados para el tópico.',
 'soporte_muestral':'Proporción de casos de la muestra con soporte explícito de la etiqueta (C/n).',
 'metodo_revision':'Procedimiento de la revisión semántica por muestreo.',
 'source_row':'Número de registro en el CSV de origen, desde 1.',
 'hash_fila':'SHA-256 de los valores originales del registro.',
 'hash_fuente':'SHA-256 del archivo fuente.',
 'codigo_pais':'Código ISO alfa-2 del país: PE, MX o AR.',
 'pais_iso3':'Código ISO alfa-3: PER, MEX o ARG.', 'pais_nombre':'Nombre del país.',
 'nk_geografia':'Hash SHA-256 de país, niveles y código nativo (clave natural técnica).',
 'clave_lugar':'País y Google Place ID unidos por dos puntos.',
 'nk_place_id':'Google Place ID (distingue mayúsculas).',
 'nk_id_review':'Identificador de la reseña en Google Maps.',
 'nombre':'Nombre del museo o sitio en la ficha (puede repetirse).',
 'categoria_normalizada':'Categoría analítica del lugar.',
 'latitud':'Latitud decimal WGS84.',
 'longitud':'Longitud decimal WGS84.',
 'tiene_sitio_web':'1 si la ficha declara dominio o URL.',
 'tiene_telefono':'1 si la ficha declara teléfono.',
 'es_vigente':'Versión vigente de la ficha.',
 'version':'Versión de la ficha observada.',
 'hash_atributos':'Hash de los atributos de la ficha.',
 'version_fuente':'Versión técnica del corpus cargado.',
 'valido_desde':'Inicio de vigencia de la ficha.',
 'valido_hasta':'Fin de vigencia de la ficha.',
 'anio':'Año estimado de la reseña; NULL si se desconoce.', 'trimestre':'Trimestre 1–4; NULL si el mes se desconoce.',
 'mes':'Mes 1–12; 0 si se desconoce el mes; NULL en el período -1.',
 'mes_nombre':'Nombre del mes.', 'anio_mes':'AAAA-MM, AAAA-00 si el mes se desconoce o 0000-00.',
 'es_mes_determinado':'1 si el mes de la reseña es conocido.',
 'etapa':'PREPANDEMIA hasta 2019, PANDEMIA 2020–2021, POSPANDEMIA desde 2022, o desconocida.',
 'nk_codigo':'Código natural del miembro de la dimensión.',
 'etiqueta':'Etiqueta legible.',
 'descripcion':'Definición del tópico.',
 'palabras_clave':'Términos más representativos del tópico.',
 'version_modelo':'Versión del modelo de tópicos.',
 'metodo':'Método de modelado de tópicos (S-BERT + BERTopic).',
 'validacion_etiqueta':'Resultado de la revisión semántica: soporte muestral o uso restringido.',
 'resenas_min':'Límite inferior de reseñas publicadas por el autor.',
 'resenas_max':'Límite superior; NULL en el tramo abierto.',
 'palabras_min':'Límite inferior de palabras del tramo de extensión.',
 'palabras_max':'Límite superior; NULL en el tramo abierto.',
 'anios_min':'Límite inferior de antigüedad de la reseña, en años.',
 'anios_max':'Límite superior; NULL en el tramo abierto.',
 'nk_rating':'Estrellas 1–5; NULL en el miembro desconocido.',
 'es_positiva':'Rating 4–5.', 'es_negativa':'Rating 1–2.', 'es_neutra':'Rating 3.',
 'polaridad':'-1 negativo, 0 neutro, 1 positivo; NULL si no hay clasificación.',
 'es_texto_analizable':'1 si la reseña tiene sentimiento negativo, neutro o positivo.',
 'rating':'Estrellas 1–5; NULL si la reseña no tiene calificación. Promedio = SUM(rating)/COUNT(rating).',
 'cantidad_palabras':'Número de palabras del texto; 0 sin texto.',
 'n_resenas_autor_asof':'Reseñas publicadas por el autor al extraer; NULL en 24 casos ambiguos.',
 'puntaje_sentimiento':'Puntaje del modelo de sentimiento en [-1, 1].',
 'confianza_sentimiento':'Confianza del modelo de sentimiento.',
 'p_negativo':'Probabilidad de la clase negativa.', 'p_neutro':'Probabilidad de la clase neutra.', 'p_positivo':'Probabilidad de la clase positiva.',
 'tiene_texto':'1 si la reseña tiene texto.',
 'precision_fecha_resena':'Precisión de la fecha estimada: DIA, SEMANA, MES, ANIO o NA.',
 'texto_resena':'Texto completo de la reseña.',
 'estado_nlp':'Estado del análisis de sentimiento (OK, baja confianza, sin texto, etc.).',
 'estado_topicos':'Estado de la asignación de tópico (asignado, outlier, fuera de alcance).',
 'version_modelo_sentimiento':'Versión del modelo de sentimiento.',
 'version_modelo_topicos':'Versión del modelo de tópicos.',
 'peso':'Peso de la pertenencia al tópico.',
 'es_dominante':'1 si es el tópico dominante de la reseña.',
 'rating_promedio_google':'Estrellas publicadas en la ficha de Google Maps.',
 'n_valoraciones_google':'Número de valoraciones publicado en la ficha.',
 'fecha_observacion':'Fecha de observación de la reputación.',
 'precision_observacion':'Precisión de la fecha de observación.',
 'codigo_nativo':'Código geográfico oficial (UBIGEO en Perú, geoBoundaries en México y Argentina).',
 'sistema_codigo':'INEI_UBIGEO en PE; GEOBOUNDARIES_ADM2 en MX y AR.',
}
FK_TARGET={'sk_periodo':'dim_tiempo','sk_resena':'fact_resena'}
STG_FILE={'resena':'base_madre_resenas.csv','lugar':'base_madre_lugares.csv','catalogo':'catalogo_dimensiones_latentes.csv','puente':'resena_dimension_latente.csv'}
HEADER=['# Diccionario físico SQL Server','',
 'Generado desde `sys.columns` con `documentar.py`. Trazabilidad de cada columna CSV hasta su destino: `mapa_campos.csv`.','',
 '- **MuseosLatam_Datamart** (sección 1): esquema del datamart entregado en el respaldo `.bak`, con 3 hechos y 10 dimensiones; cada dimensión tiene un miembro -1 (desconocido).',
 '- **MuseosLatam_Origen** (sección 2): base de origen de la carga (`stg` literal, `curado`, `aud`); no forma parte del respaldo entregado.','']

def describe(schema,table,col,identity,profile):
    if col.startswith('sk_'):
        if col=='sk_periodo' and table=='dim_tiempo':return 'Clave primaria del período: AAAAMM, AAAA00 (año sin mes) o -1.'
        if identity or col=='sk_'+table.removeprefix('dim_'):return 'Clave sustituta.'
        return 'Clave foránea a '+FK_TARGET.get(col,'dim_'+col[3:])+'.'
    if schema=='stg' and col in profile[STG_FILE[table]]['headers']:return 'Valor literal del CSV (ver mapa_campos.csv).'
    if col.startswith('nivel') and col.endswith('_nombre'):return 'Nombre de la división administrativa; NULL si el país no tiene ese nivel.'
    if col.startswith('nivel') and col.endswith('_tipo'):return 'Tipo de división administrativa según el país.'
    return DESCRIPTIONS.get(col) or ('Campo de auditoría de '+table+'.' if schema=='aud' else 'Campo técnico de '+table+'.')

def sql_type(typ,length,precision,scale):
    if typ in ['varchar','char','nvarchar','nchar','binary','varbinary']:return typ+f'({"MAX" if length==-1 else length//2 if typ.startswith("n") else length})'
    if typ in ['decimal','numeric']:return typ+f'({precision},{scale})'
    return typ

def section(db,rows,profile):
    """rows: (schema, table, columna, tipo, admite_null, es_identity) en orden de columna."""
    lines=[];last=None
    for schema,table,col,typ,nullable,identity in rows:
        if (schema,table)!=last:
            lines+=['','### '+db+'.'+schema+'.'+table,'','| Campo | Tipo | NULL | Descripción |','|---|---|---|---|'];last=(schema,table)
        lines.append(f'| {col} | {typ} | {"Sí" if nullable else "No"} | {describe(schema,table,col,identity,profile)} |')
    return lines

def columns(db):
    c=connect(db)
    cur=c.cursor().execute("SELECT s.name,t.name,col.name,ty.name,col.max_length,col.precision,col.scale,col.is_nullable,col.is_identity FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id JOIN sys.columns col ON col.object_id=t.object_id JOIN sys.types ty ON ty.user_type_id=col.user_type_id WHERE s.name IN ('stg','curado','aud','mart') ORDER BY s.name,t.name,col.column_id")
    rows=[(s,t,col,sql_type(ty,l,p,sc),n,i) for s,t,col,ty,l,p,sc,n,i in cur.fetchall()];c.close()
    return rows

def render(origen,datamart,profile):
    return '\n'.join(HEADER+['## 1. MuseosLatam_Datamart (datamart entregado)']+section('MuseosLatam_Datamart',datamart,profile)
                     +['','## 2. MuseosLatam_Origen (base de origen de la carga)']+section('MuseosLatam_Origen',origen,profile))+'\n'

def main():
    profile=json.loads((HERE/'perfil_fuentes.json').read_text(encoding='utf-8'))
    with (HERE/'mapa_campos.csv').open('w',encoding='utf-8-sig',newline='') as s:
        writer=csv.writer(s);writer.writerow(['archivo','campo_fuente','origen_literal','destino_analitico_o_auditoria','regla'])
        for file,raw in [('base_madre_resenas.csv','resena'),('base_madre_lugares.csv','lugar'),('catalogo_dimensiones_latentes.csv','catalogo'),('resena_dimension_latente.csv','puente')]:
            for col in profile[file]['headers']:
                dest=(REVIEW_MAP if raw=='resena' else PLACE_MAP if raw=='lugar' else {}).get(col)
                if raw=='catalogo':dest='Conservado en stg.catalogo.idioma para auditoría' if col=='idioma' else 'mart.dim_dimension_latente.'+{'codigo_topico':'nk_codigo'}.get(col,col)
                if raw=='puente':dest={'id_review':'lookup FACT_RESENA.sk_resena','codigo_topico':'lookup DIM_DIMENSION_LATENTE.sk_dimension_latente','version_modelo':'lookup compuesto con codigo_topico','peso':'mart.fact_resena_dimension.peso','es_dominante':'mart.fact_resena_dimension.es_dominante'}[col]
                rule='Literal en origen; conversión derivada explícita solo en destino.'
                if not dest:dest='Conservado en origen para trazabilidad; no se duplica como medida/dimensión.'
                if raw=='resena' and col in ['museo_stars','museo_reviews']:rule='Nunca alimentar reputación desde esta columna repetida; usar base_madre_lugares.'
                writer.writerow([file,col,'MuseosLatam_Origen.stg.'+raw+'.'+col,dest,rule])
    (HERE/'DICCIONARIO_SQL_SERVER.md').write_text(render(columns('MuseosLatam_Origen'),columns('MuseosLatam_Datamart'),profile),encoding='utf-8')

if __name__=='__main__':main()
