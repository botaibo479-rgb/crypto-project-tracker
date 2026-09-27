"""Observe the public Team section; never infer departure from a partial page."""
import re
import datetime as dt
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin,urlsplit,parse_qs,unquote

def identity(url):
 u=urlsplit(url)
 if u.hostname not in ('www.rootdata.com','rootdata.com','tw.rootdata.com') or not u.path.startswith('/member/'):return None
 return parse_qs(u.query).get('k',[u.path])[0]

def validate_source(project,url,request):
 u=urlsplit(url)
 if u.scheme!='https' or u.hostname not in ('www.rootdata.com','rootdata.com','tw.rootdata.com') or u.username or u.password or u.port not in (None,443) or not u.path.startswith('/projects/detail/'):
  raise ValueError('请填写 RootData 的 HTTPS 项目详情页')
 account=project.get('account','').lstrip('@').lower()
 if not account:raise ValueError('请先填写官方 X 账号，用于排除同名项目')
 parser=TeamLinks();parser.feed(request(url))
 matches=[]
 for link in parser.links:
  target=urlsplit(link['href'])
  if link['label'].strip() in ('X','Twitter') and target.scheme=='https' and target.hostname in ('x.com','www.x.com','twitter.com','www.twitter.com'):
   matches.append(target.path.strip('/').lower())
 if account not in matches:raise ValueError('RootData 页面未找到一致的官方 X 账号，请核对项目')
 return url

class TeamLinks(HTMLParser):
 def __init__(self):
  super().__init__();self.stack=[];self.current=None;self.links=[]
 def handle_starttag(self,tag,attrs):
  attrs=dict(attrs);hidden=(self.stack[-1][1] if self.stack else False) or 'hidden' in attrs or attrs.get('aria-hidden')=='true' or (attrs.get('role')=='tabpanel' and attrs.get('data-state')=='inactive')
  if tag not in ('br','img','input','hr','meta','link','source','wbr'):self.stack.append((tag,hidden))
  if tag=='a' and not hidden:self.current={'href':attrs.get('href',''),'label':''}
 def handle_data(self,text):
  if self.current:self.current['label']+=text
 def handle_endtag(self,tag):
  if tag=='a' and self.current:self.links.append(self.current);self.current=None
  for index in range(len(self.stack)-1,-1,-1):
   if self.stack[index][0]==tag:self.stack=self.stack[:index];break

def members(html,url):
 heads=list(re.finditer(r'<h2\b[^>]*>(.*?)</h2>',html,re.I|re.S))
 for i,head in enumerate(heads):
  title=re.sub('<[^>]+>','',head[1]).strip()
  if title not in ('Team','团队','團隊'):continue
  section=html[head.end():heads[i+1].start() if i+1<len(heads) else len(html)]
  parser=TeamLinks();parser.feed(section);result={}
  for link in parser.links:
   target=urljoin(url,link['href']);key=identity(target)
   if key:result[key]={'key':key,'name':unquote(urlsplit(target).path.split('/')[-1]),'url':target}
  if not result:raise ValueError('public_team_unavailable')
  return list(result.values())
 raise ValueError('team_section_missing')

def refresh(project,request,now):
 url=project.get('teamSourceUrl','');u=urlsplit(url)
 if u.scheme!='https' or u.hostname not in ('www.rootdata.com','tw.rootdata.com','rootdata.com') or not u.path.startswith('/projects/detail/'):
  raise ValueError('invalid_rootdata_source')
 previous=project.get('rootdataObservation',{})
 try:
  rows=members(request(url),url)
  known={identity(a.get('rootdataEvidence') or a.get('evidence','')) for a in project.get('team',[])}
  prior={a['key'] for a in previous.get('members',[])} or known
  current={a['key'] for a in rows}
  return {'status':'ok','checkedAt':now,'lastAttemptAt':now,'source':url,'members':rows,
          'candidates':[a for a in rows if a['key'] not in known],
          'newlyVisible':[a for a in rows if a['key'] not in prior],
          'notVisibleCount':len((prior-{None})-current),
          'note':'仅公开团队区；未出现不代表离职，新增人物需核对 X 账号。'}
 except Exception:
  return {**previous,'status':'error','lastAttemptAt':now,'source':url,'note':'公开团队区查询失败，保留已有名单与上次观察。'}

def member_account(person,html):
 heading=re.search(r'<h1\b[^>]*>(.*?)</h1>',html,re.I|re.S)
 normalize=lambda s:re.sub(r'[^\w]','',unescape(re.sub('<[^>]+>','',s))).casefold()
 if not heading or normalize(heading[1])!=normalize(person['name']):raise ValueError('人物页名称不匹配')
 parser=TeamLinks();parser.feed(html);handles={}
 for link in parser.links:
  if link['label'].strip() not in ('X','Twitter'):continue
  u=urlsplit(link['href']);handle=u.path.strip('/')
  if u.scheme=='https' and u.hostname in ('x.com','www.x.com','twitter.com','www.twitter.com') and re.fullmatch(r'[A-Za-z0-9_]{1,15}',handle) and handle.lower() not in ('home','intent','search','share','i'):
   handles[handle.lower()]=handle
 if len(handles)!=1:raise ValueError('没有唯一明确的公开 X 账号')
 return next(iter(handles.values()))

def resolve_candidates(project,observation,request,now):
 if observation.get('status')!='ok':return observation,[]
 result=dict(observation);pending=[];added=[];checks=[]
 known={a['account'].lower() for a in project.get('team',[]) if a.get('account')}
 for person in observation.get('candidates',[])[:20]:
  try:
   if not identity(person['url']) or urlsplit(person['url']).scheme!='https':raise ValueError('无效人物来源')
   account=member_account(person,request(person['url']))
   checks.append({'name':person['name'],'status':'matched','account':account})
   if account.lower() in known:continue
   known.add(account.lower())
   date=dt.datetime.fromtimestamp(now/1000,dt.timezone.utc).date().isoformat()
   added.append({'account':account,'name':person['name'],'role':'RootData 团队区收录 · '+person['name'],
                 'identity':'公开团队区及人物 X 链接关联 · 非实时任职核验','source':'RootData',
                 'evidence':person['url'],'projectEvidence':observation['source'],'checkedAt':date})
  except Exception as error:
   pending.append(person);checks.append({'name':person['name'],'status':'unresolved','message':str(error) if isinstance(error,ValueError) else '人物页查询失败'})
 result.update(candidates=pending+observation.get('candidates',[])[20:],accountChecks=checks,accountsCheckedAt=now)
 return result,added
