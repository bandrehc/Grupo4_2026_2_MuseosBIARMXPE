"""Regresión sin Internet: fechas, CSV, cardinalidad, locks y checkpoints."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'repos_wrapper/fases12'))
from common import estimate_date,integer,text_key,read_csv,connect,meta_set,meta_get,ProcessLock,REVIEW_FIELDS
from dataset import export,priority,distance
from validate import validate

class SilentProgress:
    def update(self,*args,**kwargs): pass

class Contracts(unittest.TestCase):
    def test_calendar_month(self):
        date,precision,period,_=estimate_date('hace un mes','2026-03-31T12:00:00Z')
        self.assertEqual((date[:10],precision,period),('2026-02-01','MES',202602))
    def test_year_precision(self):
        self.assertEqual(estimate_date('hace 2 años','2026-10-11T12:00:00Z')[1:3],('ANIO',202400))
    def test_hours_cross_month(self):
        self.assertEqual(estimate_date('hace 23 horas','2026-03-01T12:00:00Z')[2],202602)
    def test_unknown_relative(self):
        self.assertEqual(estimate_date('Fecha desconocida','2026-10-11T12:00:00Z')[:3],('','NA',-1))
    def test_integers(self):
        self.assertEqual(integer('1,254'),1254)
        self.assertIsNone(integer(''))
        for bad in ['-3','nanx','4.5','inf']:
            with self.assertRaises(ValueError): integer(bad)
    def test_computational_not_review_dedup(self):
        self.assertEqual(text_key('café\n bonito'),text_key('café bonito'))
        self.assertNotEqual(text_key('Bueno'),text_key('bueno'))
    def test_malformed_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.csv'; path.write_text('a,b\n1,2,3\n',encoding='utf8')
            with self.assertRaises(ValueError): list(read_csv(path))
    def test_os_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'process.lock'; a=ProcessLock(path)
            try:
                with self.assertRaises(RuntimeError): ProcessLock(path)
            finally: a.close()
            b=ProcessLock(path); b.close()
    def test_rollback_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'ck.sqlite'; c=connect(path)
            meta_set(c,'saved',1); c.commit(); meta_set(c,'not_committed',2); c.close()
            c=connect(path); self.assertEqual(meta_get(c,'saved'),1); self.assertIsNone(meta_get(c,'not_committed')); c.close()
    def test_priority_prefers_complete_text(self):
        a={'caption':'Bueno','retrieval_date':'2026-10-10T00:00:00Z','google_place_id':'A'}
        b={**a,'caption':'Bueno y bonito','retrieval_date':'2026-09-10T00:00:00Z'}
        self.assertGreater(priority(b),priority(a))
    def test_distance(self):
        self.assertAlmostEqual(distance({'lat':'-12','lon':'-77'},{'lat':'-12','lon':'-77'}),0)
    def test_export_preserves_originals_and_idempotence(self):
        with tempfile.TemporaryDirectory() as tmp:
            c=connect(Path(tmp)/'ck.sqlite'); place=dict(id='m1',lat='-12',lon='-77',domain='',url='',phoneNumber='',category='Museo')
            c.execute('INSERT INTO places VALUES (?,?,?,?,?,?)',('PE:m1','PE','m1',json.dumps(place),'source_places.csv',2))
            review={field:'' for field in REVIEW_FIELDS}
            review.update(google_place_id='m1',nombre_lugar='Museo Ñ',categoria_google='Museo',
                          id_review='r1',caption='',rating='4',relative_date='hace un mes',
                          review_date='2026-09-11T00:00:00Z',retrieval_date='2026-10-11T00:00:00Z',username='Autor real')
            h=text_key('')
            c.execute('INSERT INTO reviews VALUES (?,?,?,?,?,?,?)',('r1','PE','PE:m1',json.dumps(review),h,'source_reviews.csv',2))
            c.execute("INSERT INTO texts(text_hash,text,nlp_status,sentiment,topic_status,topics_json) VALUES (?,?,'SIN_TEXTO','SIN_TEXTO','SIN_TEXTO','[]')",(h,''))
            meta_set(c,'input_spec',dict(version='fases12-1.0.0',mode='piloto',sources=[dict(kind='places',columns=list(place))]))
            meta_set(c,'phase1_done',True); meta_set(c,'counts',dict(reviews=1,places=1,rows_input=1,duplicates=0,unique_texts=0)); c.commit()
            folder=Path(tmp)/'final'; first=export(c,folder,SilentProgress()); stats=validate(folder)
            self.assertEqual(stats['resenas'],1)
            saved=list(read_csv(folder/'base_madre_resenas.csv'))[0][1]
            self.assertEqual({f:saved[f] for f in REVIEW_FIELDS},review)
            second=export(c,folder,SilentProgress())
            self.assertEqual([o['sha256'] for o in first['outputs']],[o['sha256'] for o in second['outputs']])
            c.close()

if __name__=='__main__': unittest.main()
