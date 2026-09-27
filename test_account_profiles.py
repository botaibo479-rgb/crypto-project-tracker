import unittest
from account_profiles import observed,failed

class AccountProfileTests(unittest.TestCase):
 def test_first_observation_is_not_a_change_and_later_changes_are_bounded(self):
  data={'name':'Founder','description':'Building','followersCount':20000,'profileImageUrl':'https://pbs.twimg.com/image'}
  first=observed({},data,100)
  self.assertEqual(first['history'],[])
  second=observed(first,{**data,'description':'New project','followersCount':20100},200)
  self.assertEqual(second['history'][-1]['fields'],['简介','粉丝数'])
  self.assertEqual(second['checkedAt'],200)
  self.assertNotIn('role',second)
 def test_failure_preserves_last_success_without_fake_freshness(self):
  old=observed({},{'name':'Founder','followersCount':20000},100)
  result=failed(old,200)
  self.assertEqual(result['checkedAt'],100)
  self.assertEqual(result['lastAttemptAt'],200)
  self.assertEqual(result['status'],'error')
  self.assertEqual(result['followers'],20000)
 def test_missing_followers_is_not_zero(self):
  for data in [{},{'followersCount':True},{'followersCount':-1}]:
   with self.assertRaises(ValueError):observed({},data,100)

if __name__=='__main__':unittest.main()
