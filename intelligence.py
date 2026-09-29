"""Evidence-preserving OpenNews signals and macro calendar; no trading actions."""
import datetime as dt,hashlib,html,json,re,threading,time
from pathlib import Path
from html.parser import HTMLParser
LABELS={'listing':'交易所公告','funding':'资金费率','liquidation':'大额清算','flow':'资金动态','oi':'短时 OI','price':'价格异动'}
class Text(HTMLParser):
 def __init__(self):super().__init__();self.parts=[]
 def handle_data(self,data):self.parts.append(data)
 def handle_starttag(self,tag,attrs):
  if tag in {'br','p','div'}:self.parts.append(' ')
def plain(value):
 parser=Text();parser.feed(str(value or ''));return ' '.join(html.unescape(' '.join(parser.parts)).split())
def kind(row):
 engine=row.get('engineType');source=row.get('newsType','')
 if engine=='listing':return 'listing'
 if source in {'funding_rate','funding_diff'}:return 'funding'
 if source=='liquidation':return 'liquidation'
 if source in {'smart_money','6551OnChain'} or engine=='onchain':return 'flow'
 if engine=='market' and source in {'oi_change','price_change'}:return 'oi' if source=='oi_change' else 'price'
 return None
def listing_type(text):
 for name,pattern in [('下架',r'delist|下架'),('充提调整',r'withdraw|deposit|充提|提币|提款|充值'),('合约调整',r'perpetual|futures|leverage|合约|杠杆'),('上币',r'will list|new listing|trading.*(?:start|open)|上线|上市')]:
  if re.search(pattern,text,re.I):return name
 return '其他公告'
def amount(text):
 # Only use explicitly labelled liquidation amount, never position size or a price.
 match=re.search(r'(?:liquidat(?:ed|ion)(?:\s+(?:value|amount))?|清算金额|爆仓金额)\s*[:：]?\s*\$([\d,]+(?:\.\d+)?)\s*([KMB])?\b',text,re.I)
 if not match:return None
 return float(match[1].replace(',',''))*{'K':1e3,'M':1e6,'B':1e9}.get((match[2] or '').upper(),1)
def normalize(row,p,stamp,current):
 category=kind(row)
 if not category:return None
 text=plain(row.get('text'));symbol=p['symbol'].upper()
 coins={str(c.get('symbol','')).upper() for c in row.get('coins',[]) if isinstance(c,dict)}
 # Provider mapping PLUS explicit token syntax / project identity. Never accept bare NEAR/SOON.
 explicit=bool(re.search(r'\$'+re.escape(symbol)+r'\b|(?<![\w])'+re.escape(symbol)+r'(?:/|[-_])(?:USDT|USD|USDC)\b|(?<![\w])'+re.escape(symbol)+r'USDT\b',text,re.I))
 from news_quality import relevant
 if not ((symbol in coins and (explicit or relevant(p['id'],text,p))) or relevant(p['id'],text,p)):return None
 date=stamp(row.get('ts'))
 if not date or not 0<=current-date<=7*86400000:return None
 rid=str(row.get('id') or hashlib.sha256(text.encode()).hexdigest())
 source=str(row.get('source') or row.get('newsType') or 'OpenNews')
 url=str(row.get('link') or '');url=url if url.startswith('https://') else ''
 return dict(id='news-'+hashlib.sha256((p['id']+'opennews:'+rid).encode()).hexdigest()[:20],providerId=rid,p=p['id'],type='news',channel='opennews',title=text[:140],summary=text,url=url,publishedAt=date,discoveredAt=current,source=source,providerKind=category,providerSubtype=row.get('newsType'),engineType=row.get('engineType'),topic=LABELS[category],listingType=listing_type(text) if category=='listing' else None,amountUsd=amount(text) if category=='liquidation' else None,providerRating=row.get('aiRating') or {},coins=row.get('coins') or [],matchReason='项目标识与来源资产信息匹配，仍需核对同名资产',evidence='OpenNews 事件记录；非连续行情',high=False,priorityReason='按需配置独立提醒',freshness='recent',datePrecision='source')
def merge(old,new,current):
 rows={e['id']:e for e in old if 0<=current-e.get('publishedAt',0)<=7*86400000}
 for e in new:rows[e['id']]={**e,'discoveredAt':rows.get(e['id'],e)['discoveredAt']}
 return sorted(rows.values(),key=lambda e:e['publishedAt'],reverse=True)[:1500]
def calendar_rows(response,stamp):
 if response.get('success') is False:raise ValueError('calendar_failed')
 data=response.get('data',{})
 if isinstance(data,dict):
  if data.get('status') not in {None,'ok','partial_result'}:raise ValueError('calendar_'+str(data['status']))
  if 'events' not in data and 'items' not in data:raise ValueError('calendar_shape')
  rows=data.get('events',data.get('items'))
 elif isinstance(data,list):rows=data
 else:raise ValueError('calendar_shape')
 if not isinstance(rows,list):raise ValueError('calendar_shape')
 out=[]
 for row in rows:
  if not isinstance(row,dict):continue
  title=plain(row.get('title') or row.get('event_name') or row.get('name') or row.get('event'))
  raw=row.get('scheduled_at') or row.get('event_time') or row.get('date') or row.get('event_date') or row.get('datetime')
  if not title or not raw:continue
  out.append({'title':title,'date':str(raw),'at':stamp(raw),'estimated':bool(row.get('estimated_schedule')) or row.get('status')=='estimated_schedule','source':plain(row.get('source')),'url':row.get('source_url') or row.get('url') or '', 'importance':row.get('importance'),'timeZone':row.get('timezone') or '', 'precision':'day' if re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(raw)) else 'source'})
 if rows and not out:raise ValueError('calendar_shape')
 return out
class Store:
 def __init__(self,path):
  self.path=Path(path);self.lock=threading.RLock();self.data={'events':[],'sources':{},'calendar':{'status':'pending','items':[]}}
  if self.path.exists():
   try:self.data.update(json.loads(self.path.read_text()))
   except (ValueError,OSError):pass
 def snapshot(self):
  with self.lock:return json.loads(json.dumps(self.data))
 def collect(self,projects,request,stamp,token):
  current=int(time.time()*1000)
  if not token:
   with self.lock:self.data['sources']={'OpenNews':{'status':'missing_credential'}};self.data['calendar']['status']='missing_credential'
   return
  # Three shared queries per round, not three per project; bounded pagination and visible coverage.
  tasks={'公告':{'listing':[]},'市场异动':{'market':['funding_rate','funding_diff','liquidation','oi_change','price_change','smart_money']},'机构动态':{'news':['6551OnChain']}}
  for label,engines in tasks.items():
   try:
    response=json.loads(request('https://ai.6551.io/open/news_search',{'engineTypes':engines,'coins':list(dict.fromkeys(p['symbol'] for p in projects)),'limit':100,'page':1}))
    if response.get('success') is False or not isinstance(response.get('data'),list):raise ValueError('invalid_response')
    incoming=[e for r in response['data'] for p in projects if (e:=normalize(r,p,stamp,current))]
    with self.lock:
     self.data['events']=merge(self.data['events'],incoming,current);self.data['sources'][label]={'status':'ok','lastSuccessAt':current,'count':len(incoming),'returned':len(response['data']),'limited':len(response['data'])>=100}
   except Exception:
    with self.lock:self.data['sources'][label]={**self.data['sources'].get(label,{}),'status':'error','lastAttemptAt':current}
  with self.lock:last=self.data['calendar'].get('lastAttemptAt',0)
  if current-last>=3600000:
   try:
    today=dt.datetime.now(dt.timezone.utc).date()
    response=json.loads(request('https://ai.6551.io/open/finance-enhance/key-market-events',{'start_date':str(today),'end_date':str(today+dt.timedelta(days=14)),'importance':'high','limit':50}))
    items=calendar_rows(response,stamp)
    with self.lock:self.data['calendar']={'status':'ok','items':items,'lastSuccessAt':current,'lastAttemptAt':current}
   except Exception:
    with self.lock:self.data['calendar']={**self.data['calendar'],'status':'error','lastAttemptAt':current}
  with self.lock:
   self.data['events']=merge(self.data['events'],[],current)
   self.path.parent.mkdir(parents=True,exist_ok=True);tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(self.data,ensure_ascii=False));tmp.replace(self.path)
