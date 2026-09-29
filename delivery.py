"""Local daily digests and explicitly enabled ntfy delivery. No default outbound messages."""
import datetime as dt,hashlib,json,os,re,threading,time,urllib.request,urllib.parse
from pathlib import Path

def excerpt(text,limit=180):
 text=' '.join((text or '').split())
 if len(text)<=limit:return text
 sentence=re.match(r'^.{12,180}?[。！？.!?](?:\s|$)',text)
 return sentence[0].strip() if sentence else text[:limit]+'…'

def make_digest(rows,projects,current=None):
 current=current or dt.datetime.now().astimezone();day=current.date()-dt.timedelta(days=1)
 start=dt.datetime.combine(day,dt.time.min).astimezone();end=dt.datetime.combine(day+dt.timedelta(days=1),dt.time.min).astimezone()
 catalog={p['id']:p for p in projects};picked=[];counts={}
 eligible=[e for e in rows if not e.get('lowInformation') and e.get('qualityScore',0)>=30 and start.timestamp()*1000<=(e.get('publishedAt') or 0)<end.timestamp()*1000]
 for e in sorted(eligible,key=lambda e:(-e.get('qualityScore',0),-(e.get('publishedAt') or 0))):
  pids=[p for p in e.get('projectIds',[e['p']]) if p in catalog]
  if not pids or not any(counts.get(p,0)<3 for p in pids):continue
  for p in pids:counts[p]=counts.get(p,0)+1
  picked.append({'id':e['id'],'projectNames':[catalog[p]['name'] for p in pids],'title':excerpt(e.get('summary') or e['title']),'titleZh':excerpt(e.get('summaryZh') or e.get('titleZh')) or None,'detail':e.get('summary') or e['title'],'detailZh':e.get('summaryZh'),'url':e.get('url'),'publishedAt':e.get('publishedAt'),'qualityScore':e.get('qualityScore')})
 return {'date':str(day),'generatedAt':int(current.timestamp()*1000),'timeZone':str(current.tzinfo),'items':picked,'eligibleCount':len(eligible),'method':'原文要点摘录，非 AI 推断'}

def ntfy_config():
 url=os.environ.get('SIGNAL_NTFY_URL','').strip();enabled=os.environ.get('SIGNAL_PUSH_ENABLED')=='1'
 if not enabled:return None
 u=urllib.parse.urlsplit(url)
 # The integration deliberately supports the public ntfy service only. Never follow redirects.
 if u.scheme!='https' or u.hostname!='ntfy.sh' or u.port or u.username or u.password or u.query or u.fragment or not re.fullmatch(r'/[A-Za-z0-9_-]{8,128}',u.path):raise ValueError('invalid_ntfy_configuration')
 return {'url':url,'token':os.environ.get('SIGNAL_NTFY_TOKEN','')}
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None

def send_ntfy(config,title,message):
 headers={'Content-Type':'text/plain; charset=utf-8','Title':'Signal update','Tags':'newspaper'}
 if config.get('token'):headers['Authorization']='Bearer '+config['token']
 req=urllib.request.Request(config['url'],data=(title+'\n\n'+message).encode()[:4000].decode('utf-8','ignore').encode(),headers=headers,method='POST')
 with urllib.request.build_opener(NoRedirect).open(req,timeout=12) as response:
  if response.status!=200:raise ValueError('delivery_failed')
  response.read(2048)

class Store:
 def __init__(self,path):
  self.path=Path(path);self.lock=threading.RLock();self.data={'outbox':{},'digestHour':8,'digests':{}};self.started=int(time.time()*1000)
  if self.path.exists():
   try:self.data.update(json.loads(self.path.read_text()))
   except (ValueError,OSError):pass
 def save(self):
  self.path.parent.mkdir(parents=True,exist_ok=True);tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(self.data,ensure_ascii=False));tmp.replace(self.path)
 def status(self):
  try:enabled=bool(ntfy_config());status='已配置，等待新提醒' if enabled else '默认关闭'
  except ValueError:enabled=False;status='配置无效：需要 https://ntfy.sh/私有主题名，主题至少 8 字符'
  with self.lock:return {'enabled':enabled,'status':status,'digestHour':self.data['digestHour'],'lastDigestAt':self.data.get('lastDigestAt'),'deliveryResults':list(self.data['outbox'].values())[-10:]}
 def set_hour(self,hour):
  if type(hour)!=int or not 0<=hour<=23:raise ValueError('请选择 0–23 点')
  with self.lock:self.data['digestHour']=hour;self.save()
 def test(self):
  config=ntfy_config()
  if not config:raise ValueError('尚未启用 ntfy')
  send_ntfy(config,'Signal 测试通知','这是由你在本地阅读器点击发送的测试消息。')
 def tick(self,rows,projects,alerts,current=None,sender=send_ntfy):
  current=current or dt.datetime.now().astimezone();now=int(current.timestamp()*1000);jobs=[]
  with self.lock:
   day=str(current.date()-dt.timedelta(days=1))
   if current.hour>=self.data['digestHour'] and day not in self.data['digests']:
    digest=make_digest(rows,projects,current);self.data['digests'][day]=digest;self.data['lastDigestAt']=now
    self.data['digests']=dict(sorted(self.data['digests'].items())[-14:]);self.save()
   digest=self.data['digests'].get(day)
  try:config=ntfy_config()
  except ValueError:return
  if not config:
   with self.lock:
    if self.data.pop('destination',None) is not None:self.save()
   return
  fingerprint=hashlib.sha256((config['url']+config['token']).encode()).hexdigest()
  with self.lock:
   if self.data.get('destination')!=fingerprint:self.data.update(destination=fingerprint,enabledAt=now);self.save()
   since=self.data['enabledAt']
   for a in alerts:
    if since<a.get('at',0)<=now and now-a['at']<3600000:jobs.append(('alert:'+a['id'],a['ruleName'],a['title']+'\n'+str(a.get('evidence',{}).get('url') or '')))
   if digest and digest['generatedAt']>since:
    body='\n\n'.join(' / '.join(x['projectNames'])+'\n'+(x['titleZh'] or x['title'])[:220]+'\n'+(x['url'] or '') for x in digest['items'][:8]) or '昨日暂无已采集的有效资讯。'
    jobs.append(('digest:'+day,'Signal 昨日要点 · '+day,body))
  for key,title,body in jobs[:10]:
   with self.lock:
    if key in self.data['outbox']:continue
    self.data['outbox'][key]={'kind':key.split(':')[0],'at':now,'status':'sending'};self.save()
   try:sender(config,title,body);status='sent'
   except Exception:status='failed_or_unknown'
   # A timeout might already have delivered. Never blindly resend an ambiguous response.
   with self.lock:
    self.data['outbox'][key]['status']=status;self.data['outbox']=dict(list(self.data['outbox'].items())[-500:]);self.save()
