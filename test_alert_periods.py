import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from alerts import validate,evaluate,chart_market,Store
NOW=1800000000000
class PeriodTests(unittest.TestCase):
 def rule(self,period):
  return dict(id='r',p='near',type='ema',name='EMA',period=period,threshold=5,cooldownMinutes=60,on=True,createdAt=NOW-86400000)
 def snapshot(self,period,at):
  return dict(period=period,candles=[dict(close=9,ema200=10,ema360=10,closeTime=at-1),dict(close=11,ema200=10,ema360=10,closeTime=at)])
 def test_valid_periods_and_rejection(self):
  for kind in ['ema','level','combo']:
   for period in ['1h','4h','1d']:
    self.assertEqual(validate({**self.rule(period),'type':kind},['near'])['period'],period)
  with self.assertRaises(ValueError):validate(self.rule('15m'),['near'])
 def test_daily_freshness_cross_and_deduplication(self):
  m=chart_market({},self.snapshot('1d',NOW-12*3600000));rt={}
  result=evaluate(self.rule('1d'),rt,m,[],NOW)
  self.assertEqual(len(result),1);self.assertEqual(result[0]['evidence']['period'],'1d')
  self.assertEqual(evaluate(self.rule('1d'),rt,m,[],NOW),[])
  self.assertEqual(evaluate(self.rule('1h'),{},m,[],NOW),[])
 def test_wrong_period_never_triggers_even_when_recent(self):
  m=chart_market({},self.snapshot('1d',NOW))
  self.assertEqual(evaluate(self.rule('1h'),{},m,[],NOW),[])
 def test_insufficient_ema_never_falls_back_to_base(self):
  snap=self.snapshot('1h',NOW);snap['candles'][-1]['ema360']=None
  m=chart_market({'ema360':1,'cross':'up'},snap)
  self.assertEqual(evaluate(self.rule('1h'),{},m,[],NOW),[])
 def test_store_selects_period_and_missing_data_does_not_use_four_hour(self):
  with tempfile.TemporaryDirectory() as d:
   store=Store(Path(d)/'alerts.json');store.data['rules']=[self.rule('1h')]
   four={'marker':'4h'};one={'marker':'1h'}
   with patch('alerts.evaluate',return_value=[]) as check:
    store.tick({'near':four,('near','1h'):one},[],NOW)
    self.assertEqual(check.call_args.args[2],one)
    store.tick({'near':four},[],NOW);self.assertIsNone(check.call_args.args[2])
