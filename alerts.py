"""Persistent, read-only market/news alerts. No trading or external messaging."""
import json,time,math,threading,uuid,hashlib
from pathlib import Path

TYPES={'news','price','oi','ema','level','combo'}
def validate(payload,projects):
 p=str(payload.get('p',''));kind=payload.get('type');name=str(payload.get('name','')).strip()
 if p not in projects or kind not in TYPES or not 1<=len(name)<=60:raise ValueError('项目、类型或规则名称无效')
 period=payload.get('period');expected='24h' if kind=='price' else '1h' if kind=='oi' else '4h'
 if kind!='news' and period!=expected:raise ValueError('当前该规则支持的周期为 '+expected)
 threshold=float(payload.get('threshold',5))
 if not math.isfinite(threshold) or not 0<threshold<=10000000:raise ValueError('阈值须为有效正数')
 cooldown=int(payload.get('cooldownMinutes',60))
 if not 1<=cooldown<=1440:raise ValueError('冷却时间须为 1–1440 分钟')
 if payload.get('confirm','close')!='close':raise ValueError('当前采用收盘确认，不支持盘中突破预警')
 if payload.get('notify','site')!='site':raise ValueError('当前支持站内记录；外部通知尚未连接')
 return dict(p=p,type=kind,name=name,period=expected,threshold=threshold,cooldownMinutes=cooldown,confirm='close',notify='site',on=bool(payload.get('on',True)))

def evaluate(rule,runtime,market,news,now):
 """Return events and mutate only this rule's durable runtime."""
 if not rule['on']:runtime['status']='paused';return []
 fired=[];seen=runtime.setdefault('seen',[])
 def emit(key,title,evidence):
  if key in seen:return
  seen.append(key);runtime['seen']=seen[-1000:]
  if now-runtime.get('lastFiredAt',0)<rule['cooldownMinutes']*60000:return
  runtime['lastFiredAt']=now
  fired.append({'id':uuid.uuid4().hex,'ruleId':rule['id'],'ruleName':rule['name'],'p':rule['p'],'type':rule['type'],'title':title,'at':now,'evidence':evidence})
 kind=rule['type'];runtime['checkedAt']=now
 if kind=='news':
  runtime['status']='watching'
  for e in sorted(news,key=lambda x:x.get('publishedAt') or 0):
   if e['p']!=rule['p'] or not e.get('high'):continue
   date=e.get('publishedAt')
   if date and rule['createdAt']<date<=now and now-date<=86400000:
    key='news:'+e['id']
    emit(key,e.get('titleZh') or e['title'],{'url':e.get('url'),'publishedAt':date,'reason':e.get('priorityReason'),'note':'文本规则命中的重点候选，未经独立核实'})
   for update in e.get('progressCandidates',[]):
    date=update.get('publishedAt')
    if date and rule['createdAt']<date<=now and now-date<=86400000:
     emit('progress:'+e['p']+':'+update['key']+':'+str(e.get('id')),'项目事件出现后续进展候选',{'url':update.get('url'),'publishedAt':date,'reason':update['reason'],'note':'新增表述：'+', '.join(update['signals'])})
  return fired
 if not market:runtime['status']='missing_data';return []
 value=None;sample=None;condition=False;evidence={}
 if kind in ['price','oi']:
  field='change24h' if kind=='price' else 'oiChange1h';stamp='priceAt' if kind=='price' else 'oiAt'
  value=market.get(field);sample=market.get(stamp)
  if value is not None:condition=abs(value)>=rule['threshold'];evidence={field:value,'threshold':rule['threshold'],'sampleAt':sample}
 else:
  sample=market.get('candleAt');candles=market.get('candles',[])
  if len(candles)>=2 and market.get('close4h') is not None:
   previous=candles[-2]['close'];value=market['close4h'];level=rule['threshold'];evidence={'previousClose':previous,'close':value,'candleAt':sample}
   if kind=='level':condition=previous<=level<value;evidence['level']=level
   else:
    if market.get('ema200') is None or market.get('ema360') is None:value=None
    condition=market.get('cross')=='up';evidence.update(ema200=market.get('ema200'),ema360=market.get('ema360'))
    if kind=='combo':
     oi=market.get('oiChange1h');oi_at=market.get('oiAt')
     if oi is None or not oi_at or not 0<=now-oi_at<=10*60000:value=None
     condition=condition and oi is not None and oi>=rule['threshold'];evidence['oiChange1h']=oi
 max_age=10*60000 if kind in ['price','oi'] else 4*3600000+15*60000
 if value is None or sample is None or not 0<=now-sample<=max_age:runtime['status']='missing_data';return []
 runtime['status']='watching'
 if kind in ['price','oi']:
  if runtime.get('sampleAt')==sample:return []
  previous=runtime.get('condition');runtime.update(condition=condition,sampleAt=sample)
  # First snapshot establishes a baseline, never a fabricated crossing.
  if previous is not False or not condition:return []
 else:
  if sample<=rule['createdAt']:return []
  if not condition:return []
 labels={'price':'24h 价格变化达到阈值','oi':'1h OI 变化达到阈值','level':'4h 收盘上穿关键价位','ema':'4h 收盘上穿双均线','combo':'4h 双均线突破且 OI 增长达标'}
 emit(kind+':'+str(sample),labels[kind],evidence)
 return fired

class Store:
 def __init__(self,path):
  self.path=Path(path);self.lock=threading.RLock();self.data={'rules':[],'runtime':{},'alerts':[]}
  if self.path.exists():self.data.update(json.loads(self.path.read_text()))
 def save(self):
  self.path.parent.mkdir(exist_ok=True);tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(self.data,ensure_ascii=False));tmp.replace(self.path)
 def snapshot(self):
  with self.lock:return json.loads(json.dumps(self.data))
 def upsert(self,payload,projects):
  clean=validate(payload,projects);now=int(time.time()*1000)
  with self.lock:
   rid=payload.get('id');old=next((r for r in self.data['rules'] if r['id']==rid),None)
   if rid and not old:raise ValueError('规则不存在')
   if not old and len(self.data['rules'])>=40:raise ValueError('最多支持 40 条规则')
   clean.update(id=rid or uuid.uuid4().hex,createdAt=now)
   self.data['rules']=[r for r in self.data['rules'] if r['id']!=rid]+[clean];self.data['runtime'].pop(clean['id'],None);self.save();return clean
 def action(self,rid,action):
  with self.lock:
   r=next((r for r in self.data['rules'] if r['id']==rid),None)
   if not r:raise ValueError('规则不存在')
   if action=='delete':self.data['rules'].remove(r);self.data['runtime'].pop(rid,None)
   elif action=='toggle':r['on']=not r['on'];r['createdAt']=int(time.time()*1000);self.data['runtime'].pop(rid,None)
   else:raise ValueError('操作无效')
   self.save()
 def tick(self,markets,news,now):
  with self.lock:
   for r in self.data['rules']:
    events=evaluate(r,self.data['runtime'].setdefault(r['id'],{}),markets.get(r['p']),news,now)
    self.data['alerts'].extend(events)
   self.data['alerts']=self.data['alerts'][-500:];self.save()
