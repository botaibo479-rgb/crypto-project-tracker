"""Single-owner reader preferences, with field-level optimistic concurrency."""
import json, threading
from pathlib import Path

FIELDS={'hiddenProjects','pinnedProjects','projectGroups','projectOrder','unreadProjectsOnly','saved','read'}

def validate(values):
 if not isinstance(values,dict) or not values.keys()<=FIELDS:raise ValueError('偏好字段无效')
 for key,value in values.items():
  if key=='unreadProjectsOnly':
   if not isinstance(value,bool):raise ValueError('筛选值无效')
  elif key=='projectGroups':
   if not isinstance(value,dict) or len(value)>100 or any(not isinstance(k,str) or len(k)>100 or not isinstance(v,str) or len(v)>20 for k,v in value.items()):raise ValueError('分组无效')
  else:
   if not isinstance(value,list) or len(value)>(5000 if key in ('saved','read') else 100):raise ValueError('偏好列表过长')
   if key in ('saved','read'):
    if any(type(x)!=int or not 0<=x<=9007199254740991 for x in value):raise ValueError('资讯标识无效')
   elif any(not isinstance(x,str) or not 1<=len(x)<=100 for x in value):raise ValueError('项目标识无效')
 return values

class Store:
 def __init__(self,path):
  self.path=Path(path);self.lock=threading.RLock();self.data={}
  if self.path.exists():self.data=validate(json.loads(self.path.read_text()))
 def snapshot(self):
  with self.lock:return json.loads(json.dumps(self.data))
 def update(self,payload):
  values=validate(payload.get('values'));base=payload.get('base')
  if not isinstance(base,dict) or set(base)!=set(values):raise ValueError('缺少修改前的偏好')
  with self.lock:
   conflicts=[k for k,v in values.items() if self.data.get(k)!=base[k] and self.data.get(k)!=v]
   if conflicts:return {'values':self.snapshot(),'conflicts':conflicts},409
   updated={**self.data,**values}
   self.path.parent.mkdir(parents=True,exist_ok=True)
   tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(updated,ensure_ascii=False));tmp.replace(self.path)
   self.data=updated
   return {'values':self.snapshot()},200
