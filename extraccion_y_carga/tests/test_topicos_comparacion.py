import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'repos_wrapper/topicos_comparacion'))
from experiment import eligibility,save_csv,connection
import tempfile

class ComparisonTests(unittest.TestCase):
    def test_short_and_languages(self):
        self.assertEqual(eligibility('','es'),'SIN_TEXTO')
        self.assertEqual(eligibility('excelente museo','es'),'SIN_SENAL_TEMATICA')
        self.assertIsNone(eligibility('el museo tiene buena accesibilidad','xx'))
        self.assertEqual(eligibility('the museum has good accessibility','en'),'IDIOMA_FUERA_ALCANCE')
    def test_atomic_unicode(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); report=save_csv(p,'a.csv',['texto'],[{'texto':'Perú, México\nexposición'}])
            self.assertEqual(report['rows'],1)
            self.assertTrue((p/'a.csv').read_bytes().startswith(b'\xef\xbb\xbf'))
    def test_checkpoint_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'c.sqlite'; cx=connection(p)
            cx.execute('INSERT INTO assignments VALUES (?,?,?)',('h','OK','[["t",1.0]]')); cx.commit(); cx.close()
            cx=connection(p); self.assertEqual(cx.execute('SELECT COUNT(*) FROM assignments').fetchone()[0],1); cx.close()

if __name__=='__main__': unittest.main()
