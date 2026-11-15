"""Contratos, trazabilidad y utilidades sin dependencias NLP."""
import calendar
import csv
import hashlib
import json
import math
import os
import re
import sqlite3
import time
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO / 'data/preparacion_latam'
LOG_ROOT = REPO / 'logs/preparacion_latam'
VERSION = 'fases12-1.0.0'
REVIEW_FIELDS = ['google_place_id','nombre_lugar','categoria_google','distrito','provincia',
    'departamento','id_review','caption','relative_date','review_date','retrieval_date',
    'rating','username','n_review_user','url_user','url_source']
SOURCES = [('PE','Perú','PER','base_museos_peru.csv','resenas_museos_consolidadas.csv'),
           ('MX','México','MEX','base_museos_mexico.csv','resenas_museos_consolidadas_mexico.csv')]
csv.field_size_limit(10_000_000)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    for attempt in range(6):
        try:
            temp.replace(path)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(.2 * (attempt + 1))


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def text_key(text):
    # Deduplicación COMPUTACIONAL de textos; no modifica el texto original.
    return hashlib.sha256(normalized_text(text).encode('utf-8')).hexdigest()


def normalized_text(text):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', text)).strip()


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        for number, row in enumerate(reader, 2):
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f'CSV mal formado: {path}, registro {number}')
            yield number, row


def iso_date(value):
    date = datetime.fromisoformat(value.replace('Z','+00:00'))
    return date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date.astimezone(timezone.utc)


def integer(value):
    if not value or str(value).lower() in ('nan','none','null'):
        return None
    number = float(str(value).replace(',','').replace(' ','').strip())
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        raise ValueError(f'Entero no valido: {value!r}')
    return int(number)


def estimate_date(relative, extracted):
    """Compatibilidad con la dimensión mensual del repo; NA no inventa fecha."""
    anchor = iso_date(extracted)
    s = unicodedata.normalize('NFKD', relative.lower())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r'\b(editado|edited)\b','',s).strip()
    numbers = {'un':1,'una':1,'one':1,'dos':2,'two':2,'tres':3,'three':3,
               'cuatro':4,'four':4,'cinco':5,'five':5,'seis':6,'six':6}
    match = re.search(r'\d+',s)
    n = int(match.group()) if match else next((v for k,v in numbers.items() if re.search(rf'\b{k}\b',s)),1)
    if re.search(r'\b(segundo\w*|second\w*|minuto\w*|minute\w*|hora\w*|hour\w*)\b',s) or s in ('hoy','today'):
        seconds = n * (3600 if re.search(r'\b(hora\w*|hour\w*)\b',s) else
                       60 if re.search(r'\b(minuto\w*|minute\w*)\b',s) else
                       1 if re.search(r'\b(segundo\w*|second\w*)\b',s) else 0)
        date, precision = anchor-timedelta(seconds=seconds), 'DIA'
    elif s in ('ayer','yesterday'):
        date, precision = anchor-timedelta(days=1), 'DIA'
    elif re.search(r'\b(dia\w*|day\w*)\b',s):
        date, precision = anchor-timedelta(days=n), 'DIA'
    elif re.search(r'\b(semana\w*|week\w*)\b',s):
        date, precision = anchor-timedelta(weeks=n), 'SEMANA'
    elif re.search(r'\b(mes|meses|month\w*|ano\w*|year\w*)\b',s):
        annual = bool(re.search(r'\b(ano\w*|year\w*)\b',s))
        offset = n * 12 if annual else n
        total_month = anchor.year*12 + anchor.month-1 - offset
        year, month = divmod(total_month,12)
        date = anchor.replace(year=year,month=month+1,day=1,hour=0,minute=0,second=0,microsecond=0)
        if annual:
            date = date.replace(month=1)
        precision = 'ANIO' if annual else 'MES'
    else:
        return '', 'NA', -1, 'NO_DETERMINADA'
    if precision in ('DIA','SEMANA'):
        date = date.replace(hour=0,minute=0,second=0,microsecond=0)
    if date > anchor:
        raise ValueError('Fecha estimada posterior a extracción')
    period = date.year*100 + (0 if precision == 'ANIO' else date.month)
    age = anchor.year-date.year
    band = 'HASTA_1' if age<=1 else 'DE_2_A_3' if age<=3 else 'DE_4_A_5' if age<=5 else 'MAS_DE_5'
    return date.isoformat(), precision, period, band


def segments(row, place):
    count = len(row['caption'].split())
    n = integer(row['n_review_user'])
    profile = ('DESCONOCIDO' if n is None else 'SIN_HISTORIAL' if n==0 else
               'NOVATO' if n<=10 else 'INTERMEDIO' if n<=50 else 'EXPERIMENTADO')
    extension = ('SIN_TEXTO' if not row['caption'].strip() else 'MUY_BREVE' if count<=5 else
                 'BREVE' if count<=20 else 'MEDIA' if count<=60 else 'EXTENSA')
    date, precision, period, age = estimate_date(row['relative_date'],row['retrieval_date'])
    return dict(cantidad_palabras=count,tiene_texto=int(bool(row['caption'].strip())),
                n_resenas_autor_asof='' if n is None else n, segmento_perfil_autor=profile,
                segmento_extension=extension,fecha_estimada_analitica=date,
                precision_fecha_resena=precision,periodo_codigo=period,segmento_antiguedad=age,
                segmento_presencia_digital=presence(place))


def presence(place):
    web = bool(place.get('domain','').strip() or place.get('url','').strip())
    phone = bool(place.get('phoneNumber','').strip())
    return 'COMPLETA' if web and phone else 'SOLO_WEB' if web else 'SOLO_TELEFONO' if phone else 'NINGUNA'


class Progress:
    def __init__(self, mode):
        self.path = LOG_ROOT / f'{mode}/progreso.json'
        self.log = LOG_ROOT / f'{mode}/eventos.jsonl'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.started = time.monotonic()
        self.state = dict(version=VERSION,mode=mode,pid=os.getpid(),inicio=utcnow(),
                          estado='EN_CURSO',fase='inicio',procesadas=0,total=0,errores=0,
                          mensaje='',ultima_escritura=utcnow())
        self.last_event = ''
        self._mutex = threading.RLock()
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._heartbeat, daemon=True)
        self._thread.start()

    def _heartbeat(self):
        while not self._closed.wait(20):
            with self._mutex:
                if self.state['estado'] != 'EN_CURSO': continue
                self.state['ultimo_heartbeat'] = utcnow()
                atomic_json(self.path,self.state)

    def close(self):
        self._closed.set()
        self._thread.join(timeout=2)

    def update(self, phase=None, done=None, total=None, message='', **extra):
        with self._mutex:
            self._update(phase,done,total,message,**extra)

    def _update(self, phase=None, done=None, total=None, message='', **extra):
        if phase is not None and phase != self.state['fase']:
            self.state['unidad'] = 'registros'
        if phase is not None: self.state['fase']=phase
        if done is not None: self.state['procesadas']=int(done)
        if total is not None: self.state['total']=int(total)
        self.state.update(extra)
        self.state['ultima_escritura']=utcnow()
        self.state['ultimo_heartbeat']=self.state['ultima_escritura']
        self.state['segundos_transcurridos']=round(time.monotonic()-self.started,1)
        self.state['mensaje']=message
        atomic_json(self.path,self.state)
        event = self.state['fase'] + ':' + message
        if event != self.last_event or done is not None:
            with self.log.open('a',encoding='utf-8') as f:
                f.write(json.dumps(self.state,ensure_ascii=False)+'\n')
            self.last_event=event
        print(f"[{self.state['fase']}] {self.state['procesadas']:,}/{self.state['total']:,} {message}",flush=True)


class ProcessLock:
    def __init__(self,path):
        path.parent.mkdir(parents=True,exist_ok=True)
        self.f=path.open('a+b')
        try:
            self.f.seek(0)
            if not self.f.read(1): self.f.write(b'x'); self.f.flush()
            self.f.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.f.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:
            self.f.close()
            raise RuntimeError('Ya hay un proceso de preparación activo para esta corrida.') from exc

    def close(self): self.f.close()


def connect(path, *, factory=sqlite3.Connection, timeout=30):
    path.parent.mkdir(parents=True,exist_ok=True)
    cx=sqlite3.connect(path,timeout=timeout,factory=factory)
    cx.row_factory=sqlite3.Row
    cx.execute('PRAGMA journal_mode=DELETE')
    cx.execute('PRAGMA synchronous=FULL')
    cx.executescript('''
      CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS places (place_key TEXT PRIMARY KEY,country TEXT NOT NULL,
        place_id TEXT NOT NULL,raw_json TEXT NOT NULL,source TEXT NOT NULL,line INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS reviews (review_id TEXT PRIMARY KEY,country TEXT NOT NULL,
        place_key TEXT NOT NULL REFERENCES places(place_key),raw_json TEXT NOT NULL,
        text_hash TEXT NOT NULL,source TEXT NOT NULL,line INTEGER NOT NULL);
      CREATE INDEX IF NOT EXISTS ix_review_text ON reviews(text_hash);
      CREATE INDEX IF NOT EXISTS ix_review_place ON reviews(place_key);
      CREATE TABLE IF NOT EXISTS duplicates (id INTEGER PRIMARY KEY,review_id TEXT NOT NULL,
        discarded_place TEXT NOT NULL,raw_json TEXT NOT NULL,source TEXT NOT NULL,
        line INTEGER NOT NULL,distance_km REAL NOT NULL,reason TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS texts (text_hash TEXT PRIMARY KEY,text TEXT NOT NULL,
        language TEXT,language_score REAL,language_engine TEXT,sentiment TEXT,
        sentiment_score REAL,confidence REAL,p_negative REAL,p_neutral REAL,p_positive REAL,
        sentiment_model TEXT,tokens INTEGER,chunks INTEGER,nlp_status TEXT,
        topic_status TEXT,topics_json TEXT);
      CREATE INDEX IF NOT EXISTS ix_text_pending ON texts(nlp_status);
      CREATE INDEX IF NOT EXISTS ix_text_lang ON texts(language);
    ''')
    cx.execute('PRAGMA foreign_keys=ON')
    return cx


def meta_get(cx,key,default=None):
    result=cx.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
    return json.loads(result[0]) if result else default


def meta_set(cx,key,value):
    cx.execute('INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
               (key,json.dumps(value,ensure_ascii=False)))
