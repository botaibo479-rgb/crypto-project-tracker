"""Public account observations are not team-role verification."""
import re

def observed(previous, data, now):
 if not isinstance(data,dict) or type(data.get('followersCount')) is not int or data['followersCount']<0:
  raise ValueError('Invalid account profile')
 fields={'name':data.get('name') or '', 'description':data.get('description') or '',
         'avatar':data.get('profileImageUrl') or '', 'followers':data['followersCount']}
 if any(not isinstance(fields[k],str) for k in ('name','description','avatar')):raise ValueError('Invalid profile text')
 if not re.match(r'^https://pbs\.twimg\.com/',fields['avatar']):fields['avatar']=''
 changes=[]
 if previous.get('checkedAt'):
  labels={'name':'显示名称','description':'简介','avatar':'头像','followers':'粉丝数'}
  changes=[labels[k] for k in fields if previous.get(k)!=fields[k]]
 history=list(previous.get('history',[]))
 if changes:history.append({'at':now,'fields':changes})
 return {**fields,'checkedAt':now,'lastAttemptAt':now,'status':'ok','history':history[-20:]}

def failed(previous, now):
 return {**previous,'lastAttemptAt':now,'status':'error'}
