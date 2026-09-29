"""Conservative same-event grouping with inspectable reasons and full source retention."""
import re,hashlib
from news_quality import canonical_url
from urllib.parse import urlsplit

def references(e):
 urls=re.findall(r'https?://[^\s<>]+',e.get('summary',''))+[e.get('url','')]
 result=set()
 for url in urls:
  url=url.rstrip('.,，。)');u=urlsplit(url)
  if u.hostname in ['t.co','bit.ly'] or not u.hostname:continue
  if len(u.path.strip('/'))<8:continue
  if u.hostname in ['x.com','twitter.com'] and '/status/' not in u.path:continue
  result.add(canonical_url(url))
 return result

def same_event(a,b):
 if a['p']!=b['p']:return None
 if not a.get('publishedAt') or not b.get('publishedAt') or abs(a['publishedAt']-b['publishedAt'])>48*3600000:return None
 from reader_quality import normalized
 ta,tb=normalized(a.get('summary') or a.get('title')),normalized(b.get('summary') or b.get('title'))
 if ta and ta==tb and len(ta)>=12 and abs(a['publishedAt']-b['publishedAt'])<=2*3600000:return '标准化正文一致，发布时间相差不超过 2 小时'
 if references(a)&references(b):return '共同引用同一篇原文，发布时间相差不超过 48 小时'
 def words(e):return re.findall(r'[a-z0-9]+|[\u4e00-\u9fff]',re.sub(r'https?://\S+','',e.get('summary','')).lower())
 wa,wb=words(a),words(b)
 if min(len(wa),len(wb))<30:return None
 # Changed amounts/dates can be a new development and must remain separately visible.
 if set(re.findall(r'\d+(?:\.\d+)?',a.get('summary','')))!=set(re.findall(r'\d+(?:\.\d+)?',b.get('summary',''))):return None
 sa,sb=set(wa),set(wb)
 if len(sa&sb)/max(1,len(sa|sb))>=.92:return '正文高度重合，数字一致，发布时间相差不超过 48 小时'
 return None

def progress_candidates(group):
 def facts(item):
  text=re.sub(r'https?://\S+','',item.get('summary','')).lower()
  values=set(re.findall(r'(?:\$\s*\d[\d,.]*|\d[\d,.]*\s*(?:%|million|billion|usd|usdt|万美元|亿美元|万枚|亿枚))',text))
  states={'上线确认':r'now live|is live|已上线|正式上线','暂停':r'has paused|suspended|暂停提现|暂停提款|已暂停','恢复':r'resumed|restored|已恢复|恢复提现','修复':r'has been patched|fix deployed|已修复|修复完成'}
  for label,pattern in states.items():
   if re.search(pattern,text):values.add(label)
  return values
 if len(group)<2:return []
 known=facts(group[0]);out=[]
 for item in group[1:]:
  current=facts(item);added=current-known;known|=current
  if added and (item.get('publishedAt') or 0)>(group[0].get('publishedAt') or 0):
   key=hashlib.sha256('|'.join(sorted(added)).encode()).hexdigest()[:16]
   out.append({'key':key,'publishedAt':item['publishedAt'],'discoveredAt':item.get('discoveredAt'),'url':item.get('url'),'source':item.get('source'),'signals':sorted(added),'reason':'后续报道出现新的金额、比例或状态表述；仅为规则识别候选，需核对原文'})
 return out

def cluster(rows):
 groups=[]
 for e in sorted(rows,key=lambda e:(e.get('publishedAt') or 0,e['id'])):
  target=None;reason=None
  for group in reversed(groups):
   # Compare to anchor only; do not chain weakly related stories across a group.
   reason=same_event(group[0],e)
   if reason:target=group;break
  if target is None:groups.append([e])
  else:target.append({**e,'clusterReason':reason})
 result=[]
 for group in groups:
  first=group[0];out=dict(first)
  if len(group)>1:
   out['relatedItems']=[{k:v for k,v in e.items() if k!='relatedItems'} for e in group]
   out['progressCandidates']=progress_candidates(group)
   out['clusterSize']=len(group);out['clusterReason']='按原文引用或高度重合正文归并；不代表多方独立证实'
   sources=[]
   for e in group:
    for s in e.get('sourcesList',[]):
     if s not in sources:sources.append(s)
   out['sourcesList']=sources;out['sourceCount']=len(sources)
   out['lastRelatedAt']=max(e.get('publishedAt') or 0 for e in group)
   out['independenceNote']=out['clusterReason']
   out['revision']=hashlib.sha256('|'.join(sorted(e['id'] for e in group)).encode()).hexdigest()[:16]
  result.append(out)
 return sorted(result,key=lambda e:e.get('publishedAt') or 0,reverse=True)
