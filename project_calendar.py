"""Project schedules with explicit source identity, timestamps and optional DefiLlama API."""
import datetime as dt,hashlib,json,math,re,threading,time,urllib.parse,urllib.request,urllib.error
from pathlib import Path
from public_sources import public_url

def number(value):
 try:v=float(value)
 except (TypeError,ValueError):return None
 return v if math.isfinite(v) and v>=0 else None

def normalize_raises(data,project,stamp):
 if not isinstance(data,dict) or not isinstance(data.get('raises'),list):raise ValueError('融资数据格式无效')
 ident=project.get('calendarProtocolId');out=[]
 if not ident:return out # Never match ambiguous ticker/name.
 for r in data['raises']:
  if str(r.get('defillamaId',''))!=ident:continue
  at=number(r.get('date'))
  if not at or at*1000>stamp:continue # Disclosed history is never a future funding event.
  try:url=public_url(r.get('source',''))
  except ValueError:url='https://defillama.com/raises'
  out.append({'id':'raise-'+hashlib.sha256((ident+str(at)+str(r.get('round'))).encode()).hexdigest()[:20],'p':project['id'],'kind':'funding','title':str(r.get('name',''))+' · '+str(r.get('round','融资披露')),'at':int(at*1000),'investors':r.get('leadInvestors') or [],'source':'DefiLlama 融资披露','url':url,'checkedAt':stamp,'origin':'provider','precision':'day'})
 return sorted(out,key=lambda x:x['at'],reverse=True)[:30]

def manual(payload,pid):
 kind=payload.get('kind');title=str(payload.get('title','')).strip()
 if kind!='funding' or not 1<=len(title)<=120:raise ValueError('类型或标题无效')
 try:
  date=dt.datetime.fromisoformat(str(payload.get('date','')).replace('Z','+00:00'))
  if date.tzinfo is None:raise ValueError()
  at=int(date.timestamp()*1000)
 except (ValueError,OverflowError):raise ValueError('请输入带时区的日程时间')
 now=int(time.time()*1000)
 if not now-10*366*86400000<at<now+5*366*86400000:raise ValueError('日程时间超出范围')
 url=public_url(payload.get('url',''));tokens=number(payload.get('tokens'));supply=number(payload.get('supply'))
 if kind=='funding' and at>now:raise ValueError('融资只记录已披露历史，不预测未来融资')
 for k in ('tokens','supply'):
  if payload.get(k) not in (None,'') and number(payload[k]) is None:raise ValueError('数量须为非负有限数值')
 return {'id':'manual-'+hashlib.sha256((pid+kind+str(at)+url).encode()).hexdigest()[:20],'p':pid,'kind':kind,'title':title,'at':at,'tokens':tokens,'supply':supply,'floatPercent':tokens/supply*100 if tokens is not None and supply else None,'supplyAt':now,'source':'用户录入 · 请核对来源','url':url,'checkedAt':now,'origin':'manual','precision':'source'}

class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):raise ValueError('供应方重定向未接受')

class Store:
 def __init__(self,path):
  self.path=Path(path);self.lock=threading.RLock();self.data={'items':[],'status':'missing_credential','providers':{}}
  if self.path.exists():self.data.update(json.loads(self.path.read_text()))
 def save(self):
  self.path.parent.mkdir(exist_ok=True);tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(self.data,ensure_ascii=False));tmp.replace(self.path)
 def snapshot(self):
  with self.lock:return {**{k:v for k,v in json.loads(json.dumps(self.data)).items() if k not in ('unlockLeads','unlockSearch')},'items':[i for i in json.loads(json.dumps(self.data['items'])) if i.get('kind')=='funding']}
 def add(self,payload,pid):
  row=manual(payload,pid)
  with self.lock:
   if len([x for x in self.data['items'] if x.get('origin')=='manual'])>=200:raise ValueError('手动日程已达 200 条')
   self.data['items']=[x for x in self.data['items'] if x['id']!=row['id']]+[row];self.save()
  return row
 def remove(self,ident):
  with self.lock:
   if not any(x['id']==ident and x.get('origin')=='manual' for x in self.data['items']):raise ValueError('只可移除手动记录')
   self.data['items']=[x for x in self.data['items'] if x['id']!=ident];self.save()
 def collect(self,projects,key):
  now=int(time.time()*1000)
  if not key:
   with self.lock:self.data['status']='missing_credential';self.save()
   return
  # Key is kept only in the request URL required by this provider, never persisted/logged.
  for path,kind,normalize in [('raises','funding',normalize_raises)]:
   try:
    req=urllib.request.Request('https://pro-api.llama.fi/'+urllib.parse.quote(key,safe='')+'/api/'+path,headers={'User-Agent':'SignalReader/0.3'})
    with urllib.request.build_opener(NoRedirect).open(req,timeout=25) as r:
     raw=r.read(20_000_001)
     if len(raw)>20_000_000:raise ValueError('响应过大')
     data=json.loads(raw)
    rows=[x for p in projects for x in normalize(data,p,now)]
    with self.lock:
     self.data['items']=[x for x in self.data['items'] if x.get('origin')!='provider' or x['kind']!=kind]+rows
     self.data['providers'][kind]={'status':'ok','lastSuccessAt':now,'lastAttemptAt':now}
   except Exception:
    with self.lock:self.data['providers'][kind]={**self.data['providers'].get(kind,{}),'status':'error','lastAttemptAt':now}
  with self.lock:self.data['status']='ok' if all(v.get('status')=='ok' for v in self.data['providers'].values()) else 'error';self.save()
