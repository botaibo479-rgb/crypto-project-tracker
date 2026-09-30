"""Reader ranking, reversible noise folding and cross-project presentation grouping."""
import re,hashlib
from news_quality import canonical_url
from urllib.parse import urlsplit

def normalized(text):
 return ' '.join(re.findall(r'[a-z0-9]+|[\u4e00-\u9fff]',re.sub(r'https?://\S+','',text or '').lower()))

def quality(e):
 text=(e.get('summary') or e.get('title') or '').strip();channel=e.get('channel','opennews')
 plain=re.sub(r'https?://\S+|@[A-Za-z0-9_]+','',text)
 chars=re.findall(r'[A-Za-z0-9\u4e00-\u9fff]',plain)
 social=channel in {'x','team'} or '/status/' in e.get('url','')
 reason=''
 if social:
  if e.get('isRetweet') or re.match(r'^RT\s+@',text,re.I):reason='纯转发'
  elif e.get('isReply') or text.startswith('@'):reason='回复 / 互动'
  elif len(chars)<18 and not re.search(r'mainnet.{0,15}(?:live|launched)|主网.{0,10}上线|暂停提现|暂停提款|漏洞已修复|ETF.{0,15}approved',text,re.I):reason='去除链接与互动符号后信息量较低'
 source_points={'official':30,'x':30,'team':24,'opennews':16,'kol':10,'subscription':22}.get(channel,10)
 category={'ETF / 机构产品':25,'安全风险':40,'交易所动态':25,'代币机制':20,'项目合作':15,'产品进展':15}.get(e.get('topic'),0)
 concrete=bool(re.search(r'\d+(?:[.,]\d+)?\s*(?:%|million|billion|tokens?|USDT|USD|枚|万|亿|月|日)|\$\s*\d|\d{4}[-/]\d{1,2}|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d',text,re.I))
 action=bool(re.search(r'now live|has launched|has listed|will list|has completed|已上线|已完成|正式发布|已回购|已销毁|已下架',text,re.I))
 hype=bool(re.search(r'coming soon|something (?:big|huge)|stay tuned|big things|很快.*大事|敬请期待|即将揭晓',text,re.I))
 score=max(0,min(100,source_points+category+15*concrete+10*action-25*hype-50*bool(reason)))
 parts=[f'信源 {source_points}',f'类别 {category}']
 if concrete:parts.append('具体数字或日期 +15')
 if action:parts.append('明确进展表述 +10')
 if hype:parts.append('预告措辞 -25')
 if reason:parts.append('低信息量 -50')
 return {'qualityScore':score,'lowInformation':bool(reason),'lowInformationReason':reason,'high':score>=65 and e.get('freshness')=='recent' and not reason,'priorityReason':'；'.join(parts)+'。排序参考，不是事实核验或价格预测。'}

def presentation(rows):
 """One original URL across projects becomes one card, keeping all evidence and old ids."""
 groups={}
 for e in sorted(rows,key=lambda x:(x.get('publishedAt') or 0,x['id'])):
  url=canonical_url(e.get('url','')) if e.get('url') else ''
  key=url or e['id']
  if key not in groups:
   groups[key]={**e,'projectIds':[e['p']],'memberIds':list(dict.fromkeys([e['id']]+[x['id'] for x in e.get('relatedItems',[])]))}
  else:
   g=groups[key];g['projectIds']=sorted(set(g['projectIds']+[e['p']]));g['memberIds']=list(dict.fromkeys(g['memberIds']+[e['id']]+[x['id'] for x in e.get('relatedItems',[])]))
   # Do not discard per-project source evidence, including an existing cluster.
   if 'crossProjectItems' not in g:g['crossProjectItems']=[{**g}]
   g['crossProjectItems'].append(e)
   if e.get('qualityScore',0)>g.get('qualityScore',0):
    for field in ['qualityScore','high','priorityReason','lowInformation','lowInformationReason']:g[field]=e.get(field)
 out=list(groups.values())
 for g in out:
  items=g.get('relatedItems',[g])+g.get('crossProjectItems',[])
  domains={urlsplit(x.get('url','')).hostname for x in items if x.get('url')}
  # X reposts / repeated provider entries cannot establish independent corroboration.
  domains.discard('x.com');domains.discard('twitter.com');domains.discard(None)
  bonus=min(10,max(0,len(domains)-1)*5)
  g['qualityScore']=min(100,g.get('qualityScore',0)+bonus)
  if bonus:g['priorityReason']+='；不同发布域名 +'+str(bonus)+'（不保证独立信源）'
  g['high']=g['qualityScore']>=65 and g.get('freshness')=='recent' and not g.get('lowInformation')
 return sorted(out,key=lambda e:e.get('publishedAt') or 0,reverse=True)

def topic_key(e):
 if e.get('providerKind') or e.get('lowInformation'):return None
 text=(e.get('summary') or e.get('title') or '')
 for topic,pattern in [('ETF',r'\bETF\b|交易所交易基金'),('安全事件',r'\bhack|\bexploit|漏洞|被盗'),('主网上线',r'\bmainnet\b|主网上线'),('代币解锁',r'\bunlock|代币解锁')]:
  if re.search(pattern,text,re.I):return topic
 return None
