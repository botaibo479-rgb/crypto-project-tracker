import unittest
from collection_state import social_result,merge_news
class CollectionTests(unittest.TestCase):
 def test_failure_preserves_original_timestamp_and_accounts(self):
  previous={'updatedAt':100,'discussants':[{'account':'alice'}]}
  r=social_result(previous,{'status':'error','discussants':[]},200)
  self.assertEqual(r['updatedAt'],100);self.assertEqual(r['lastAttemptAt'],200);self.assertEqual(r['discussants'],previous['discussants']);self.assertTrue(r['stale'])
 def test_successful_empty_result_replaces_old_accounts(self):
  r=social_result({'discussants':[{'account':'alice'}]},{'status':'ok','discussants':[],'updatedAt':200},201)
  self.assertEqual(r['discussants'],[]);self.assertFalse(r['stale']);self.assertEqual(r['lastSuccessAt'],200)
 def test_news_failure_keeps_contents_and_success_time(self):
  rows,s=merge_news([{'id':'a','publishedAt':10,'discoveredAt':20}],[],{'X':{'status':'error'}},{'X':{'lastSuccessAt':30}},40)
  self.assertEqual(rows[0]['discoveredAt'],20);self.assertEqual(s['X']['lastSuccessAt'],30);self.assertEqual(s['X']['lastAttemptAt'],40)
if __name__=='__main__':unittest.main()
