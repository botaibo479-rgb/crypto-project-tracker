"""Merge failed collection attempts without disguising old results as fresh."""
def social_result(previous,result,attempted_at):
 merged=dict(result);merged['lastAttemptAt']=attempted_at
 if result.get('status')=='ok':merged['lastSuccessAt']=result.get('updatedAt',attempted_at);merged['stale']=False
 else:
  merged['discussants']=previous.get('discussants',[])
  merged['lastSuccessAt']=previous.get('lastSuccessAt') or previous.get('updatedAt')
  merged['updatedAt']=previous.get('updatedAt');merged['stale']=bool(merged['discussants'])
 return merged

def merge_news(existing,items,status,previous_status,attempted_at):
 by_id={e['id']:dict(e) for e in existing}
 for item in items:
  item=dict(item)
  if item['id'] in by_id:item['discoveredAt']=by_id[item['id']].get('discoveredAt',attempted_at)
  by_id[item['id']]=item
 sources={}
 for name,entry in status.items():
  e=dict(entry);e['lastAttemptAt']=attempted_at
  if not e.get('lastSuccessAt'):e['lastSuccessAt']=previous_status.get(name,{}).get('lastSuccessAt')
  sources[name]=e
 return sorted(by_id.values(),key=lambda e:e.get('publishedAt') or 0)[-400:],sources
