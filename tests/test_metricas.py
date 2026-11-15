"""Pruebas offline, separadas de los tests de integración que necesitan SQL Server."""
import sys
import unittest
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dashboard'))
from metricas import benchmark


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.lugares = pd.DataFrame([dict(sk_lugar=i, nombre=str(i), pais='Perú', categoria='museo') for i in (1, 2)])
        self.datos = pd.DataFrame([
            dict(sk_lugar=i, pais='Perú', categoria='museo', anio=year, n_resenas=40,
                 n_ratings=40, suma_rating=40*rating, n_rating_neg=0, n_pos=20, n_neu=10, n_neg=10)
            for i, year, rating in [(1, 2020, 1), (2, 2020, 5), (1, 2025, 5), (2, 2025, 1)]])

    def calc(self, years):
        return benchmark(self.datos, self.lugares, ['Perú'], ['museo'], years).set_index('sk_lugar')

    def test_year_changes_ranking_and_counts(self):
        old, new = self.calc([2020,2020]), self.calc([2025,2025])
        self.assertLess(old.loc[1,'rating_suavizado'], old.loc[2,'rating_suavizado'])
        self.assertGreater(new.loc[1,'rating_suavizado'], new.loc[2,'rating_suavizado'])
        self.assertEqual(new.loc[1,'n_ratings'], 40)
        self.assertEqual(new.loc[1,'pct_rank_pares'], 1)

    def test_rating_weighted_and_prior(self):
        d = self.calc([2020,2025])
        self.assertEqual(d.loc[1,'rating_prom'], 3)
        self.assertEqual(d.loc[1,'media_grupo'], 3)
        self.assertEqual(d.loc[1,'pct_rank_pares'], 0)  # empate

    def test_no_ratings_and_no_classified_is_unknown(self):
        self.datos[['n_ratings','suma_rating','n_pos','n_neu','n_neg']] = 0
        d = self.calc([2020,2025])
        self.assertTrue(d.rating_prom.isna().all())
        self.assertTrue(d.pct_neg.isna().all())
        self.assertTrue(d.pct_rank_pares.isna().all())

    def test_empty_filter(self):
        self.assertTrue(self.calc([1900,1901]).empty)

    def test_duplicate_metadata_rejected(self):
        with self.assertRaises(ValueError):
            benchmark(self.datos, pd.concat([self.lugares,self.lugares]), ['Perú'], ['museo'], [2020,2025])

    def test_single_peer_percentile_zero(self):
        self.datos = self.datos[self.datos.sk_lugar==1]
        self.assertEqual(self.calc([2020,2025]).loc[1,'pct_rank_pares'], 0)

    def test_country_filter(self):
        self.assertTrue(benchmark(self.datos,self.lugares,['Argentina'],['museo'],[2020,2025]).empty)


if __name__ == '__main__': unittest.main()
