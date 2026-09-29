import unittest
from event_clusters import cluster,progress_candidates
class ClusterTests(unittest.TestCase):
 def event(self,id,body,p='near',date=1000):return dict(id=id,p=p,publishedAt=date,summary=body,url='https://x.com/a/status/'+id,sourcesList=[{'name':'Source '+id,'url':'https://x.com/a/status/'+id}])
 def test_progress_only_marks_new_structured_claims(self):
  first=self.event('1','Raised $100 million https://near.org/blog/funding')
  repeat=self.event('2','Raised $100 million https://near.org/blog/funding',date=2000)
  update=self.event('3','Now live, funding reaches $200 million https://near.org/blog/funding',date=3000)
  self.assertEqual(progress_candidates([first,repeat]),[])
  candidates=progress_candidates([first,repeat,update]);self.assertEqual(len(candidates),1)
  self.assertIn('上线确认',candidates[0]['signals'])
 def test_common_original_merges_with_provenance(self):
  r=cluster([self.event('1','Launch https://near.org/blog/upgrade-2026'),self.event('2','Team explains https://near.org/blog/upgrade-2026',date=2000)])
  self.assertEqual(len(r),1);self.assertEqual(len(r[0]['relatedItems']),2);self.assertEqual(r[0]['sourceCount'],2)
 def test_different_project_date_and_homepage_do_not_merge(self):
  for second in [self.event('2','https://near.org/'),self.event('2','https://near.org/blog/upgrade-2026',p='pha'),self.event('2','https://near.org/blog/upgrade-2026',date=200000000)]:
   self.assertEqual(len(cluster([self.event('1','https://near.org/blog/upgrade-2026'),second])),2)
 def test_changed_numeric_claims_not_merged_by_text(self):
  text='NEAR Protocol '+('this upgrade improves infrastructure and performance for every developer building decentralized applications across the network '*4)
  self.assertEqual(len(cluster([self.event('1',text+' 100 million'),self.event('2',text+' 200 million')])),2)
 def test_exact_short_posts_merge_only_in_two_hour_window(self):
  self.assertEqual(len(cluster([self.event('1','NEAR launches upgrade'),self.event('2','NEAR launches upgrade')])),1)
  self.assertEqual(len(cluster([self.event('1','NEAR launches upgrade'),self.event('2','NEAR launches upgrade',date=3*3600000)])),2)
if __name__=='__main__':unittest.main()
