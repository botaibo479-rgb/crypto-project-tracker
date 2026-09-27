"""Live reader: loopback by default, authenticated HTTPS proxy in production."""
import concurrent.futures as cf
import datetime as dt
import email.utils
import hashlib
import json
import os
import re
import threading
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from news_quality import relevant, QUERIES, curate
import features
import team_news
import alerts
import charts
import preferences
import rootdata_monitor
import runtime_config as config
from collection_state import social_result,merge_news
from event_clusters import cluster

ROOT=Path(__file__).resolve().parent
ALERT_STORE=alerts.Store(config.DATA_DIR/'alerts.json')
PREFERENCES=preferences.Store(config.DATA_DIR/'preferences.json')
CHART_CACHE={}
CHART_LOCK=threading.Lock()
PROJECTS=[
 dict(id='soon',name='SOON',symbol='SOON',account='soon_svm',website='https://soon.foundation/',bg='#e2e9fa',color='#586bb6',mark='S'),
 dict(id='near',name='NEAR Protocol',symbol='NEAR',account='NEARProtocol',website='https://www.near.org/',bg='#e0efe8',color='#3a7257',mark='N'),
 dict(id='pha',name='Phala',symbol='PHA',account='PhalaNetwork',website='https://phala.com/',bg='#eef0df',color='#6d7942',mark='P'),
 dict(id='nil',name='Nillion',symbol='NIL',account='nillion',website='https://nillion.com/',bg='#e7e5fa',color='#7665ad',mark='N')]
PROJECTS[1]['team']=[{'account':'ilblackdragon','role':'联合创始人 · Illia Polosukhin','evidence':'https://docs.near.org/assets/files/Nightshade-201ea58f8dd6bc547f457d26ed5e8138.pdf','identity':'官方资料关联 · 非实时任职核验'}]
PROJECTS[2]['team']=[{'account':'marvin_tong','role':'创始人 · Marvin Tong','evidence':'https://phala.com/reports/2025RealCodeForRealdAGI.pdf','identity':'官方资料关联 · 非实时任职核验'}]
PROJECT_FILE=config.DATA_DIR/'projects.json'
if PROJECT_FILE.exists():
 try:
  for saved in json.loads(PROJECT_FILE.read_text()):
   existing=next((p for p in PROJECTS if p['id']==saved['id']),None)
   if existing:existing.update(saved)
   else:PROJECTS.append(saved)
 except Exception:pass
# Reviewed public RootData team snapshot; preserve existing official/user evidence.
ROOTDATA_TEAM=ROOT/'rootdata-team.json'
if ROOTDATA_TEAM.exists():
 for member in json.loads(ROOTDATA_TEAM.read_text()):
  project=next((p for p in PROJECTS if p['id']==member['project']),None)
  if not project:continue
  project['teamSourceUrl']=member['projectEvidence']
  team=project.setdefault('team',[])
  existing=next((a for a in team if a['account'].lower()==member['account'].lower()),None)
  if existing:
   existing['rootdataEvidence']=member['evidence'];existing['rootdataCheckedAt']=member['checkedAt']
  else:team.append(dict(member))
for project in PROJECTS:
 QUERIES.setdefault(project['id'],'"'+project['name']+'" OR "$'+project['symbol']+'"')
LOCK=threading.Lock()
DATA={'projects':PROJECTS,'markets':{},'events':[],'sources':{},'social':{},'updatedAt':None,'refreshing':True,'collectors':{}}
CACHE=config.DATA_DIR/'live-cache.json'
TOKEN=os.environ.get('OPENNEWS_TOKEN','')
# Only load a configuration path explicitly supplied to this application; never search other projects.
if os.environ.get('SIGNAL_ENV_FILE'):
 for line in Path(os.environ['SIGNAL_ENV_FILE']).read_text().splitlines():
  if line.startswith('OPENNEWS_TOKEN='): TOKEN=line.split('=',1)[1].strip().strip('"\'')

def now():return int(time.time()*1000)
def request(url,payload=None):
 headers={'User-Agent':'SignalReader/0.2','Accept':'application/json, application/xml, text/html'}
 if url.startswith('https://ai.6551.io/'):
  if not TOKEN:raise ValueError('missing_credential')
  headers['Authorization']='Bearer '+TOKEN
 raw=json.dumps(payload).encode() if payload is not None else None
 if raw:headers['Content-Type']='application/json'
 for attempt in range(2):
  try:
   with urllib.request.urlopen(urllib.request.Request(url,data=raw,headers=headers),timeout=18) as r:return r.read(6_000_000).decode('utf-8')
  except urllib.error.HTTPError as e:
   # Authorization failures are final; only retry temporary read-query failures.
   if attempt or e.code not in [502,503,504]:raise
   time.sleep(1)
  except (TimeoutError,urllib.error.URLError):
   if attempt:raise
   time.sleep(1)

def api(path,params):return json.loads(request('https://fapi.binance.com'+path+'?'+urllib.parse.urlencode(params)))
def error_label(e):
 if isinstance(e,urllib.error.HTTPError):return 'HTTP '+str(e.code)
 return {'TimeoutError':'连接超时','URLError':'网络连接失败','ValueError':'数据不可用'}.get(type(e).__name__,'数据读取失败')
def ema(values,period):
 if len(values)<period:return []
 out=[None]*(period-1);v=sum(values[:period])/period;out.append(v)
 for x in values[period:]:v=x*2/(period+1)+v*(1-2/(period+1));out.append(v)
 return out

def market(p):
 symbol=p['symbol']+'USDT';t=now();result={'symbol':symbol,'source':'Binance USDⓈ-M 永续','fetchedAt':t,'errors':{}}
 queries={'ticker':('/fapi/v1/ticker/24hr',{'symbol':symbol}), 'klines':('/fapi/v1/klines',{'symbol':symbol,'interval':'4h','limit':1500}), 'oi':('/futures/data/openInterestHist',{'symbol':symbol,'period':'5m','limit':13})}
 def fetch(item):
  k,(path,params)=item
  try:return k,api(path,params),None
  except Exception as e:return k,None,error_label(e)
 parts={}
 with cf.ThreadPoolExecutor(max_workers=3) as ex:
  for k,value,error in ex.map(fetch,queries.items()):
   if error:result['errors'][k]=error
   else:parts[k]=value
 if isinstance(parts.get('ticker'),dict) and 'lastPrice' in parts['ticker']:
  q=parts['ticker'];result.update(price=float(q['lastPrice']),change24h=float(q['priceChangePercent']),quoteVolume=float(q['quoteVolume']),priceAt=int(q['closeTime']))
 if isinstance(parts.get('klines'),list):
  ks=[x for x in parts['klines'] if int(x[6])<t];values=[float(x[4]) for x in ks];a=ema(values,200);b=ema(values,360)
  result['candles']=[{'time':int(x[0]),'open':float(x[1]),'high':float(x[2]),'low':float(x[3]),'close':float(x[4]),'volume':float(x[5])} for x in ks[-96:]]
  if a and b and len(values)>=361:
   crossUp=values[-2]<=max(a[-2],b[-2]) and values[-1]>max(a[-1],b[-1])
   crossDown=values[-2]>=min(a[-2],b[-2]) and values[-1]<min(a[-1],b[-1])
   result.update(ema200=a[-1],ema360=b[-1],close4h=values[-1],candleAt=int(ks[-1][6]),above200=values[-1]>a[-1],above360=values[-1]>b[-1],cross='up' if crossUp else 'down' if crossDown else None,klineCount=len(values),spark=values[-30:])
  else:result['errors']['ema']='已收盘 K 线不足 361 根'
 if isinstance(parts.get('oi'),list) and len(parts['oi'])>=2:
  rows=sorted(parts['oi'],key=lambda x:int(x['timestamp']));first,last=rows[0],rows[-1];span=int(last['timestamp'])-int(first['timestamp']);base=float(first['sumOpenInterest'])
  result.update(oi=float(last['sumOpenInterest']),oiAt=int(last['timestamp']),oiFrom=int(first['timestamp']),oiSpanMinutes=span/60000)
  if 55*60000<=span<=65*60000 and base>0:result['oiChange1h']=(float(last['sumOpenInterest'])/base-1)*100
  else:result['errors']['oiWindow']='未获得完整一小时 OI 窗口'
 return p['id'],result

class Anchors(HTMLParser):
 def __init__(self):super().__init__();self.links=[];self.href=None;self.text=[]
 def handle_starttag(self,tag,attrs):
  if tag=='a':self.href=dict(attrs).get('href');self.text=[]
 def handle_data(self,text):
  if self.href:self.text.append(text)
 def handle_endtag(self,tag):
  if tag=='a' and self.href:
   self.links.append((self.href,' '.join(' '.join(self.text).split())));self.href=None

def timestamp(s):
 try:
  if isinstance(s,(int,float)):return int(s if s>10**11 else s*1000)
  try:d=dt.datetime.fromisoformat(s.replace('Z','+00:00'))
  except ValueError:d=email.utils.parsedate_to_datetime(s)
  return int(d.replace(tzinfo=d.tzinfo or dt.timezone.utc).timestamp()*1000)
 except Exception:return None

def news_event(pid,title,url,published,source,body=''):
 return dict(id='news-'+hashlib.sha256((pid+url+source).encode()).hexdigest()[:20],p=pid,type='news',title=title,summary=body or '保留来源原文标题。点击查看原始内容，项目方表述不等于独立核实。',url=url,publishedAt=published,discoveredAt=now(),source=source,high=False,topic='项目资讯',evidence='来源声明',datePrecision='unknown' if not published else 'source')

def public_news(p):
 pid=p['id'];out=[]
 if pid=='soon':
  response=json.loads(request('https://api.official-admin.soo.network/social/medium/list'))
  result=response.get('data',{}).get('result')
  if not result:raise ValueError('official_article_feed_unavailable')
  rows=result.get('data',{})
  for row in (rows.get('last',[])+rows.get('pin',[]))[:8]:
   out.append(news_event(pid,row.get('title',''),row.get('articleLink',''),timestamp(row.get('publishedDate','')),'SOON 官网文章索引'))
  return out
 if pid=='near':
  parser=Anchors();parser.feed(request('https://www.near.org/blog/category/Infrastructure'))
  seen=set()
  for path,label in parser.links:
   if not path.startswith('/blog/') or '/category/' in path or path in seen or not label:continue
   seen.add(path)
   out.append(news_event(pid,label,'https://www.near.org'+path,None,'NEAR 官网 · Infrastructure 分类','官网分类页中的真实文章标题，发布时间未取得；此来源仅覆盖基础设施分类，不代表最新全量资讯。'))
  return out[:5]
 if pid=='nil':
  parser=Anchors();parser.feed(request('https://nillion.com/news/'))
  for path,label in parser.links:
   if not path.startswith('/news/') or path=='/news/':continue
   match=re.match(r'(\d{1,2} [A-Za-z]+ \d{4})\s+(.*)',label)
   if match:
    date=int(dt.datetime.strptime(match[1],'%d %B %Y').replace(tzinfo=dt.timezone.utc).timestamp()*1000)
    e=news_event(pid,match[2],'https://nillion.com'+path,date,'Nillion 官网');e['datePrecision']='day';out.append(e)
  return out[:8]
 if pid=='pha':
  xml=request('https://phala.com/atom.xml');root=ET.fromstring(xml)
  for item in root.findall('{http://www.w3.org/2005/Atom}entry')[:8]:
   ns={'a':'http://www.w3.org/2005/Atom'};link=item.find('a:link',ns)
   out.append(news_event(pid,item.findtext('a:title','',ns),link.get('href','') if link is not None else '',timestamp(item.findtext('a:published','',ns) or item.findtext('a:updated','',ns)),'Phala 官方 RSS'))
  return out
 return []

def provider_news(p):
 out=[];statuses={}
 if not TOKEN:return [],{'OpenNews':{'status':'missing_credential','message':'未配置 OPENNEWS_TOKEN'},'OpenTwitter':{'status':'missing_credential','message':'未连接；团队和 KOL 尚未采集'}}
 tasks={'OpenNews':('news_search',{'coins':[p['symbol']],'limit':30,'page':1}),'OpenNews关键词':('news_search',{'q':QUERIES[p['id']],'limit':30,'page':1}),'OpenTwitter':('twitter_user_tweets',{'username':p['account'],'maxResults':20,'includeReplies':True,'includeRetweets':False,'product':'Latest'})}
 for name,(path,payload) in tasks.items():
  try:
   response=json.loads(request('https://ai.6551.io/open/'+path,payload));rows=response.get('data',[])
   if response.get('success') is False:raise ValueError('provider_error')
   if isinstance(rows,dict):rows=rows.get('tweets',rows.get('list',[]))
   if not isinstance(rows,list):raise ValueError('unexpected_data')
   before_count=len(out)
   for row in rows:
    if name=='OpenTwitter':
     author=row.get('userScreenName',p['account']);tid=str(row.get('id',''))
     if not tid.isdigit() or author.lower()!=p['account'].lower():continue
     e=news_event(p['id'],row.get('text','')[:140],'https://x.com/'+author+'/status/'+tid,timestamp(row.get('createdAt','')),'X · @'+author,row.get('text',''))
    else:
     url=row.get('link','');text=row.get('text','');coins=[x.get('symbol','').upper() for x in (row.get('coins') or [])]
     # The provider's coin mapping is necessary, but ambiguous English words alone are insufficient.
     if not url.startswith('https://') or not relevant(p['id'],text,p):continue
     e=news_event(p['id'],text[:140],url,timestamp(row.get('ts')),str(row.get('newsType','OpenNews')),text)
    e['channel']='x' if name=='OpenTwitter' else 'opennews'
    if name!='OpenTwitter':
     rating=row.get('aiRating') or {}
     e['providerRating']={'score':rating.get('score'),'summary':rating.get('summary'),'status':rating.get('status')}
     e['matchReason']='官方名称 / 标识匹配；'+('币种检索' if name=='OpenNews' else '关键词补充检索')
    out.append(e)
   statuses[name]={'status':'ok','count':len(out)-before_count,'returnedCount':len(rows),'lastSuccessAt':now(),'message':'分页首批检索，非完整历史；结果经项目标识过滤'}
  except Exception as e:statuses[name]={'status':'error','message':error_label(e)}
 return out,statuses

def refresh_news(p):
 events,statuses=provider_news(p)
 if TOKEN:
  team_events,team_status=team_news.collect(p,request,timestamp,news_event)
  events.extend(team_events);statuses['团队 X']=team_status
 else:statuses['团队 X']={'status':'missing_credential','message':'未连接团队推文采集'}
 try:
  try:public=public_news(p)
  except (TimeoutError,urllib.error.URLError):public=public_news(p)
  events.extend(public)
  statuses['官网资讯']={'status':'ok' if public else 'limited','count':len(public),'lastSuccessAt':now() if public else None,'message':('仅 Infrastructure 分类，发布时间未取得' if p['id']=='near' else '官网索引 / RSS，非全网覆盖') if public else '此官网需要动态加载；暂未接入自动文章采集'}
 except Exception as e:statuses['官网资讯']={'status':'error','message':error_label(e)}
 return p['id'],events,statuses

def persist():
 CACHE.parent.mkdir(exist_ok=True);temp=CACHE.with_suffix('.tmp');temp.write_text(json.dumps(DATA,ensure_ascii=False));temp.replace(CACHE)

def collector_status(name,**fields):
 with LOCK:DATA['collectors'].setdefault(name,{}).update(fields)

def store_news(pid,items,status):
 with LOCK:
  merged,sources=merge_news([e for e in DATA['events'] if e['p']==pid],items,status,DATA['sources'].get(pid,{}),now())
  DATA['events']=[e for e in DATA['events'] if e['p']!=pid]+merged;DATA['sources'][pid]=sources

def loop():
 while True:
  started=time.time();collector_status('market',running=True,lastStartedAt=now(),intervalSeconds=60)
  try:
   with LOCK:projects=list(PROJECTS);DATA['refreshing']=True
   with cf.ThreadPoolExecutor(max_workers=4) as pool:
    futures={pool.submit(market,p):p for p in projects}
    for future in cf.as_completed(futures):
     try:
      pid,m=future.result()
      with LOCK:DATA['markets'][pid]=m
     except Exception as e:collector_status('market',lastError=error_label(e),lastErrorAt=now())
   with LOCK:DATA['updatedAt']=now();DATA['refreshing']=False;persist()
   collector_status('market',lastCompletedAt=now())
  except Exception as e:collector_status('market',lastError=error_label(e),lastErrorAt=now())
  delay=max(1,60-(time.time()-started));collector_status('market',running=False,nextRunAt=now()+int(delay*1000))
  time.sleep(delay)

def news_loop():
 while True:
  with LOCK:last=DATA['collectors'].get('news',{}).get('lastCompletedAt',0)
  remaining=1800-(now()-last)/1000
  if remaining>0:collector_status('news',running=False,nextRunAt=last+1800000);time.sleep(min(60,remaining));continue
  collector_status('news',running=True,lastStartedAt=now(),intervalSeconds=1800)
  try:
   with LOCK:projects=list(PROJECTS)
   with cf.ThreadPoolExecutor(max_workers=3) as pool:
    futures={pool.submit(refresh_news,p):p for p in projects}
    for future in cf.as_completed(futures):
     try:store_news(*future.result())
     except Exception as e:collector_status('news',lastError=error_label(e),lastErrorAt=now())
   collector_status('news',lastCompletedAt=now(),running=False,nextRunAt=now()+1800000)
   with LOCK:persist()
  except Exception as e:
   collector_status('news',lastError=error_label(e),lastErrorAt=now(),running=False);time.sleep(60)

def save_projects():
 PROJECT_FILE.parent.mkdir(exist_ok=True);tmp=PROJECT_FILE.with_suffix('.tmp');tmp.write_text(json.dumps(PROJECTS,ensure_ascii=False));tmp.replace(PROJECT_FILE)

def collect_new(project):
 if project.get('account'):
  a={'account':project['account']};features.enrich_avatars([a],request)
  if a.get('avatar'):
   with LOCK:project['logo']=a['avatar'];project['logoSource']='https://x.com/'+project['account']
 pid,m=market(project)
 with LOCK:DATA['markets'][pid]=m
 pid,items,status=refresh_news(project)
 store_news(pid,items,status)
 with LOCK:persist()

def alert_snapshot():
 result=ALERT_STORE.snapshot()
 for a in result['alerts']:
  if a.get('type')=='news':a['titleZh']=features.translated(a.get('title',''))
 return result

def alert_loop():
 while True:
  try:
   with LOCK:
    markets=dict(DATA['markets']);news=cluster(curate(list(DATA['events']),projects=PROJECTS))
   ALERT_STORE.tick(markets,news,now())
  except Exception as e:
   print('Alert evaluation failed: '+type(e).__name__,flush=True)
  time.sleep(20)

def logo_loop():
 while True:
  with LOCK:projects=list(PROJECTS)
  for p in projects:
   if not p.get('account'):continue
   a={'account':p['account']}
   features.enrich_avatars([a]+p.get('team',[]),request)
   if a.get('profile'):
    with LOCK:p['accountProfile']=a['profile']
   if a.get('avatar'):
    with LOCK:p['logo']=a['avatar'];p['logoSource']='https://x.com/'+p['account']
  time.sleep(21600)

def collect_rootdata(project):
 try:
  result=rootdata_monitor.refresh(project,request,now())
  result,additions=rootdata_monitor.resolve_candidates(project,result,request,now())
 except Exception:
  result={**project.get('rootdataObservation',{}),'status':'error','lastAttemptAt':now()};additions=[]
 with LOCK:
  target=next((p for p in PROJECTS if p['id']==project['id']),None)
  if target is not None and target.get('teamSourceUrl')==project.get('teamSourceUrl'):
   target['rootdataObservation']=result
   known={a['account'].lower() for a in target.get('team',[]) if a.get('account')}
   target.setdefault('team',[]).extend(a for a in additions if a['account'].lower() not in known)
   save_projects()

def rootdata_loop():
 while True:
  with LOCK:projects=[dict(p) for p in PROJECTS if p.get('teamSourceUrl')]
  for project in projects:
   last=project.get('rootdataObservation',{}).get('lastAttemptAt',0)
   if now()-last<86400000:continue
   collect_rootdata(project)
  time.sleep(3600)

def collect_social_project(project):
 try:result=features.discover(project,request,timestamp)
 except Exception as e:result={'status':'error','message':error_label(e),'discussants':[]}
 with LOCK:DATA['social'][project['id']]=social_result(DATA['social'].get(project['id'],{}),result,now())

def social_loop():
 while True:
  with LOCK:last=DATA['collectors'].get('social',{}).get('lastCompletedAt',0)
  remaining=1800-(now()-last)/1000
  if remaining>0:collector_status('social',running=False,nextRunAt=last+1800000);time.sleep(min(60,remaining));continue
  collector_status('social',running=True,lastStartedAt=now(),intervalSeconds=1800)
  try:
   with LOCK:projects=list(PROJECTS)
   for p in projects:collect_social_project(p)
   collector_status('social',running=False,lastCompletedAt=now(),nextRunAt=now()+1800000)
   with LOCK:persist()
  except Exception as e:collector_status('social',running=False,lastError=error_label(e),lastErrorAt=now());time.sleep(60)

def chart_data(pid,period):
 project=next((p for p in PROJECTS if p['id']==pid),None)
 if not project or period not in charts.PERIODS:raise ValueError('项目或周期无效')
 key=(pid,period)
 with CHART_LOCK:
  cached=CHART_CACHE.get(key)
  if cached and now()-cached['fetchedAt']<60000:return cached
  rows=api('/fapi/v1/klines',{'symbol':project['symbol']+'USDT','interval':period,'limit':1500})
  if not isinstance(rows,list):raise ValueError('K 线数据不可用')
  result=charts.snapshot(rows,period,now(),ema);CHART_CACHE[key]=result;return result

class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT/'dist'),**kwargs)
 def do_GET(self):
  if not config.allowed_read(self.headers.get('Host','')):
   self.send_error(403);return
  if self.path=='/api/preferences':
   self.json_response({'values':PREFERENCES.snapshot()});return
  if self.path=='/healthz':
   self.json_response({'status':'ok'});return
  if self.path.startswith('/api/chart?'):
   query=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
   try:self.json_response(chart_data(query.get('project',[''])[0],query.get('period',['4h'])[0]))
   except ValueError as e:self.json_response({'error':str(e)},400)
   except Exception:self.json_response({'error':'图表来源暂不可用，或无对应永续交易对'},502)
   return
  if self.path.startswith('/api/projects/search?'):
   try:self.json_response(features.search_projects(urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get('q',[''])[0],request))
   except Exception:self.json_response({'error':'搜索服务暂不可用，可以手动填写项目信息'},502)
   return
  if self.path=='/api/live':
   with LOCK:body=json.dumps({**DATA,'events':[features.localize(e) for e in cluster(curate(DATA['events'],projects=PROJECTS))],'social':{pid:{**v,'discussants':[{**a,'textZh':features.translated(a.get('text',''))} for a in v.get('discussants',[]) if features.eligible_discussant(a) and a.get('publishedAt') and now()-7*86400000<=a['publishedAt']<=now()+300000]} for pid,v in DATA.get('social',{}).items()},'alertState':alert_snapshot(),'serverTime':now(),'translation':features.translation_status(),'cadence':{'marketSeconds':60,'newsSeconds':1800}},ensure_ascii=False).encode()
   self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
  if self.path.split('?')[0] not in ['/','/index.html','/style.css','/live.js','/project.js','/rules.js','/watchlist.js','/charts.js','/notifications.js','/preferences.js','/reorder.js','/source-status.js']:
   self.send_error(404);return
  super().do_GET()
 def json_response(self,value,status=200):
  body=json.dumps(value,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def do_POST(self):
  host=self.headers.get('Host','')
  if not config.allowed_write(host,self.headers.get('Origin',''),self.headers.get('Content-Type','')):
   self.json_response({'error':'请求来源无效'},403);return
  try:
   length=int(self.headers.get('Content-Length','0'))
   if not 0<length<=(250000 if self.path=='/api/preferences' else 10000):raise ValueError('请求大小无效')
   payload=json.loads(self.rfile.read(length))
   if self.path=='/api/preferences':
    result,status=PREFERENCES.update(payload);self.json_response(result,status);return
   if self.path=='/api/rules':
    self.json_response({'rule':ALERT_STORE.upsert(payload,[p['id'] for p in PROJECTS])});return
   if self.path=='/api/rules/action':
    ALERT_STORE.action(payload.get('id'),payload.get('action'));self.json_response({'ok':True});return
   if self.path=='/api/projects/prepare':self.json_response(features.prepare_project(payload,request));return
   if self.path=='/api/projects':
    project=features.confirm_project(payload)
    if payload.get('rootdataUrl'):project['teamSourceUrl']=rootdata_monitor.validate_source(project,str(payload['rootdataUrl']).strip(),request)
    with LOCK:
     if any(p['symbol']==project['symbol'] or p['id']==project['id'] for p in PROJECTS):raise ValueError('该代币已经存在')
     if len(PROJECTS)>=20:raise ValueError('本地测试版最多支持 20 个项目')
     PROJECTS.append(project);QUERIES[project['id']]='"'+project['name']+'" OR "$'+project['symbol']+'"';save_projects()
    if project.get('teamSourceUrl'):threading.Thread(target=collect_rootdata,args=(dict(project),),daemon=True).start()
    threading.Thread(target=collect_new,args=(project,),daemon=True).start()
    threading.Thread(target=lambda: self.collect_social(project),daemon=True).start()
    self.json_response({'project':project});return
   if self.path=='/api/projects/rootdata':
    with LOCK:project=next((dict(p) for p in PROJECTS if p['id']==payload.get('projectId')),None)
    if not project:raise ValueError('项目不存在')
    source=rootdata_monitor.validate_source(project,str(payload.get('url','')).strip(),request)
    with LOCK:
     target=next(p for p in PROJECTS if p['id']==project['id'])
     if target.get('teamSourceUrl')!=source:target.pop('rootdataObservation',None)
     target['teamSourceUrl']=source;save_projects();project=dict(target)
    threading.Thread(target=collect_rootdata,args=(project,),daemon=True).start()
    self.json_response({'ok':True});return
   if self.path=='/api/projects/team':
    handle=str(payload.get('account','')).removeprefix('@');evidence=features.clean_url(str(payload.get('evidence','')))
    if not re.fullmatch('[A-Za-z0-9_]{1,15}',handle):raise ValueError('账号格式无效')
    role=str(payload.get('role','团队成员'))[:80]
    with LOCK:
     project=next((p for p in PROJECTS if p['id']==payload.get('projectId')),None)
     if not project:raise ValueError('项目不存在')
     team=project.setdefault('team',[])
     if any(a['account'].lower()==handle.lower() for a in team):raise ValueError('账号已添加')
     team.append({'account':handle,'role':role,'evidence':evidence,'identity':'用户添加 · 待核实'});save_projects()
    self.json_response({'ok':True});return
   self.json_response({'error':'接口不存在'},404)
  except ValueError as e:self.json_response({'error':str(e)[:140]},400)
  except Exception:self.json_response({'error':'上游服务暂不可用，请稍后再试'},502)
 def collect_social(self,project):collect_social_project(project)
 def log_message(self,*args):pass

if __name__=='__main__':
 if CACHE.exists():
  try:
   old=json.loads(CACHE.read_text());DATA.update({k:old[k] for k in ['markets','events','sources','social','updatedAt','collectors'] if k in old});DATA['refreshing']=True
  except Exception:pass
 httpd=ThreadingHTTPServer((config.BIND,config.PORT),Handler)
 threading.Thread(target=loop,daemon=True).start()
 threading.Thread(target=news_loop,daemon=True).start()
 threading.Thread(target=social_loop,daemon=True).start()
 threading.Thread(target=logo_loop,daemon=True).start()
 threading.Thread(target=rootdata_loop,daemon=True).start()
 threading.Thread(target=alert_loop,daemon=True).start()
 threading.Thread(target=features.translation_loop,args=(DATA,LOCK,request),daemon=True).start()
 print('Signal live reader ready',flush=True)
 try:httpd.serve_forever()
 except KeyboardInterrupt:pass
 finally:httpd.server_close()
