"""Bounded, credential-free RSS/Atom discovery and collection. Python stdlib only."""
import datetime as dt,email.utils,hashlib,html,http.client,ipaddress,json,re,socket,ssl,threading,time,urllib.parse,urllib.request,xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

def public_url(url):
 u=urllib.parse.urlsplit(str(url))
 if u.scheme!='https' or not u.hostname or u.username or u.password or u.port not in (None,443):raise ValueError('仅支持公开 HTTPS 地址，不接受账号密码或非标准端口')
 if u.hostname.lower() in {'localhost','metadata.google.internal'} or u.hostname.lower().endswith(('.local','.localhost')):raise ValueError('不能访问本地网络')
 try:
  if not ipaddress.ip_address(u.hostname).is_global:raise ValueError('不能访问本地网络')
 except ValueError:
  if re.fullmatch(r'[0-9.:]+',u.hostname):raise ValueError('不能访问本地网络')
 return urllib.parse.urlunsplit(('https',u.netloc,u.path or '/',u.query,''))

class PublicHTTPS(http.client.HTTPSConnection):
 def connect(self):
  addresses=socket.getaddrinfo(self.host,443,type=socket.SOCK_STREAM)
  # Some desktop proxies return RFC 2544 synthetic addresses. Resolve that specific
  # range through a fixed HTTPS DNS service, then still connect only to a public IP.
  synthetic=ipaddress.ip_network('198.18.0.0/15')
  if addresses and all(ipaddress.ip_address(a[4][0]) in synthetic for a in addresses):
   q=urllib.parse.urlencode({'name':self.host,'type':'A','edns_client_subnet':'0.0.0.0/0'})
   with urllib.request.urlopen('https://dns.google/resolve?'+q,timeout=8) as r:answer=json.loads(r.read(65536))
   ips=[a['data'] for a in answer.get('Answer',[]) if a.get('type')==1]
   addresses=[(socket.AF_INET,socket.SOCK_STREAM,0,'',(ip,443)) for ip in ips]
  if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):raise ValueError('不能访问私有地址')
  self.sock=socket.create_connection((addresses[0][4][0],443),self.timeout)
  self.sock=self._context.wrap_socket(self.sock,server_hostname=self.host)

def fetch(url,headers=None):
 # Pin the validated destination address; validate every redirect. Never forward credentials.
 for _ in range(4):
  url=public_url(url);u=urllib.parse.urlsplit(url);c=PublicHTTPS(u.hostname,timeout=12)
  try:
   c.request('GET',urllib.parse.urlunsplit(('', '',u.path or '/',u.query,'')),headers={'User-Agent':'SignalReader/0.3','Accept':'application/rss+xml, application/atom+xml, text/html, application/json',**{k:v for k,v in (headers or {}).items() if k in ('If-None-Match','If-Modified-Since')}})
   r=c.getresponse()
   if r.status in (301,302,303,307,308):url=urllib.parse.urljoin(url,r.getheader('Location',''));continue
   if r.status==304:return '',{},url,304
   if r.status!=200:raise ValueError('来源 HTTP '+str(r.status))
   body=r.read(2_000_001)
   if len(body)>2_000_000:raise ValueError('来源内容过大')
   encoding=r.headers.get_content_charset() or 'utf-8'
   return body.decode(encoding,errors='replace'),{k:r.getheader(k) for k in ('ETag','Last-Modified') if r.getheader(k)},url,200
  finally:c.close()
 raise ValueError('来源重定向过多')

class Links(HTMLParser):
 def __init__(self):super().__init__();self.links=[];self.feeds=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs);href=a.get('href','')
  if tag=='a' and href:self.links.append(href)
  if tag=='link' and 'alternate' in a.get('rel','') and any(t in a.get('type','') for t in ('rss','atom')):self.feeds.append(href)

def route(url,rsshub=''):
 u=urllib.parse.urlsplit(public_url(url));host=u.hostname.lower();parts=u.path.strip('/').split('/')
 if host=='github.com' and len(parts)>=2 and all(re.fullmatch(r'[\w.-]+',x) for x in parts[:2]):return f'https://github.com/{parts[0]}/{parts[1]}/releases.atom'
 if host=='medium.com' and parts[0]:return 'https://medium.com/feed/'+parts[0]
 if host.endswith('.medium.com'):return 'https://'+host+'/feed'
 if host.endswith('.mirror.xyz') or host=='mirror.xyz':return url.rstrip('/')+'/feed/atom'
 if host in ('t.me','telegram.me'):
  name=parts[1] if parts[0]=='s' and len(parts)>1 else parts[0]
  if not rsshub:raise ValueError('Telegram 需要配置 SIGNAL_RSSHUB_URL，或填写已有 RSS 地址')
  if not re.fullmatch(r'[A-Za-z0-9_]{5,64}',name):raise ValueError('频道地址无效')
  return public_url(rsshub.rstrip('/')+'/telegram/channel/'+name)
 return url

def parse_feed(text,base):
 if re.search(r'<!DOCTYPE|<!ENTITY',text,re.I):raise ValueError('不接受含实体声明的 XML')
 root=ET.fromstring(text)
 if root.tag.split('}')[-1] not in ('rss','feed','RDF'):raise ValueError('不是 RSS / Atom')
 out=[]
 for item in [e for e in root.iter() if e.tag.split('}')[-1] in ('item','entry')][:100]:
  values={};link=''
  for child in item:
   tag=child.tag.split('}')[-1];value=''.join(child.itertext())
   if tag=='link' and child.attrib.get('rel','alternate')=='alternate':link=child.attrib.get('href') or value
   values.setdefault(tag,value)
  title=html.unescape(re.sub('<[^>]+>','',values.get('title',''))).strip()[:300]
  body=html.unescape(re.sub('<[^>]+>','',values.get('encoded') or values.get('content') or values.get('description') or values.get('summary') or title)).strip()[:6000]
  if not title or not link:continue
  try:link=public_url(urllib.parse.urljoin(base,link))
  except ValueError:continue
  raw=values.get('published') or values.get('pubDate') or values.get('date') or values.get('updated');stamp=None
  if raw:
   try:
    try:date=dt.datetime.fromisoformat(raw.replace('Z','+00:00'))
    except ValueError:date=email.utils.parsedate_to_datetime(raw)
    if date.tzinfo is not None:stamp=int(date.timestamp()*1000)
   except (ValueError,TypeError,OverflowError):pass
  out.append({'title':title,'body':body,'url':link,'at':stamp})
 return out

class Store:
 def __init__(self,path,rsshub=''):
  self.path=Path(path);self.lock=threading.RLock();self.rsshub=rsshub;self.data={'projects':{}}
  if self.path.exists():self.data.update(json.loads(self.path.read_text()))
  for project in self.data['projects'].values():project['discovering']=False
 def save(self):
  self.path.parent.mkdir(exist_ok=True);tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(self.data,ensure_ascii=False));tmp.replace(self.path)
 def snapshot(self,pid):
  with self.lock:return json.loads(json.dumps(self.data['projects'].get(pid,{'sources':[],'candidates':[],'economy':False})))
 def patch(self,pid,**values):
  with self.lock:self.data['projects'].setdefault(pid,{'sources':[],'candidates':[],'economy':False}).update(values);self.save()
 def discover(self,p):
  pid=p['id'];old=self.snapshot(pid)
  if old.get('discovering'):return
  self.patch(pid,discovering=True)
  try:
   text,_,base,_=fetch(p['website']);parser=Links();parser.feed(text);candidates=[]
   for href in parser.feeds:
    try:candidates.append({'url':public_url(urllib.parse.urljoin(base,href)),'kind':'原生 RSS / Atom','evidence':base})
    except ValueError:pass
   pages=[]
   for href in parser.links:
    try:url=public_url(urllib.parse.urljoin(base,href));host=urllib.parse.urlsplit(url).hostname
    except ValueError:continue
    if host in ('github.com','medium.com','t.me','telegram.me','mirror.xyz') or host.endswith(('.medium.com','.mirror.xyz')):
     try:feed=route(url,self.rsshub)
     except ValueError:continue
     if feed!=url:candidates.append({'url':feed,'kind':'官网链接推导 · 待核对','evidence':url})
    elif any(x in url.lower() for x in ('blog','forum','governance')) and host==urllib.parse.urlsplit(base).hostname:pages.append(url)
   for url in list(dict.fromkeys(pages))[:2]:
    try:
     text,_,b,_=fetch(url);other=Links();other.feed(text)
     for href in other.feeds:candidates.append({'url':public_url(urllib.parse.urljoin(b,href)),'kind':'博客 / 论坛 RSS','evidence':b})
    except Exception:pass
   unique={x['url']:x for x in candidates};self.patch(pid,candidates=list(unique.values())[:20],discoveryStatus='ok',discoveredAt=int(time.time()*1000))
  except Exception:self.patch(pid,discoveryStatus='error',discoveredAt=int(time.time()*1000))
  finally:self.patch(pid,discovering=False)
 def add(self,pid,url,label):
  url=route(url,self.rsshub);text,_,base,_=fetch(url);parse_feed(text,base)
  label=str(label).strip()[:80] or '项目订阅'
  with self.lock:
   d=self.data['projects'].setdefault(pid,{'sources':[],'candidates':[],'economy':False})
   if len(d['sources'])>=8:raise ValueError('每项目最多 8 个订阅源')
   if any(x['url']==url for x in d['sources']):raise ValueError('来源已存在')
   d['sources'].append({'id':hashlib.sha256(url.encode()).hexdigest()[:16],'url':url,'label':label,'enabled':True,'status':'pending'});self.save()
 def action(self,pid,payload):
  with self.lock:
   d=self.data['projects'].setdefault(pid,{'sources':[],'candidates':[],'economy':False})
   if payload.get('action')=='economy':d['economy']=bool(payload.get('enabled'))
   else:
    item=next((s for s in d['sources'] if s['id']==payload.get('id')),None)
    if not item:raise ValueError('来源不存在')
    item['enabled']=not item['enabled']
   self.save()
 def healthy(self,pid):return any(s['enabled'] and s.get('status')=='ok' and time.time()*1000-s.get('lastSuccessAt',0)<3600000 for s in self.snapshot(pid)['sources'])
 def collect(self,p,news_event):
  results=[]
  for source in self.snapshot(p['id'])['sources']:
   if not source['enabled']:continue
   now=int(time.time()*1000)
   if now<source.get('retryAt',0):continue
   try:
    text,headers,base,code=fetch(source['url'],source.get('conditional'))
    rows=source.get('rows',[]) if code==304 else parse_feed(text,base)
    update={'status':'ok','lastSuccessAt':now,'rows':rows,'failures':0,'conditional':{'If-None-Match':headers['ETag']} if headers.get('ETag') else source.get('conditional',{})}
    for r in rows:
     if r['at'] and not 0<=now-r['at']<=7*86400000:continue
     e=news_event(p['id'],r['title'],r['url'],r['at'],'RSS · '+source['label'],r['body']);e.update(channel='subscription',subscriptionId=source['id'],sourceUrl=source['url'],matchReason='用户确认的项目订阅；来源身份未独立核验');results.append(e)
   except Exception:
    failures=source.get('failures',0)+1;update={'status':'error','failures':failures,'retryAt':now+min(86400000,1800000*2**min(failures-1,5))}
   with self.lock:
    current=next((s for s in self.data['projects'][p['id']]['sources'] if s['id']==source['id']),None)
    if current:current.update(update,lastAttemptAt=now);self.save()
  return results
