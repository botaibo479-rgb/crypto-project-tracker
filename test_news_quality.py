import unittest
from news_quality import relevant,curate
class QualityTests(unittest.TestCase):
 def test_ambiguous_words_rejected(self):
  self.assertFalse(relevant('soon','A new feature is coming soon'))
  self.assertFalse(relevant('near','Trading near the high'))
  self.assertFalse(relevant('nil','Result: nil'))
  self.assertTrue(relevant('soon','SOON Network invests in Phala'))
  self.assertTrue(relevant('near','NEAR Intents launches an integration'))
 def test_same_original_dedup_and_provenance(self):
  rows=[dict(id='1',p='near',title='NEAR Protocol Launch',summary='',source='X · @NEARProtocol',url='https://twitter.com/NEARProtocol/status/123?s=20',publishedAt=1000),dict(id='2',p='near',title='NEAR Protocol Launch',summary='',source='OpenNews',url='https://x.com/nearprotocol/status/123',publishedAt=1000)]
  result=curate(rows,2000)
  self.assertEqual(len(result),1)
  self.assertEqual(result[0]['sourceCount'],2)
 def test_old_security_post_is_not_new_alert(self):
  rows=[dict(id='1',p='pha',title='Security vulnerability',summary='',source='Phala 官网',url='https://phala.com/posts/security',publishedAt=1000)]
  self.assertFalse(curate(rows,10*86400000)[0]['high'])
  self.assertTrue(curate(rows,2000)[0]['high'])
 def test_different_sources_not_auto_merged(self):
  base=dict(p='nil',title='Nillion launch',summary='',source='Media',publishedAt=1000)
  self.assertEqual(len(curate([{**base,'url':'https://a.com/a'},{**base,'url':'https://b.com/b'}],2000)),2)
class AmbiguousProjectTests(unittest.TestCase):
 def test_spark_requires_crypto_project_evidence(self):
  from news_quality import relevant
  p={'name':'Spark','symbol':'SPK','account':'sparkfinance','website':'https://spark.finance/'}
  for text in ['Nuclear deal could spark an arms race','Muse Spark AI model on Google Cloud','SPARK 2027 keynote speakers']:
   self.assertFalse(relevant('custom-spk',text,p))
  for text in ['Spark lending now supports USDS','News from @sparkfinance','Buyback of $SPK','Read spark.finance/blog']:
   self.assertTrue(relevant('custom-spk',text,p))

if __name__=='__main__':unittest.main()
