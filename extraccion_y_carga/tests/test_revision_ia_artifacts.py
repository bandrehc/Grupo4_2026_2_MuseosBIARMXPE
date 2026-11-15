"""Integridad de la revisión congelada: no requiere corpus, modelos ni SQL Server."""
import collections
import hashlib
import json
from pathlib import Path
import unittest
import csv
import os
import shutil
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parents[1]/'carga_sql_server/revision_ia_v1'

def read(name):
    return json.loads((HERE/name).read_text(encoding='utf-8'))

class RevisionArtifacts(unittest.TestCase):
    def test_perfilador_usa_la_carpeta_del_clon(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);repo=base/'otro nombre del clon';scripts=repo/'carga_sql_server'
            scripts.mkdir(parents=True)
            shutil.copy2(HERE.parent/'perfilar.py',scripts/'perfilar.py')
            source=repo/'data/preparacion_latam/ampliacion_2026-10-22_v1/final'
            source.mkdir(parents=True)
            with (source/'base_madre_lugares.csv').open('w',encoding='utf-8-sig',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(['codigo_pais','stars','reviews'])
                writer.writerow(['PE','4.5','12'])
            private=base/'privado';(private/'MuseosLatamSQL').mkdir(parents=True)
            result=subprocess.run([sys.executable,'-B',str(scripts/'perfilar.py')],cwd=base,
                env=dict(os.environ,LOCALAPPDATA=str(private)),capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            profile=json.loads((scripts/'perfil_fuentes.json').read_text(encoding='utf-8'))
            self.assertEqual(profile['base_madre_lugares.csv']['rows'],1)

    def test_frozen_bytes_match_manifest(self):
        for name,expected in read('manifiesto_revision.json')['archivos'].items():
            with self.subTest(name=name):
                self.assertEqual(hashlib.sha256((HERE/name).read_bytes()).hexdigest(),expected)

    def test_complete_catalog_and_sample_accounting(self):
        catalog=read('catalogo_curado.json');samples=read('evaluaciones_topicos.json')
        self.assertEqual(len(catalog),41)
        self.assertEqual(len({r['codigo_topico'] for r in catalog}),41)
        self.assertEqual(len(samples),488)
        self.assertEqual(sum(r['apto_analisis_tematico'] for r in catalog),22)
        for row in catalog:
            counts=collections.Counter(s['juicio'] for s in samples if s['codigo_topico']==row['codigo_topico'])
            self.assertEqual(sum(counts.values()),row['muestra_n'])
            self.assertEqual((counts['C'],counts['P'],counts['N']),
                             (row['coherentes_n'],row['parciales_n'],row['no_coherentes_n']))

    def test_distinct_definitions_and_no_fake_human_approval(self):
        catalog=read('catalogo_curado.json')
        self.assertEqual(len({r['descripcion'] for r in catalog}),41)
        self.assertIs(read('manifiesto_revision.json')['validacion_humana'],False)
        for row in catalog:
            self.assertTrue(row['criterios_inclusion'] and row['criterios_exclusion'] and row['limitaciones'])
            self.assertIn('REVISADO_IA_',row['validacion_etiqueta'])

    def test_sentiment_evidence_has_traceable_ids_and_hashes(self):
        rows=read('evaluaciones_sentimiento.json')
        self.assertEqual(len(rows),54)
        self.assertEqual({r['numero'] for r in rows},set(range(1,55)))
        for row in rows:
            self.assertTrue(row['id_review'])
            self.assertRegex(row['sha256_texto'],r'^[0-9a-f]{64}$')

if __name__=='__main__':unittest.main()
