import unittest
from charts import snapshot
from server import ema
class ChartTests(unittest.TestCase):
 def test_full_history_warmup_and_closed_only(self):
  rows=[[i*900000,'2','3','1','2','10',(i+1)*900000-1] for i in range(401)]
  d=snapshot(rows,'15m',400*900000,ema)
  self.assertEqual(d['warmupCount'],400);self.assertEqual(len(d['candles']),96)
  self.assertEqual(d['candles'][-1]['closeTime'],400*900000-1)
  self.assertEqual(d['candles'][-1]['ema200'],2);self.assertEqual(d['candles'][-1]['ema360'],2)
 def test_short_history_has_no_fake_ema(self):
  d=snapshot([[0,'2','3','1','2','10',899999]],'15m',900000,ema)
  self.assertIsNone(d['candles'][0]['ema360'])
 def test_invalid_period_rejected(self):
  with self.assertRaises(ValueError):snapshot([],'2s',1,ema)
if __name__=='__main__':unittest.main()
