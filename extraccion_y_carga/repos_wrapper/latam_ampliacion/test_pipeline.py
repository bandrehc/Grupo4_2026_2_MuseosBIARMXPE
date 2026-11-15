"""Pruebas del adaptador, sin corpus ni modelos."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import gzip
import csv
import sqlite3
import threading
import time
import json
from unittest.mock import patch
import contextlib
import io
from types import SimpleNamespace

spec=importlib.util.spec_from_file_location('ampliacion',Path(__file__).with_name('pipeline.py'))
p=importlib.util.module_from_spec(spec); spec.loader.exec_module(p)


class AdapterTests(unittest.TestCase):
    def row(self):
        row={k:'' for k in p.REVIEW_FIELDS}
        row.update(id_review='r',google_place_id='g',nombre_lugar='Museo',categoria_google='Museo de arte',
                   rating='5',review_date='2026-01-01T00:00:00Z',retrieval_date='2026-10-21T00:00:00Z',relative_date='hace 9 meses')
        return row

    def test_categories(self):
        self.assertTrue(p.museum('Museo'))
        self.assertTrue(p.museum('Museo Histórico'))
        self.assertFalse(p.museum('Museografía comercial'))

    def test_missing_rating_is_flag_not_drop(self):
        row=self.row(); row['rating']=''
        self.assertEqual(p.row_quality(row,{'AR:g'},'AR'),['RATING_AUSENTE'])
        self.assertEqual(row['rating'],'')

    def test_bad_rating_and_dates_flagged(self):
        row=self.row(); row.update(rating='6',review_date='2027-01-01',retrieval_date='2026-10-21')
        flags=p.row_quality(row,{'AR:g'},'AR')
        self.assertIn('RATING_INVALIDO',flags)
        self.assertIn('FECHA_RESENA_POSTERIOR_EXTRACCION',flags)

    def test_no_fabricated_dates(self):
        row=self.row(); row['review_date']=''
        self.assertIn('REVIEW_DATE_AUSENTE',p.row_quality(row,{'AR:g'},'AR'))
        self.assertEqual(row['review_date'],'')

    def test_missing_place(self):
        self.assertIn('LUGAR_SIN_BASE',p.row_quality(self.row(),set(),'AR'))

    def test_unicode_and_whitespace_cache_key(self):
        self.assertEqual(p.text_key('cafe\u0301  bonito\n'),p.text_key('café bonito'))
        self.assertNotEqual(p.text_key('bueno'),p.text_key('no bueno'))

    def test_preserve_original_fields_and_hash(self):
        row=self.row(); before=dict(row); h=p.content_hash(row)
        p.row_quality(row,{'AR:g'},'AR')
        self.assertEqual(row,before)
        row['caption']='otro texto'
        self.assertNotEqual(h,p.content_hash(row))

    def test_compressed_multiline_csv(self):
        row=self.row(); row['caption']='Texto, con coma\ny otra línea'
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.csv.gz'
            with gzip.open(path,'wt',encoding='utf-8-sig',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=p.REVIEW_FIELDS); writer.writeheader(); writer.writerow(row)
            self.assertEqual(list(p.rows(path)),[(2,row)])

    def test_prepare_export_three_countries(self):
        originals=p.REPO,p.WORK,p.OLD,p.TOPIC,p.STOP
        with tempfile.TemporaryDirectory() as folder:
            p.REPO=Path(folder); p.WORK=p.REPO/'work'; p.WORK.mkdir()
            p.OLD=p.REPO/'old'; p.TOPIC=p.OLD/'topics'; p.STOP=p.WORK/'stop.request'
            def write(rel,fields,records):
                path=p.REPO/rel; path.parent.mkdir(parents=True,exist_ok=True)
                opener=gzip.open if path.suffix=='.gz' else open
                with opener(path,'wt',encoding='utf-8-sig',newline='') as stream:
                    writer=csv.DictWriter(stream,fieldnames=fields); writer.writeheader(); writer.writerows(records)
            try:
                pe=self.row(); pe.update(id_review='pe',pais='Perú')
                ar=self.row(); ar.update(id_review='ar',pais='Argentina',rating='')
                mx=self.row(); mx.update(id_review='mx')
                place=dict(id='g',category='Museo de arte',lat='-34.6',lon='-58.4')
                for country,kind,rel in p.SOURCE_FILES:
                    if kind=='places': write(rel,list(place),[place])
                    elif kind=='verification': write(rel,p.REVIEW_FIELDS,[{k:ar[k] for k in p.REVIEW_FIELDS}])
                    elif country=='MX': write(rel,p.REVIEW_FIELDS,[mx])
                    else: write(rel,p.REVIEW_FIELDS+p.EXTRA,[{**pe,'corrida':'I','registro_completo':'True'},{**ar,'corrida':'AR','registro_completo':'False'}])
                catalog=dict(codigo_topico='test-T000',idioma='es',etiqueta='Prueba',descripcion='',palabras_clave='',version_modelo='test',metodo='S-BERT',validacion_etiqueta='PENDIENTE')
                write('old/final/S-BERT/catalogo_dimensiones_latentes.csv',list(catalog),[catalog])
                cx=p.connect(p.WORK/'checkpoint.sqlite')
                cx.executescript('CREATE TABLE review_quality(review_id TEXT PRIMARY KEY,flags TEXT,content_hash TEXT); CREATE TABLE place_quality(place_key TEXT PRIMARY KEY,flags TEXT); CREATE TABLE duplicate_sources(review_id TEXT,source TEXT,line INTEGER); CREATE TABLE argentina_raw_check(review_id TEXT PRIMARY KEY,content_hash TEXT);')
                p.prepare(cx,p.Progress())
                p.meta_set(cx,'topic_model',dict(version='test')); cx.commit()
                p.export(cx,p.Progress(),partial=True)
                result=list(p.rows(p.WORK/'fase1/base_madre_resenas.csv'))
                self.assertEqual(len(result),3)
                self.assertEqual({r['codigo_pais'] for _,r in result},{'PE','MX','AR'})
                ar_result=next(r for _,r in result if r['id_review']=='ar')
                self.assertEqual(ar_result['rating'],'')
                self.assertIn('RATING_AUSENTE',ar_result['banderas_calidad'])
                self.assertEqual(ar_result['estado_nlp'],'PENDIENTE')
                self.assertTrue(set(p.DERIVED)<=set(ar_result))
                self.assertEqual(ar_result['n_resenas_autor_asof'],'')
                with self.assertRaisesRegex(ValueError,'pendientes'):
                    p.export(cx,p.Progress(),partial=False)
                self.assertEqual(p.meta_get(cx,'argentina_raw_check')['changed_original_fields'],0)
                self.assertEqual(cx.execute('PRAGMA foreign_key_check').fetchall(),[])
                cx.close()
            finally: p.REPO,p.WORK,p.OLD,p.TOPIC,p.STOP=originals


class ResilienceTests(unittest.TestCase):
    def test_resume_validates_sources_then_skips_partial_export(self):
        script=Path(__file__).with_name('ejecutar.py')
        module_spec=importlib.util.spec_from_file_location('supervisor_ampliacion',script)
        supervisor=importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(supervisor)
        with tempfile.TemporaryDirectory() as folder, patch.object(supervisor,'WORK',Path(folder)), \
             patch.object(supervisor.sys,'argv',['ejecutar.py','--reanudar']), \
             patch.object(supervisor.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
            p.atomic_json(Path(folder)/'supervisor.json',dict(state='ERROR',stage='sentimiento'))
            supervisor.main()
            self.assertEqual([call.args[0][3] for call in run.call_args_list],
                             ['preparar','sentimiento','topicos','exportar'])

    def setup_database(self, folder):
        path=Path(folder)/'test.sqlite'
        writer=sqlite3.connect(path,factory=p.RetryingConnection,timeout=.02)
        writer.retry_delay=.01
        writer.execute('CREATE TABLE data(id INTEGER PRIMARY KEY,value TEXT)')
        writer.execute("INSERT INTO data VALUES (1,'original')"); writer.commit()
        reader=sqlite3.connect(path,check_same_thread=False)
        reader.execute('BEGIN'); reader.execute('SELECT * FROM data').fetchall()
        writer.execute("UPDATE data SET value='confirmado' WHERE id=1")
        return path,writer,reader

    def test_commit_waits_for_reader_without_repeating_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            path,writer,reader=self.setup_database(folder)
            events=[]; writer.on_commit_wait=lambda state,n:events.append(state)
            def release():
                time.sleep(.15); reader.rollback(); reader.close()
            thread=threading.Thread(target=release); thread.start()
            try:
                writer.commit(); thread.join()
                self.assertIn('ESPERANDO_LECTOR',events)
                self.assertEqual(events[-1],'RESUELTO')
                self.assertEqual(writer.execute('SELECT * FROM data').fetchall(),[(1,'confirmado')])
            finally:
                thread.join(); writer.close()
            check=sqlite3.connect(path)
            try: self.assertEqual(check.execute('SELECT value FROM data').fetchone()[0],'confirmado')
            finally: check.close()

    def test_persistent_lock_times_out_and_rollback_preserves_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            _,writer,reader=self.setup_database(folder)
            writer.retry_seconds=.07
            events=[]; writer.on_commit_wait=lambda state,n:events.append(state)
            try:
                with self.assertRaises(sqlite3.OperationalError): writer.commit()
                self.assertEqual(events[-1],'AGOTADO')
                self.assertTrue(writer.in_transaction)
                writer.rollback(); reader.rollback()
                self.assertEqual(writer.execute('SELECT value FROM data').fetchone()[0],'original')
            finally: reader.close(); writer.close()

    def test_status_default_never_opens_database(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(p,'WORK',Path(folder)), \
             patch.object(p.sys,'argv',['pipeline.py','estado']), \
             patch.object(p,'ro',side_effect=AssertionError('No abrir SQLite')):
            with contextlib.redirect_stdout(io.StringIO()) as output: p.main()
            self.assertEqual(json.loads(output.getvalue())['mode'],'SNAPSHOTS_SIN_CONSULTAR_SQLITE')
            self.assertFalse((Path(folder)/'checkpoint.sqlite').exists())

    def test_detailed_status_refuses_when_writer_lock_is_held(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(p,'WORK',Path(folder)), \
             patch.object(p.sys,'argv',['pipeline.py','estado','--detallado']), \
             patch.object(p,'ro',side_effect=AssertionError('No abrir SQLite')):
            lock=p.ProcessLock(Path(folder)/'process.lock')
            try:
                with self.assertRaises(RuntimeError): p.main()
            finally: lock.close()

    def test_error_event_does_not_overwrite_last_confirmed_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(p,'WORK',Path(folder)):
            progress=p.Progress()
            with contextlib.redirect_stdout(io.StringIO()):
                progress.update('nlp_textos_unicos',256,1000,ultimo_checkpoint=p.utcnow())
                progress.update('ERROR',message='error posterior')
            snapshot=json.loads((Path(folder)/'checkpoint_confirmado.json').read_text(encoding='utf-8'))
            self.assertEqual(snapshot['done'],256)


if __name__=='__main__': unittest.main()
