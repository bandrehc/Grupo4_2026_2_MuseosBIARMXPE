"""Carga local reproducible PE/MX/AR. Python 3.12 + pyodbc 5.3, SQL Server 2019.
No ejecuta scraping/NLP, no borra datos ni cambia seguridad del servidor.
"""
import argparse
import csv
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import sys
import time
import traceback
from datetime import datetime, timezone
import pyodbc

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ROOT = REPO.parent
FINAL = REPO / 'data/preparacion_latam/ampliacion_2026-10-22_v1/final'
PRIVATE = Path(os.environ['LOCALAPPDATA']) / 'MuseosLatamSQL'
PRIVATE.mkdir(parents=True, exist_ok=True)
VERSION = 'latam-ampliacion-2026-10-22-v1'
OWNER = 'MuseosLatamSQL-20261023-v1'
FILES = {'lugar':'base_madre_lugares.csv', 'resena':'base_madre_resenas.csv',
         'catalogo':'catalogo_dimensiones_latentes.csv','puente':'resena_dimension_latente.csv'}
KEYS = {'lugar':['clave_lugar'], 'resena':['id_review'],
        'catalogo':['codigo_topico','version_modelo'], 'puente':['id_review','codigo_topico','version_modelo']}
BATCH = 1000

def jdump(path, value):
    tmp = path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    tmp.replace(path)

def progress(phase, **kw):
    value = dict(phase=phase,updated=datetime.now(timezone.utc).isoformat(),pid=os.getpid(),**kw)
    jdump(PRIVATE/'progreso.json',value)
    print(json.dumps(value,ensure_ascii=False,default=str),flush=True)

def stopped():
    if (PRIVATE/'stop.request').exists():
        raise InterruptedError('Parada segura solicitada; checkpoints confirmados conservados')

def connect(db='master',autocommit=False):
    cfg=json.loads(Path(os.environ.get('MUSEOS_SQL_CONFIG',PRIVATE/'connection.json')).read_text(encoding='utf-8'))
    server=cfg['server']
    if not (server.lower().startswith(('localhost','lpc:localhost'))):
        raise ValueError('Esta implementación solo autoriza la instancia local')
    pwd=cfg['password'].replace('}','}}')
    return pyodbc.connect(f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={db};UID={cfg["user"]};PWD={{{pwd}}};Encrypt=yes;TrustServerCertificate=yes;APP=MuseosLatamSQL',timeout=15,autocommit=autocommit)

def scalar(c,sql,*params):
    return c.cursor().execute(sql,*params).fetchone()[0]

def execute_script(c,text):
    for batch in re.split(r'^\s*GO\s*$',text,flags=re.M|re.I):
        if batch.strip():
            cur=c.cursor().execute(batch)
            while cur.nextset(): pass

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as s:
        for b in iter(lambda:s.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()

def digest(values):
    return hashlib.sha256(json.dumps(list(values),ensure_ascii=False,separators=(',',':')).encode('utf-8')).digest()

def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as s:
        reader=csv.DictReader(s)
        for r in reader:
            if None in r or any(v is None for v in r.values()):raise ValueError('CSV mal formado: '+path.name)
            yield r

def verify_files():
    val=json.loads((FINAL/'validacion_final.json').read_text(encoding='utf-8-sig'))
    result={}
    for x in val['outputs']:
        actual=sha(FINAL/x['file'])
        assert actual==x['sha256'],x['file']+' SHA no coincide'
        result[x['file']]=x
    return result

CONTROL = """
CREATE SCHEMA aud;
GO
CREATE TABLE aud.propiedad (propietario varchar(80) NOT NULL PRIMARY KEY);
INSERT aud.propiedad VALUES ('MuseosLatamSQL-20261023-v1');
CREATE TABLE aud.fuente (tabla varchar(40) PRIMARY KEY,version varchar(80) NOT NULL,sha256 char(64) NOT NULL,filas bigint NOT NULL,encabezados nvarchar(max) NOT NULL);
CREATE TABLE aud.lote (fase varchar(40) NOT NULL,tabla varchar(40) NOT NULL,sha256 char(64) NOT NULL,inicio bigint NOT NULL,fin bigint NOT NULL,filas bigint NOT NULL,hash_lote binary(32) NULL,confirmado datetime2 NOT NULL DEFAULT SYSUTCDATETIME(),PRIMARY KEY(fase,tabla,inicio));
CREATE TABLE aud.ejecucion (id bigint IDENTITY PRIMARY KEY,inicio datetime2 NOT NULL DEFAULT SYSUTCDATETIME(),fin datetime2 NULL,estado varchar(40) NOT NULL,informe nvarchar(max) NULL);
CREATE TABLE aud.incidencia (tabla varchar(40) NOT NULL,source_row bigint NOT NULL,regla nvarchar(100) NOT NULL,detalle nvarchar(max) NOT NULL,PRIMARY KEY(tabla,source_row,regla));
"""

def ensure_db(master,name):
    assert re.fullmatch(r'[A-Za-z0-9_]+',name)
    if scalar(master,'SELECT COUNT(*) FROM sys.databases WHERE name=?',name):
        c=connect(name)
        try:owner=scalar(c,'SELECT propietario FROM aud.propiedad')
        except Exception:
            c.close();raise RuntimeError('Colisión de base ajena: '+name)
        c.close()
        if owner!=OWNER:raise RuntimeError('Propietario incompatible: '+name)
        return
    master.execute(f'CREATE DATABASE [{name}] COLLATE Latin1_General_100_BIN2')
    master.execute(f'ALTER DATABASE [{name}] SET RECOVERY SIMPLE')
    c=connect(name)
    execute_script(c,CONTROL);c.commit();c.close()

def raw_ddl(profile):
    sql=['CREATE SCHEMA stg;','GO']
    for table,file in FILES.items():
        p=profile[file]
        defs=['source_row bigint NOT NULL PRIMARY KEY','hash_fila binary(32) NOT NULL','hash_fuente char(64) NOT NULL']
        for col in p['headers']:
            size=p['max_utf16'].get(col,0)
            typ='nvarchar(max)' if col=='caption' or size>1000 else f'nvarchar({max(16,size+16)})'
            defs.append(f'[{col}] {typ} COLLATE Latin1_General_100_BIN2 NOT NULL')
        defs.append('UNIQUE ('+','.join('['+k+']' for k in KEYS[table])+')')
        sql.append(f'CREATE TABLE stg.{table} ('+',\n'.join(defs)+');')
    return '\n'.join(sql)

def init_origin(c,profile):
    sql=raw_ddl(profile)
    (HERE/'01_origen.sql').write_text(CONTROL+'\n'+sql,encoding='utf-8')
    if not scalar(c,"SELECT COUNT(*) FROM sys.tables WHERE name='resena' AND schema_id=SCHEMA_ID('stg')"):
        execute_script(c,sql);c.commit()

def checkpoint(c,phase,table,start,end,source_hash,n,h=None):
    c.execute('INSERT aud.lote(fase,tabla,sha256,inicio,fin,filas,hash_lote) VALUES(?,?,?,?,?,?,?)',phase,table,source_hash,start,end,n,h)

def existing(c,phase,table):
    return {r[0]:r[1] for r in c.cursor().execute('SELECT inicio,fin FROM aud.lote WHERE fase=? AND tabla=?',phase,table)}

def commit_checked(c,db,phase,table,start):
    try:c.commit()
    except pyodbc.Error:
        # Nunca repetir un commit incierto sin consultar el checkpoint en otra conexión.
        probe=connect(db)
        found=scalar(probe,'SELECT COUNT(*) FROM aud.lote WHERE fase=? AND tabla=? AND inicio=?',phase,table,start)
        probe.close()
        if found:raise RuntimeError('Commit confirmado tras pérdida de conexión. Reanudar comando para abrir una sesión nueva.')
        raise

def load_origin(c,db,profile,sources,pilot=False):
    selected=json.loads((PRIVATE/'pilot_samples.json').read_text(encoding='utf-8')) if pilot else None
    ids={r['id_review'] for r in selected} if pilot else None
    for table,file in FILES.items():
        stopped();headers=profile[file]['headers'];source_hash=sources[file]['sha256']
        old=c.cursor().execute('SELECT sha256 FROM aud.fuente WHERE tabla=?',table).fetchone()
        if old and old[0]!=source_hash:raise ValueError('Fuente cambió: crear versión nueva sin mezclar checkpoints')
        dataset=(selected if table=='resena' and pilot else rows(FINAL/file))
        if table=='puente' and pilot:dataset=(r for r in dataset if r['id_review'] in ids)
        done=existing(c,'origen',table)
        if not old:
            c.execute('INSERT aud.fuente VALUES(?,?,?,?,?)',table,VERSION,source_hash,profile[file]['rows'] if not pilot else -1,json.dumps(headers));c.commit()
        it=iter(dataset);start=1
        while True:
            batch=list(itertools.islice(it,BATCH))
            if not batch:break
            end=start+len(batch)-1
            if start in done:
                assert done[start]==end
                assert scalar(c,f'SELECT COUNT(*) FROM stg.{table} WHERE source_row BETWEEN ? AND ?',start,end)==len(batch)
                start=end+1;continue
            stopped();prepared=[];batch_hash=hashlib.sha256()
            for n,r in enumerate(batch,start):
                values=[r[k] for k in headers];h=digest(values);batch_hash.update(h)
                prepared.append((n,h,source_hash,*values))
            cur=c.cursor();cur.fast_executemany=True
            # Los tamaños de búfer se miden en unidades UTF-16, incluido Unicode suplementario.
            sizes=[(pyodbc.SQL_BIGINT,0,0),(pyodbc.SQL_BINARY,32,0),(pyodbc.SQL_CHAR,64,0)]
            for k in headers:
                capacity=max(1,max(len(r[k].encode('utf-16-le'))//2 for r in batch))
                sizes.append((pyodbc.SQL_WLONGVARCHAR if capacity>4000 else pyodbc.SQL_WVARCHAR,capacity,0))
            cur.setinputsizes(sizes)
            cols=['source_row','hash_fila','hash_fuente']+headers
            sql=f'INSERT stg.{table} ('+','.join('['+x+']' for x in cols)+') VALUES('+','.join('?' for _ in cols)+')'
            try:
                cur.executemany(sql,prepared)
                checkpoint(c,'origen',table,start,end,source_hash,len(batch),batch_hash.digest())
                commit_checked(c,db,'origen',table,start)
            except Exception:c.rollback();raise
            if end%10000==0 or pilot or len(batch)<BATCH:progress('origen',tabla=table,done=end,total=profile[file]['rows'],ultimo_checkpoint=end,piloto=pilot)
            start=end+1
        if table=='resena':
            c.execute("INSERT aud.incidencia SELECT 'resena',r.source_row,j.value,r.banderas_calidad FROM stg.resena r CROSS APPLY OPENJSON(r.banderas_calidad) j WHERE NOT EXISTS(SELECT 1 FROM aud.incidencia i WHERE i.tabla='resena' AND i.source_row=r.source_row AND i.regla=j.value)")
            c.commit()

CATALOGS = {
 'perfil_autor':('segmento_perfil_autor','DESCONOCIDO','resenas_min int NULL,resenas_max int NULL'),
 'rating':(None,'DESCONOCIDO','nk_rating smallint NULL,es_positiva bit NULL,es_negativa bit NULL,es_neutra bit NULL'),
 'idioma':('codigo_idioma','xx','nombre nvarchar(100) NULL'),
 'sentimiento':('sentimiento','NO_CLASIFICADO','polaridad smallint NULL,es_texto_analizable bit NULL'),
 'extension_resena':('segmento_extension','DESCONOCIDA','palabras_min int NULL,palabras_max int NULL'),
 'antiguedad_resena':('segmento_antiguedad','NO_DETERMINADA','anios_min int NULL,anios_max int NULL'),
 'presencia_digital':('segmento_presencia_digital','DESCONOCIDA','tiene_sitio_web bit NULL,tiene_telefono bit NULL'),
}

def mart_ddl():
    sql=['CREATE SCHEMA mart;','GO',"""
CREATE TABLE mart.dim_geografia (sk_geografia bigint IDENTITY PRIMARY KEY,nk_geografia varchar(64) NOT NULL UNIQUE,codigo_pais nvarchar(16) NOT NULL,pais_iso3 nvarchar(16) NOT NULL,pais_nombre nvarchar(100) NOT NULL,nivel1_nombre nvarchar(300) NOT NULL,nivel1_tipo nvarchar(50) NULL,nivel2_nombre nvarchar(300) NOT NULL,nivel2_tipo nvarchar(50) NULL,nivel3_nombre nvarchar(300) NOT NULL,nivel3_tipo nvarchar(50) NULL,codigo_nativo nvarchar(100) NOT NULL,sistema_codigo nvarchar(50) NULL);
CREATE TABLE mart.dim_lugar (sk_lugar bigint IDENTITY PRIMARY KEY,clave_lugar nvarchar(160) NOT NULL UNIQUE,nk_place_id nvarchar(140) NOT NULL,codigo_pais nvarchar(16) NOT NULL,nombre nvarchar(1000) NOT NULL,categoria_normalizada nvarchar(200) NOT NULL,latitud decimal(12,9) NULL,longitud decimal(12,9) NULL,tiene_sitio_web bit NOT NULL,tiene_telefono bit NOT NULL,sk_geografia bigint NOT NULL REFERENCES mart.dim_geografia(sk_geografia),es_vigente bit NOT NULL DEFAULT 1,version int NOT NULL DEFAULT 1,hash_atributos binary(32) NOT NULL,version_fuente varchar(80) NOT NULL,valido_desde date NULL,valido_hasta date NULL,UNIQUE(codigo_pais,nk_place_id));
CREATE TABLE mart.dim_tiempo (sk_periodo int PRIMARY KEY,anio smallint NULL,trimestre smallint NULL,mes smallint NULL,mes_nombre nvarchar(30) NOT NULL,anio_mes char(7) NOT NULL,es_mes_determinado bit NOT NULL,etapa varchar(30) NOT NULL,CHECK(sk_periodo=-1 OR (sk_periodo BETWEEN 100000 AND 999912 AND sk_periodo%100 BETWEEN 0 AND 12)));
"""]
    for name,(_,unknown,extra) in CATALOGS.items():
        sql.append(f'CREATE TABLE mart.dim_{name} (sk_{name} bigint IDENTITY PRIMARY KEY,nk_codigo nvarchar(100) NOT NULL UNIQUE,etiqueta nvarchar(200) NOT NULL,{extra});')
    sql.append("""
CREATE TABLE mart.dim_dimension_latente (sk_dimension_latente bigint IDENTITY PRIMARY KEY,nk_codigo nvarchar(100) NOT NULL,version_modelo nvarchar(100) NOT NULL,etiqueta nvarchar(500) NOT NULL,descripcion nvarchar(max) NOT NULL,palabras_clave nvarchar(max) NOT NULL,metodo nvarchar(100) NOT NULL,validacion_etiqueta nvarchar(100) NOT NULL,UNIQUE(nk_codigo,version_modelo));
CREATE TABLE mart.fact_resena (sk_resena bigint IDENTITY PRIMARY KEY,nk_id_review nvarchar(160) NOT NULL UNIQUE,source_row bigint NOT NULL UNIQUE,hash_fuente char(64) NOT NULL,hash_fila binary(32) NOT NULL,codigo_pais nvarchar(16) NOT NULL,
sk_lugar bigint NOT NULL REFERENCES mart.dim_lugar(sk_lugar),sk_geografia bigint NOT NULL REFERENCES mart.dim_geografia(sk_geografia),sk_periodo int NOT NULL REFERENCES mart.dim_tiempo(sk_periodo),
""")
    sql.append(','.join(f'sk_{name} bigint NOT NULL REFERENCES mart.dim_{name}(sk_{name})' for name in CATALOGS)+',')
    sql.append("""
rating smallint NULL CHECK(rating BETWEEN 1 AND 5),cantidad_palabras int NOT NULL CHECK(cantidad_palabras>=0),n_resenas_autor_asof int NULL,puntaje_sentimiento float NULL CHECK(puntaje_sentimiento BETWEEN -1 AND 1),confianza_sentimiento float NULL,p_negativo float NULL,p_neutro float NULL,p_positivo float NULL,tiene_texto bit NOT NULL,precision_fecha_resena varchar(6) NOT NULL CHECK(precision_fecha_resena IN ('DIA','SEMANA','MES','ANIO','NA')),texto_resena nvarchar(max) NOT NULL,estado_nlp nvarchar(100) NOT NULL,estado_topicos nvarchar(100) NOT NULL,version_modelo_sentimiento nvarchar(150) NOT NULL,version_modelo_topicos nvarchar(150) NOT NULL);
CREATE TABLE mart.fact_resena_dimension (sk_resena bigint NOT NULL REFERENCES mart.fact_resena(sk_resena),sk_dimension_latente bigint NOT NULL REFERENCES mart.dim_dimension_latente(sk_dimension_latente),peso decimal(4,3) NOT NULL CHECK(peso=1),es_dominante bit NOT NULL,source_row bigint NOT NULL UNIQUE,hash_fuente char(64) NOT NULL,PRIMARY KEY(sk_resena,sk_dimension_latente));
CREATE TABLE mart.fact_reputacion_lugar (sk_reputacion bigint IDENTITY PRIMARY KEY,sk_lugar bigint NOT NULL REFERENCES mart.dim_lugar(sk_lugar),sk_geografia bigint NOT NULL REFERENCES mart.dim_geografia(sk_geografia),sk_periodo int NOT NULL REFERENCES mart.dim_tiempo(sk_periodo),sk_presencia_digital bigint NOT NULL REFERENCES mart.dim_presencia_digital(sk_presencia_digital),rating_promedio_google decimal(3,1) NULL CHECK(rating_promedio_google BETWEEN 0 AND 5),n_valoraciones_google bigint NULL CHECK(n_valoraciones_google>=0),fecha_observacion date NULL,precision_observacion varchar(30) NOT NULL CHECK(precision_observacion='NO_DOCUMENTADA'),version_fuente varchar(80) NOT NULL,source_row bigint NOT NULL UNIQUE,UNIQUE(sk_lugar,version_fuente),CHECK(rating_promedio_google IS NOT NULL OR n_valoraciones_google IS NOT NULL));
""")
    return '\n'.join(sql)

def core_view(origin):
    return f"""
CREATE OR ALTER VIEW mart.v_fuente_lugar AS
SELECT l.*,CONVERT(varchar(64),HASHBYTES('SHA2_256',(SELECT l.codigo_pais,l.departamento_final,l.provincia_final,l.distrito_final,l.inei_real FOR JSON PATH,WITHOUT_ARRAY_WRAPPER)),2) nk_geografia,
CONVERT(bit,CASE WHEN l.domain<>'' OR l.url<>'' THEN 1 ELSE 0 END) tiene_web,
CONVERT(bit,CASE WHEN l.phoneNumber<>'' OR l.completePhoneNumber<>'' THEN 1 ELSE 0 END) tiene_telefono,
CASE WHEN l.domain<>'' OR l.url<>'' THEN CASE WHEN l.phoneNumber<>'' OR l.completePhoneNumber<>'' THEN 'COMPLETA' ELSE 'SOLO_WEB' END ELSE CASE WHEN l.phoneNumber<>'' OR l.completePhoneNumber<>'' THEN 'SOLO_TELEFONO' ELSE 'NINGUNA' END END presencia
FROM [{origin}].stg.lugar l;
"""

def init_mart(c,origin):
    sql=mart_ddl()
    (HERE/'02_datamart.sql').write_text(CONTROL+'\n'+sql,encoding='utf-8')
    if not scalar(c,"SELECT COUNT(*) FROM sys.tables WHERE name='fact_resena' AND schema_id=SCHEMA_ID('mart')"):
        execute_script(c,sql);c.commit()
    execute_script(c,core_view(origin));c.commit()
    views=(HERE/'03_vistas.sql').read_text(encoding='utf-8').replace('USE [MuseosLatam_Datamart];','')
    execute_script(c,views);c.commit()

def load_dims(c,origin):
    progress('dimensiones')
    if not scalar(c,"SELECT COUNT(*) FROM aud.lote WHERE fase='dimensiones'"):
        sql="""
SET IDENTITY_INSERT mart.dim_geografia ON;
INSERT mart.dim_geografia(sk_geografia,nk_geografia,codigo_pais,pais_iso3,pais_nombre,nivel1_nombre,nivel2_nombre,nivel3_nombre,codigo_nativo) VALUES(-1,'DESCONOCIDO','XX','XXX','Desconocido','','','','');
SET IDENTITY_INSERT mart.dim_geografia OFF;
INSERT mart.dim_geografia(nk_geografia,codigo_pais,pais_iso3,pais_nombre,nivel1_nombre,nivel1_tipo,nivel2_nombre,nivel2_tipo,nivel3_nombre,nivel3_tipo,codigo_nativo,sistema_codigo)
SELECT DISTINCT nk_geografia,codigo_pais,pais_iso3,pais,departamento_final,CASE codigo_pais WHEN 'PE' THEN 'departamento' WHEN 'MX' THEN 'estado' ELSE 'provincia' END,provincia_final,CASE codigo_pais WHEN 'PE' THEN 'provincia' WHEN 'MX' THEN 'municipio o alcaldia' ELSE 'departamento o partido' END,distrito_final,CASE WHEN distrito_final<>'' THEN 'distrito' END,inei_real,CASE codigo_pais WHEN 'PE' THEN 'INEI_UBIGEO' ELSE 'GEOBOUNDARIES_ADM2' END FROM mart.v_fuente_lugar;
SET IDENTITY_INSERT mart.dim_lugar ON;
INSERT mart.dim_lugar(sk_lugar,clave_lugar,nk_place_id,codigo_pais,nombre,categoria_normalizada,tiene_sitio_web,tiene_telefono,sk_geografia,hash_atributos,version_fuente) VALUES(-1,'DESCONOCIDO','DESCONOCIDO','XX','Desconocido','',0,0,-1,HASHBYTES('SHA2_256','DESCONOCIDO'),'DESCONOCIDO');
SET IDENTITY_INSERT mart.dim_lugar OFF;
INSERT mart.dim_lugar(clave_lugar,nk_place_id,codigo_pais,nombre,categoria_normalizada,latitud,longitud,tiene_sitio_web,tiene_telefono,sk_geografia,hash_atributos,version_fuente)
SELECT l.clave_lugar,l.id,l.codigo_pais,l.title,l.categoria_normalizada,CONVERT(decimal(12,9),NULLIF(l.lat,'')),CONVERT(decimal(12,9),NULLIF(l.lon,'')),l.tiene_web,l.tiene_telefono,g.sk_geografia,l.hash_fila,'latam-ampliacion-2026-10-22-v1' FROM mart.v_fuente_lugar l JOIN mart.dim_geografia g ON g.nk_geografia=l.nk_geografia;
INSERT mart.dim_tiempo VALUES(-1,NULL,NULL,NULL,'Desconocido','0000-00',0,'NO_DETERMINADA');
"""
        execute_script(c,sql)
        periods={int(r[0]) for r in c.cursor().execute(f'SELECT DISTINCT periodo_codigo FROM [{origin}].stg.resena')}
        periods|={y*100+m for y in range(2004,2032) for m in range(13)}
        months=['No determinado','Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
        for p in sorted(periods-{-1}):
            y,m=divmod(p,100);assert 0<=m<=12
            c.execute('INSERT mart.dim_tiempo VALUES(?,?,?,?,?,?,?,?)',p,y,(m-1)//3+1 if m else None,m,months[m],f'{y:04}-{m:02}',bool(m),'PREPANDEMIA' if y<=2019 else 'PANDEMIA' if y<=2021 else 'POSPANDEMIA')
        for name,(source,unknown,_) in CATALOGS.items():
            execute_script(c,f"SET IDENTITY_INSERT mart.dim_{name} ON; INSERT mart.dim_{name}(sk_{name},nk_codigo,etiqueta) VALUES(-1,N'{unknown}',N'{unknown}'); SET IDENTITY_INSERT mart.dim_{name} OFF;")
            if source:
                c.execute(f"INSERT mart.dim_{name}(nk_codigo,etiqueta) SELECT DISTINCT r.[{source}],r.[{source}] FROM [{origin}].stg.resena r WHERE r.[{source}]<>?",unknown)
            else:
                for n,label in enumerate(['Muy negativa','Negativa','Neutra','Positiva','Muy positiva'],1):
                    c.execute('INSERT mart.dim_rating(nk_codigo,etiqueta,nk_rating,es_positiva,es_negativa,es_neutra) VALUES(?,?,?,?,?,?)',str(n),label,n,n>=4,n<=2,n==3)
        for code in ['COMPLETA','SOLO_WEB','SOLO_TELEFONO','NINGUNA']:
            c.execute("IF NOT EXISTS(SELECT 1 FROM mart.dim_presencia_digital WHERE nk_codigo=?) INSERT mart.dim_presencia_digital(nk_codigo,etiqueta) VALUES(?,?)",code,code,code)
        # Los catálogos derivados de la fuente conservan todos los estados, incluidos baja confianza e idioma incierto.
        execute_script(c,"""
UPDATE mart.dim_perfil_autor SET resenas_min=CASE nk_codigo WHEN 'SIN_HISTORIAL' THEN 0 WHEN 'NOVATO' THEN 1 WHEN 'INTERMEDIO' THEN 11 WHEN 'EXPERIMENTADO' THEN 51 END,resenas_max=CASE nk_codigo WHEN 'SIN_HISTORIAL' THEN 0 WHEN 'NOVATO' THEN 10 WHEN 'INTERMEDIO' THEN 50 END;
UPDATE mart.dim_extension_resena SET palabras_min=CASE nk_codigo WHEN 'SIN_TEXTO' THEN 0 WHEN 'MUY_BREVE' THEN 1 WHEN 'BREVE' THEN 6 WHEN 'MEDIA' THEN 21 WHEN 'EXTENSA' THEN 61 END,palabras_max=CASE nk_codigo WHEN 'SIN_TEXTO' THEN 0 WHEN 'MUY_BREVE' THEN 5 WHEN 'BREVE' THEN 20 WHEN 'MEDIA' THEN 60 END;
UPDATE mart.dim_antiguedad_resena SET anios_min=CASE nk_codigo WHEN 'HASTA_1' THEN 0 WHEN 'DE_2_A_3' THEN 2 WHEN 'DE_4_A_5' THEN 4 WHEN 'MAS_DE_5' THEN 6 END,anios_max=CASE nk_codigo WHEN 'HASTA_1' THEN 1 WHEN 'DE_2_A_3' THEN 3 WHEN 'DE_4_A_5' THEN 5 END;
UPDATE mart.dim_sentimiento SET polaridad=CASE nk_codigo WHEN 'NEGATIVO' THEN -1 WHEN 'NEUTRO' THEN 0 WHEN 'POSITIVO' THEN 1 END,es_texto_analizable=CASE WHEN nk_codigo IN ('NEGATIVO','NEUTRO','POSITIVO') THEN 1 ELSE 0 END;
UPDATE mart.dim_idioma SET nombre=CASE nk_codigo WHEN 'xx' THEN N'Incierto' WHEN 'es' THEN N'Español' WHEN 'en' THEN N'Inglés' WHEN 'pt' THEN N'Portugués' WHEN 'fr' THEN N'Francés' WHEN 'de' THEN N'Alemán' WHEN 'it' THEN N'Italiano' ELSE nk_codigo END;
UPDATE mart.dim_presencia_digital SET tiene_sitio_web=CASE WHEN sk_presencia_digital=-1 THEN NULL WHEN nk_codigo IN ('COMPLETA','SOLO_WEB') THEN 1 ELSE 0 END,tiene_telefono=CASE WHEN sk_presencia_digital=-1 THEN NULL WHEN nk_codigo IN ('COMPLETA','SOLO_TELEFONO') THEN 1 ELSE 0 END;
SET IDENTITY_INSERT mart.dim_dimension_latente ON;
INSERT mart.dim_dimension_latente(sk_dimension_latente,nk_codigo,version_modelo,etiqueta,descripcion,palabras_clave,metodo,validacion_etiqueta) VALUES(-1,'NO_ASIGNADA','DESCONOCIDO','No asignada','','','','NO_APLICA');
SET IDENTITY_INSERT mart.dim_dimension_latente OFF;
""")
        c.execute(f'INSERT mart.dim_dimension_latente(nk_codigo,version_modelo,etiqueta,descripcion,palabras_clave,metodo,validacion_etiqueta) SELECT codigo_topico,version_modelo,etiqueta,descripcion,palabras_clave,metodo,validacion_etiqueta FROM [{origin}].stg.catalogo')
        checkpoint(c,'dimensiones','todas',1,1,VERSION,1)
        c.commit()

def fact_select(origin):
    cols=['nk_id_review','source_row','hash_fuente','hash_fila','codigo_pais','sk_lugar','sk_geografia','sk_periodo']+['sk_'+x for x in CATALOGS]
    expr=['r.id_review','r.source_row','r.hash_fuente','r.hash_fila','r.codigo_pais','l.sk_lugar','l.sk_geografia','CONVERT(int,r.periodo_codigo)']
    joins=[f'FROM [{origin}].stg.resena r JOIN mart.dim_lugar l ON l.clave_lugar=r.clave_lugar']
    for name,(source,_,_) in CATALOGS.items():
        expr.append(f'd_{name}.sk_{name}')
        nk=(f"COALESCE(CONVERT(nvarchar(100),CONVERT(smallint,CONVERT(decimal(3,1),NULLIF(r.rating,'')))),'DESCONOCIDO')" if name=='rating' else f'r.[{source}]')
        joins.append(f'JOIN mart.dim_{name} d_{name} ON d_{name}.nk_codigo={nk}')
    measures={
        'rating':"CONVERT(smallint,CONVERT(decimal(3,1),NULLIF(r.rating,'')))",'cantidad_palabras':'CONVERT(int,r.cantidad_palabras)',
        'n_resenas_autor_asof':"CONVERT(int,NULLIF(r.n_resenas_autor_asof,''))",
        **{k:f"CONVERT(float,NULLIF(r.{k},''))" for k in ['puntaje_sentimiento','confianza_sentimiento','p_negativo','p_neutro','p_positivo']},
        'tiene_texto':'CONVERT(bit,r.tiene_texto)','precision_fecha_resena':'r.precision_fecha_resena','texto_resena':'r.caption',
        **{k:'r.'+k for k in ['estado_nlp','estado_topicos','version_modelo_sentimiento','version_modelo_topicos']}}
    cols+=list(measures);expr+=list(measures.values())
    return cols,expr,'\n'.join(joins)

def load_facts(c,origin,sources,pilot=False):
    cols,expr,joins=fact_select(origin)
    queries={
      'resena':f"INSERT mart.fact_resena({','.join(cols)}) SELECT {','.join(expr)} {joins} WHERE r.source_row BETWEEN ? AND ? AND NOT EXISTS(SELECT 1 FROM mart.fact_resena f WHERE f.nk_id_review=r.id_review)",
      'puente':f"INSERT mart.fact_resena_dimension(sk_resena,sk_dimension_latente,peso,es_dominante,source_row,hash_fuente) SELECT f.sk_resena,d.sk_dimension_latente,CONVERT(decimal(4,3),r.peso),CONVERT(bit,r.es_dominante),r.source_row,r.hash_fuente FROM [{origin}].stg.puente r JOIN mart.fact_resena f ON f.nk_id_review=r.id_review JOIN mart.dim_dimension_latente d ON d.nk_codigo=r.codigo_topico AND d.version_modelo=r.version_modelo WHERE r.source_row BETWEEN ? AND ? AND NOT EXISTS(SELECT 1 FROM mart.fact_resena_dimension x WHERE x.sk_resena=f.sk_resena AND x.sk_dimension_latente=d.sk_dimension_latente)",
      'lugar':"""INSERT mart.fact_reputacion_lugar(sk_lugar,sk_geografia,sk_periodo,sk_presencia_digital,rating_promedio_google,n_valoraciones_google,fecha_observacion,precision_observacion,version_fuente,source_row)
SELECT l.sk_lugar,l.sk_geografia,-1,p.sk_presencia_digital,CONVERT(decimal(3,1),NULLIF(r.stars,'')),CONVERT(bigint,CONVERT(decimal(20,1),NULLIF(r.reviews,''))),NULL,'NO_DOCUMENTADA','latam-ampliacion-2026-10-22-v1',r.source_row FROM mart.v_fuente_lugar r JOIN mart.dim_lugar l ON l.clave_lugar=r.clave_lugar JOIN mart.dim_presencia_digital p ON p.nk_codigo=r.presencia WHERE r.source_row BETWEEN ? AND ? AND (r.stars<>'' OR r.reviews<>'') AND NOT EXISTS(SELECT 1 FROM mart.fact_reputacion_lugar f WHERE f.sk_lugar=l.sk_lugar AND f.version_fuente='latam-ampliacion-2026-10-22-v1')"""}
    for table in ['resena','puente','lugar']:
        total=scalar(c,f'SELECT COUNT_BIG(*) FROM [{origin}].stg.{table}')
        done=existing(c,'mart',table)
        for start in range(1,total+1,10000):
            if start in done:continue
            stopped();end=min(start+9999,total)
            c.execute(queries[table],start,end)
            n=scalar(c,'SELECT @@ROWCOUNT')
            checkpoint(c,'mart',table,start,end,sources[FILES[table]]['sha256'],n)
            c.commit()
            if end%100000==0 or end==total:progress('hechos',tabla=table,done=end,total=total,ultimo_checkpoint=end,piloto=pilot)

def counts(c,schema):
    tables=[r[0] for r in c.cursor().execute('SELECT name FROM sys.tables WHERE schema_id=SCHEMA_ID(?) ORDER BY name',schema)]
    return {t:scalar(c,f'SELECT COUNT_BIG(*) FROM {schema}.[{t}]') for t in tables}

def validate(c,origin,profile,pilot=False):
    progress('validacion_sql',piloto=pilot)
    report={'conteos':counts(c,'mart'),'pruebas':{},'pais':[]}
    tests=report['pruebas']
    def zero(name,sql):
        value=scalar(c,sql);tests[name]=value
        assert value==0,f'{name}: {value}'
    pairs=[('resena','fact_resena','s.id_review=f.nk_id_review'),('lugar','dim_lugar','s.clave_lugar=f.clave_lugar'),('catalogo','dim_dimension_latente','s.codigo_topico=f.nk_codigo AND s.version_modelo=f.version_modelo')]
    for raw,tab,cond in pairs:
        zero(raw+'_faltantes',f'SELECT COUNT_BIG(*) FROM [{origin}].stg.{raw} s WHERE NOT EXISTS(SELECT 1 FROM mart.{tab} f WHERE {cond})')
        extra=" AND f.sk_lugar<>-1" if tab=='dim_lugar' else " AND f.sk_dimension_latente<>-1" if tab=='dim_dimension_latente' else ''
        zero(raw+'_sobrantes',f'SELECT COUNT_BIG(*) FROM mart.{tab} f WHERE NOT EXISTS(SELECT 1 FROM [{origin}].stg.{raw} s WHERE {cond})'+extra)
    zero('puente_faltantes',f'''SELECT COUNT_BIG(*) FROM [{origin}].stg.puente s WHERE NOT EXISTS(SELECT 1 FROM mart.fact_resena_dimension w JOIN mart.fact_resena f ON f.sk_resena=w.sk_resena JOIN mart.dim_dimension_latente d ON d.sk_dimension_latente=w.sk_dimension_latente WHERE f.nk_id_review=s.id_review AND d.nk_codigo=s.codigo_topico AND d.version_modelo=s.version_modelo AND w.peso=CONVERT(decimal(4,3),s.peso) AND w.es_dominante=CONVERT(bit,s.es_dominante))''')
    zero('puente_sobrantes',f'''SELECT COUNT_BIG(*) FROM mart.fact_resena_dimension w JOIN mart.fact_resena f ON f.sk_resena=w.sk_resena JOIN mart.dim_dimension_latente d ON d.sk_dimension_latente=w.sk_dimension_latente WHERE NOT EXISTS(SELECT 1 FROM [{origin}].stg.puente s WHERE f.nk_id_review=s.id_review AND d.nk_codigo=s.codigo_topico AND d.version_modelo=s.version_modelo)''')
    zero('reseñas_duplicadas','SELECT COUNT_BIG(*) FROM (SELECT nk_id_review FROM mart.fact_resena GROUP BY nk_id_review HAVING COUNT(*)>1) q')
    zero('geografia_inconsistente','SELECT COUNT_BIG(*) FROM mart.fact_resena f JOIN mart.dim_lugar l ON l.sk_lugar=f.sk_lugar JOIN mart.dim_geografia g ON g.sk_geografia=l.sk_geografia WHERE f.sk_geografia<>l.sk_geografia OR f.codigo_pais<>l.codigo_pais OR f.codigo_pais<>g.codigo_pais')
    zero('periodo_precision',"SELECT COUNT_BIG(*) FROM mart.fact_resena WHERE (precision_fecha_resena='ANIO' AND sk_periodo%100<>0) OR (precision_fecha_resena='NA' AND sk_periodo<>-1)")
    zero('mes_trimestre_inventado','SELECT COUNT(*) FROM mart.dim_tiempo WHERE sk_periodo<>-1 AND mes=0 AND (trimestre IS NOT NULL OR es_mes_determinado<>0)')
    zero('coordenadas_fuera_rango','SELECT COUNT(*) FROM mart.dim_lugar WHERE latitud NOT BETWEEN -90 AND 90 OR longitud NOT BETWEEN -180 AND 180')
    zero('reputacion_fecha_inventada',"SELECT COUNT(*) FROM mart.fact_reputacion_lugar WHERE sk_periodo<>-1 OR fecha_observacion IS NOT NULL OR precision_observacion<>'NO_DOCUMENTADA'")
    zero('peso_no_uno','SELECT COUNT(*) FROM mart.fact_resena_dimension WHERE peso<>1')
    zero('texto_hash_o_longitud_diferente',f"SELECT COUNT_BIG(*) FROM mart.fact_resena f JOIN [{origin}].stg.resena s ON s.id_review=f.nk_id_review WHERE DATALENGTH(s.caption)<>DATALENGTH(f.texto_resena) OR HASHBYTES('SHA2_256',s.caption)<>HASHBYTES('SHA2_256',f.texto_resena)")
    zero('presencia_inconsistente',"SELECT COUNT_BIG(*) FROM mart.fact_resena f JOIN mart.dim_lugar l ON l.sk_lugar=f.sk_lugar JOIN mart.dim_presencia_digital p ON p.sk_presencia_digital=f.sk_presencia_digital WHERE p.tiene_sitio_web<>l.tiene_sitio_web OR p.tiene_telefono<>l.tiene_telefono")
    zero('autor_ambiguo_inventado',f"SELECT COUNT_BIG(*) FROM mart.fact_resena f JOIN [{origin}].stg.resena s ON s.id_review=f.nk_id_review WHERE s.banderas_calidad LIKE '%HISTORIAL_AUTOR_INVALIDO%' AND (f.n_resenas_autor_asof IS NOT NULL OR f.sk_perfil_autor<>-1)")
    zero('restricciones_no_confiables','SELECT COUNT(*) FROM sys.foreign_keys WHERE is_disabled=1 OR is_not_trusted=1')
    dim_pk={'geografia':'geografia','lugar':'lugar','tiempo':'periodo','dimension_latente':'dimension_latente',**{k:k for k in CATALOGS}}
    for name,pk in dim_pk.items():
        assert scalar(c,f'SELECT COUNT(*) FROM mart.dim_{name} WHERE sk_{pk}=-1')==1
    tests['once_miembros_desconocidos']='OK'
    for row in c.cursor().execute("SELECT DISTINCT OBJECT_SCHEMA_NAME(parent_object_id),OBJECT_NAME(parent_object_id),'ALL' FROM sys.foreign_keys").fetchall():
        schema,table,constraint=row
        # DBCC comprueba cada FK y CHECK contra los registros realmente cargados.
        cur=c.cursor().execute(f"DBCC CHECKCONSTRAINTS ('{schema}.{table}') WITH ALL_CONSTRAINTS")
        violations=[]
        while True:
            if cur.description:violations+=cur.fetchall()
            if not cur.nextset():break
        assert not violations,(constraint,violations[:1])
    tests['FK_CHECK_reales']='OK'
    cols,expr,joins=fact_select(origin)
    compare=['f.'+x for x in cols]
    # EXCEPT compara cada medida o estado transformado, el texto UTF-16 y cada SK, no solo los conteos.
    aliased=[e+' AS ['+col+']' for col,e in zip(cols,expr)]
    zero('campos_hecho_diferentes',f"SELECT COUNT_BIG(*) FROM (SELECT {','.join(aliased)} {joins} EXCEPT SELECT {','.join(compare)} FROM mart.fact_resena f) q")
    zero('reputacion_medidas_diferentes',"""SELECT COUNT(*) FROM mart.fact_reputacion_lugar f JOIN mart.dim_lugar l ON l.sk_lugar=f.sk_lugar JOIN mart.v_fuente_lugar s ON s.clave_lugar=l.clave_lugar WHERE EXISTS(SELECT f.rating_promedio_google,f.n_valoraciones_google EXCEPT SELECT CONVERT(decimal(3,1),NULLIF(s.stars,'')),CONVERT(bigint,CONVERT(decimal(20,1),NULLIF(s.reviews,''))))""")
    expected_rep=scalar(c,"SELECT COUNT(*) FROM mart.v_fuente_lugar WHERE stars<>'' OR reviews<>''")
    assert report['conteos']['fact_reputacion_lugar']==expected_rep
    report['reputacion_esperada']=expected_rep
    for row in c.cursor().execute('SELECT codigo_pais,COUNT_BIG(*),COUNT(rating),SUM(CONVERT(bigint,rating)),SUM(CONVERT(bigint,tiene_texto)),SUM(CONVERT(bigint,cantidad_palabras)),MIN(rating),MAX(rating) FROM mart.fact_resena GROUP BY codigo_pais ORDER BY codigo_pais'):
        country,n,nonnull,total,withtext,words,minr,maxr=row
        record=dict(codigo_pais=country,resenas=n,ratings_null=n-nonnull,suma_rating=total,con_texto=withtext,suma_palabras=words,min_rating=minr,max_rating=maxr)
        report['pais'].append(record)
        if not pilot:
            expected=profile[FILES['resena']]['stats'][country]
            assert (n,n-nonnull,total,withtext,words)==(expected['rows'],expected['null_rating'],expected['sum_rating'],expected['with_text'],expected['sum_words'])
    if not pilot:
        assert report['conteos']['fact_resena']==1143877
        assert report['conteos']['fact_resena_dimension']==233556
        assert report['conteos']['dim_lugar']==6539
        assert report['conteos']['dim_dimension_latente']==42
        coverage={r[0]:tuple(r[1:]) for r in c.cursor().execute("SELECT codigo_pais,COUNT_BIG(*),SUM(CONVERT(bigint,tiene_texto)),SUM(CASE WHEN estado_topicos IN ('OK','OK_IDIOMA_INCIERTO','FUERA_DE_GRUPO') THEN CONVERT(bigint,1) ELSE 0 END),SUM(CASE WHEN estado_topicos IN ('OK','OK_IDIOMA_INCIERTO') THEN CONVERT(bigint,1) ELSE 0 END) FROM mart.fact_resena GROUP BY codigo_pais").fetchall()}
        for r in rows(FINAL/'cobertura_por_pais.csv'):
            assert coverage[r['codigo_pais']]==tuple(int(r[k]) for k in ['resenas','con_texto','elegibles_linea_base','asignadas'])
        distribution={(r[0],r[1],r[2]):r[3] for r in c.cursor().execute('SELECT f.codigo_pais,d.nk_codigo,d.version_modelo,COUNT_BIG(*) FROM mart.fact_resena_dimension w JOIN mart.fact_resena f ON f.sk_resena=w.sk_resena JOIN mart.dim_dimension_latente d ON d.sk_dimension_latente=w.sk_dimension_latente GROUP BY f.codigo_pais,d.nk_codigo,d.version_modelo').fetchall()}
        expected_distribution={(r['codigo_pais'],r['codigo_topico'],r['version_modelo']):int(r['resenas']) for r in rows(FINAL/'distribucion_topicos_por_pais.csv')}
        assert distribution==expected_distribution
        tests['cobertura_y_123_distribuciones_topicos']='OK'
        if scalar(c,"SELECT COUNT(*) FROM sys.tables WHERE name='revision_semantica' AND schema_id=SCHEMA_ID('aud')"):
            from revision_ia_v1.aplicar_revision import validate as validate_revision
            report['revision_ia']=validate_revision(c,origin)
            tests['catalogo_curado_y_etiquetas_IA']='OK'
    c.commit()
    return report

def verify_roundtrip(c,profile,pilot=False):
    progress('lectura_vuelta_completa',piloto=pilot)
    result={}
    for table,file in FILES.items():
        headers=profile[file]['headers'];cur=c.cursor()
        cur.execute('SELECT source_row,hash_fila,'+','.join('['+k+']' for k in headers)+f' FROM stg.{table} ORDER BY source_row')
        n=0;agg=hashlib.sha256()
        while True:
            batch=cur.fetchmany(500)
            if not batch:break
            for row in batch:
                n+=1;assert row[0]==n
                actual=digest(row[2:]);assert actual==bytes(row[1]),f'Lectura SQL difiere: {table} {n}'
                agg.update(actual)
            if n%100000==0:progress('lectura_vuelta_completa',tabla=table,done=n,total=profile[file]['rows'])
        # Compara el agregado con un nuevo parseo independiente del CSV, no solo con los hashes guardados.
        progress('contraste_hash_csv',tabla=table,done=n,piloto=pilot)
        source=hashlib.sha256();ns=0
        selected=json.loads((PRIVATE/'pilot_samples.json').read_text(encoding='utf-8')) if pilot else None
        dataset=selected if pilot and table=='resena' else rows(FINAL/file)
        ids={r['id_review'] for r in selected} if pilot else None
        for r in dataset:
            if pilot and table=='puente' and r['id_review'] not in ids:continue
            source.update(digest(r[k] for k in headers));ns+=1
        assert ns==n and source.digest()==agg.digest(),table+' no concilia con CSV'
        result[table]={'rows':n,'sha256_campos_sql_y_csv':agg.hexdigest(),'estado':'OK'}
        progress('lectura_vuelta_ok',tabla=table,done=n)
    c.commit()
    return result

def run_pair(master,profile,sources,pilot=False,previous_readback=None):
    suffix='_Piloto' if pilot else ''
    origin='MuseosLatam_Origen'+suffix;mart='MuseosLatam_Datamart'+suffix
    for name in [origin,mart]:ensure_db(master,name)
    o=connect(origin);m=connect(mart)
    execution=None
    try:
        init_origin(o,profile);init_mart(m,origin)
        started=datetime.now(timezone.utc).isoformat()
        before=counts(m,'mart')
        execution=scalar(m,"INSERT aud.ejecucion(estado) OUTPUT INSERTED.id VALUES('EN_CURSO')")
        m.commit()
        load_origin(o,origin,profile,sources,pilot)
        load_dims(m,origin)
        if not pilot and (HERE/'revision_ia_v1/manifiesto_revision.json').exists():
            from revision_ia_v1.aplicar_revision import apply as apply_revision
            apply_revision(m,origin);m.commit()
        load_facts(m,origin,sources,pilot)
        report=validate(m,origin,profile,pilot)
        report['origen']=counts(o,'stg')
        if not pilot:
            assert report['origen']=={'catalogo':41,'lugar':6538,'puente':233556,'resena':1143877}
        report['roundtrip']=verify_roundtrip(o,profile,pilot) if previous_readback is None else previous_readback
        if previous_readback is not None:
            report['roundtrip_reutilizado']='La primera pasada verificó todos los campos. Segunda pasada bajo el mismo lock exclusivo; repite controles SQL completos y concilia conteos reales.'
        verify_files()  # También detecta un archivo cambiado durante la ejecución.
        report['bases']=[origin,mart]
        report['inicio_utc']=started
        report['fin_utc']=datetime.now(timezone.utc).isoformat()
        report['antes']=before
        report['delta_desde_inicio']={k:report['conteos'][k]-v for k,v in before.items()}
        m.execute("UPDATE aud.ejecucion SET fin=SYSUTCDATETIME(),estado='EJECUTADO_Y_VERIFICADO',informe=? WHERE id=?",json.dumps(report,ensure_ascii=False,default=str),execution)
        m.commit()
        return report
    except BaseException as exc:
        o.rollback();m.rollback()
        if execution is not None:
            try:
                m.execute("UPDATE aud.ejecucion SET fin=SYSUTCDATETIME(),estado='FALLIDO',informe=? WHERE id=?",json.dumps({'error':str(exc)},ensure_ascii=False),execution)
                m.commit()
            except pyodbc.Error:
                # SQL puede estar caído; el log privado conserva la causa y el checkpoint.
                pass
        raise
    finally:o.close();m.close()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--piloto',action='store_true');parser.add_argument('--completo',action='store_true');args=parser.parse_args()
    if not args.piloto and not args.completo:parser.error('Indicar --piloto o --completo')
    master=connect(autocommit=True)
    lock=scalar(master,"DECLARE @r int; EXEC @r=sys.sp_getapplock @Resource='MuseosLatamSQL-carga',@LockMode='Exclusive',@LockOwner='Session',@LockTimeout=0; SELECT @r")
    if lock<0:raise RuntimeError('Ya hay otro cargador activo')
    try:
        stopped();start=time.time()
        version=list(master.cursor().execute("SELECT @@SERVERNAME,@@VERSION,SERVERPROPERTY('Edition'),HAS_PERMS_BY_NAME(NULL,NULL,'CREATE ANY DATABASE')").fetchone())
        progress('preflight',instancia=version[0],edicion=version[2])
        sources=verify_files();profile=json.loads((HERE/'perfil_fuentes.json').read_text(encoding='utf-8'))
        if args.completo:
            pilot=json.loads((HERE/'evidencia_piloto.json').read_text(encoding='utf-8'))
            assert pilot['estado']=='EJECUTADO_Y_VERIFICADO' and all(x==0 for x in pilot['delta'].values())
        first=run_pair(master,profile,sources,args.piloto)
        # Misma ruta de entrada dos veces: los checkpoints se contrastan con SQL y se repiten todas las validaciones.
        second=run_pair(master,profile,sources,args.piloto,previous_readback=first['roundtrip'])
        delta={k:second['conteos'][k]-v for k,v in first['conteos'].items()}
        assert all(v==0 for v in delta.values())
        report=dict(estado='EJECUTADO_Y_VERIFICADO',version=VERSION,servidor=version,segundos=time.time()-start,primera=first,segunda=second,delta=delta)
        path=HERE/('evidencia_piloto.json' if args.piloto else 'evidencia_final.json');jdump(path,report)
        progress('EJECUTADO_Y_VERIFICADO',informe=str(path),segundos=report['segundos'])
    finally:master.close()

if __name__=='__main__':
    try:main()
    except BaseException as exc:
        # Los datos del error y las trazas se guardan en privado; nunca se registran cadenas de conexión ni contraseñas.
        details=traceback.format_exc()
        try:
            secret=json.loads((PRIVATE/'connection.json').read_text(encoding='utf-8'))['password'];details=details.replace(secret,'[REDACTED]')
        except Exception:pass
        (PRIVATE/'ultimo_error.log').write_text(details,encoding='utf-8')
        progress('DETENIDO' if isinstance(exc,InterruptedError) else 'FALLIDO',error=str(exc))
        raise SystemExit(1)
