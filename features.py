import json,re,time,hashlib,threading,urllib.parse,datetime as dt
import account_profiles
import discussion_quality
import reading_text
from runtime_config import DATA_DIR
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parent
TLOCK=threading.Lock(); TRANSLATIONS={}; RETRY={}
TRANSLATION_PAUSE_UNTIL=0
TRANSLATION_ERRORS={}; TRANSLATION_ATTEMPTS={}
TPATH=DATA_DIR/'translations.json'
APATH=DATA_DIR/'avatars.json'
try:AVATARS=json.loads(APATH.read_text())
except Exception:AVATARS={}
if TPATH.exists():
 try:TRANSLATIONS=json.loads(TPATH.read_text())
 except Exception:pass

def digest(text):return hashlib.sha256((reading_text.translation_version(text)+text).encode()).hexdigest()
def needs_translation(text):
 return bool(re.search('[A-Za-z]{3,}',text)) and len(re.findall('[\u4e00-\u9fff]',text))<max(3,len(re.findall('[A-Za-z]',text))//3)
def translated(text):
 if not needs_translation(text):return reading_text.readable(text)
 with TLOCK:
  value=TRANSLATIONS.get(digest(text))
  if value:value=re.sub(r'[\u200b\u200c\u200d\ufeff]','',value)
  if value and 'ZXQ' not in value:return value
  # Reuse legacy text only when every currently protected identifier survives.
  # This does not assert translation accuracy; it prevents avoidable cache churn.
  if reading_text.translation_version(text)=='v3:':
   old=TRANSLATIONS.get(hashlib.sha256(('v2:'+text).encode()).hexdigest())
   if old:
    old=reading_text.readable(old)
    tokens=[m.group() for m in reading_text.PROTECTED.finditer(reading_text.readable(text))]
    if 'ZXQ' not in old and all(old.casefold().count(t.casefold())>=tokens.count(t) for t in set(tokens)):
     return old
  return None
def translate_one(text,request):
 global TRANSLATION_PAUSE_UNTIL
 if translated(text) is not None:return
 key=digest(text)
 with TLOCK:
  if TRANSLATION_PAUSE_UNTIL>time.time():return
  if (key in TRANSLATIONS and 'ZXQ' not in re.sub(r'[\u200b\u200c\u200d\ufeff]','',TRANSLATIONS[key])) or RETRY.get(key,0)>time.time():return
 try:
  # Public source text only. No API credentials are sent to the translator.
  parts=[]; protected=[]
  def protect(match):
   protected.append(match.group());return 'ZXQKEEP'+str(len(protected)-1)+'QXZ'
  source=reading_text.PROTECTED.sub(protect,reading_text.readable(text))
  source=reading_text.standard_terms(source)
  for chunk in reading_text.chunks(source):
   query=urllib.parse.urlencode({'client':'gtx','sl':'auto','tl':'zh-CN','dt':'t','q':chunk})
   result=json.loads(request('https://translate.googleapis.com/translate_a/single?'+query))
   parts.append(''.join(item[0] for item in result[0] if item and item[0]))
  value=re.sub(r'[\u200b\u200c\u200d\ufeff]','',''.join(parts))
  for i,original in enumerate(protected):value=re.sub(r'ZXQ\s*(?:KEEP|保留)\s*'+str(i)+r'\s*QXZ',lambda _:original,value,flags=re.I)
  if 'ZXQ' in value:raise ValueError('unresolved_placeholder')
  if not value:raise ValueError('empty_translation')
  with TLOCK:
   TRANSLATIONS[key]=value;RETRY.pop(key,None);TRANSLATION_ERRORS.pop(key,None);TRANSLATION_ATTEMPTS.pop(key,None)
 except Exception as error:
  with TLOCK:
   TRANSLATION_ATTEMPTS[key]=TRANSLATION_ATTEMPTS.get(key,0)+1
   RETRY[key]=time.time()+min(3600,300*2**min(TRANSLATION_ATTEMPTS[key]-1,4))
   TRANSLATION_ERRORS[key]='rate_limited' if getattr(error,'code',None)==429 else 'failed'
   if getattr(error,'code',None)==429:
    try:delay=max(300,min(3600,int(error.headers.get('Retry-After','900'))))
    except (ValueError,TypeError,AttributeError):delay=900
    TRANSLATION_PAUSE_UNTIL=time.time()+delay

def translation_status():
 with TLOCK:
  paused=TRANSLATION_PAUSE_UNTIL>time.time()
  return {'status':'rate_limited' if paused else 'available','retryAt':int(TRANSLATION_PAUSE_UNTIL*1000) if paused else None}

def text_translation_status(text):
 if translated(text) is not None:return {'status':'ready','retryAt':None}
 key=digest(text)
 with TLOCK:
  retry=max(RETRY.get(key,0),TRANSLATION_PAUSE_UNTIL)
  status='rate_limited' if TRANSLATION_PAUSE_UNTIL>time.time() else TRANSLATION_ERRORS.get(key,'pending')
  return {'status':status,'retryAt':int(retry*1000) if retry>time.time() else None,'attempts':TRANSLATION_ATTEMPTS.get(key,0)}

def translation_loop(data,lock,request):
 while True:
  with lock:
   events=sorted(data['events']+data.get('intelligenceEvents',[]),key=lambda e:e.get('publishedAt') or 0,reverse=True)
   texts=[e.get(field,'') for e in events for field in ['title','summary']]+data.get('calendarTexts',[])
   for social in data.get('social',{}).values():
    texts.extend(a.get('text','') for a in social.get('discussants',[]))
  with TLOCK:retry=dict(RETRY)
  pending=list(dict.fromkeys(t for t in texts if t and needs_translation(t) and translated(t) is None and retry.get(digest(t),0)<=time.time()))[:40]
  with ThreadPoolExecutor(max_workers=4) as ex:list(ex.map(lambda t:translate_one(t,request),pending))
  with TLOCK:
   TPATH.parent.mkdir(exist_ok=True);tmp=TPATH.with_suffix('.tmp');tmp.write_text(json.dumps(TRANSLATIONS,ensure_ascii=False));tmp.replace(TPATH)
  time.sleep(5 if pending else 20)

def localize(e):
 e=dict(e)
 if e.get('relatedItems'):e['relatedItems']=[localize(item) for item in e['relatedItems']]
 e['translationDetails']={field:text_translation_status(e.get(field,'')) for field in ['title','summary']}
 e['titleZh']=translated(e.get('title',''));e['summaryZh']=translated(e.get('summary',''));e['translationStatus']='ready' if e['titleZh'] is not None and e['summaryZh'] is not None else 'pending';return e

def search_projects(query,request):
 if not 2<=len(query)<=80:raise ValueError('请输入至少两个字符')
 if query.startswith('@'):return {'candidates':[],'manual':True}
 d=json.loads(request('https://api.coingecko.com/api/v3/search?'+urllib.parse.urlencode({'query':query})))
 return {'candidates':[{'coinId':p['id'],'name':p['name'],'symbol':p['symbol'],'rank':p.get('market_cap_rank')} for p in d.get('coins',[])[:8]]}

def clean_url(value):
 u=urllib.parse.urlsplit(value.strip())
 if u.scheme!='https' or not u.hostname or u.username or u.password or u.hostname in ['localhost','127.0.0.1','::1']:raise ValueError('官网和证据链接须为有效 HTTPS 地址')
 return value.strip()
def prepare_project(payload,request):
 coin=payload.get('coinId','')
 if coin:
  if not re.fullmatch('[a-z0-9-]{1,100}',coin):raise ValueError('项目标识无效')
  d=json.loads(request('https://api.coingecko.com/api/v3/coins/'+coin+'?localization=false&tickers=false&market_data=false&community_data=false&developer_data=false'))
  links=d.get('links') or {};home=next((x for x in links.get('homepage',[]) if x.startswith('https://')),'');account=links.get('twitter_screen_name') or ''
  name=d['name'];symbol=d['symbol'].upper();identity='CoinGecko 项目资料，官网及账号待人工复核'
 else:
  name=str(payload.get('name','')).strip();symbol=str(payload.get('symbol','')).upper().strip();home=str(payload.get('website','')).strip();account=str(payload.get('account','')).strip().removeprefix('@');identity='用户填写，尚未核实身份'
 if '<' in name or '>' in name:raise ValueError('项目名称不能包含 HTML 标记')
 if not 1<=len(name)<=100 or not re.fullmatch('[A-Z0-9]{1,20}',symbol):raise ValueError('请输入项目名称与有效代币符号')
 if account and not re.fullmatch('[A-Za-z0-9_]{1,15}',account):raise ValueError('X 账号格式无效')
 if home:clean_url(home)
 return dict(coinId=coin,id=coin or ('custom-'+symbol.lower()),name=name,symbol=symbol,website=home,account=account,identity=identity,bg='#e5edf5',color='#486a8e',mark=symbol[0],custom=True)

def confirm_project(payload):
 # Save the fields the user reviewed, without fetching over their edits.
 coin=str(payload.get('coinId','')).strip()
 if coin and not re.fullmatch('[a-z0-9-]{1,100}',coin):raise ValueError('项目标识无效')
 project=prepare_project({k:v for k,v in payload.items() if k!='coinId'},None)
 if coin:
  project.update(id=coin,coinId=coin,identity='参考 CoinGecko 项目资料，由用户确认；身份尚未独立核实',identitySource='https://www.coingecko.com/en/coins/'+coin)
 return project

def enrich_avatars(accounts,request):
 def apply(a,cached):
  if 'followers' in cached:a['followers']=cached['followers']
  if cached.get('url'):a['avatar']=cached['url']
  if cached.get('profile'):a['profile']=cached['profile']
 def enrich(a):
  handle=a['account'];cached=AVATARS.get(handle,{})
  if cached.get('expires',0)>time.time() and cached.get('profile'):
   apply(a,cached);return
  stamp=int(time.time()*1000)
  try:
   response=json.loads(request('https://ai.6551.io/open/twitter_user_info',{'username':handle}))
   if response.get('success') is False:raise ValueError('profile_query_failed')
   returned=(response.get('data') or {}).get('screenName')
   if returned and returned.lower()!=handle.lower():raise ValueError('profile_identity_mismatch')
   profile=account_profiles.observed(cached.get('profile',{}),response.get('data'),stamp)
   cached={'url':profile['avatar'],'followers':profile['followers'],'profile':profile,'expires':time.time()+86400}
  except Exception:
   cached={**cached,'profile':account_profiles.failed(cached.get('profile',{}),stamp),'expires':time.time()+300}
  with TLOCK:AVATARS[handle]=cached
  apply(a,cached)
 with ThreadPoolExecutor(max_workers=4) as ex:list(ex.map(enrich,accounts))
 with TLOCK:
  APATH.parent.mkdir(exist_ok=True);tmp=APATH.with_suffix('.tmp');tmp.write_text(json.dumps(AVATARS));tmp.replace(APATH)

def eligible_discussant(a):
 try:return int(a.get('followers') or 0)>=20000
 except (ValueError,TypeError):return False

def discover(p,request,stamp):
 if not p.get('account'):return {'status':'unavailable','message':'尚未配置官方 X 账号','discussants':[],'team':[]}
 since=dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=7)
 r=json.loads(request('https://ai.6551.io/open/twitter_search',{'mentionUser':p['account'],'maxResults':40,'product':'Latest','excludeRetweets':True,'sinceDate':since.strftime('%Y-%m-%d')}))
 rows=r.get('data',[])
 if isinstance(rows,dict):rows=rows.get('tweets',rows.get('list',[]))
 if not isinstance(rows,list) or r.get('success') is False:raise ValueError('discussion_search_failed')
 authors={};observations={};seen=set()
 for row in rows:
  if not isinstance(row,dict) or discussion_quality.is_retweet(row):continue
  user=row.get('user') or {};handle=row.get('userScreenName') or user.get('screenName') or user.get('username');tid=str(row.get('id',''));date=stamp(row.get('createdAt',''))
  if not handle or not re.fullmatch('[A-Za-z0-9_]{1,15}',handle) or not tid.isdigit() or handle.lower()==p['account'].lower():continue
  if not date or date<int(since.timestamp()*1000) or date>int(time.time()*1000)+300000:continue
  if tid in seen:continue
  seen.add(tid)
  handle=handle.lower()
  text=row.get('text','')
  if p['account'].lower() not in text.lower() and p['name'].lower() not in text.lower() and '$'+p['symbol'].lower() not in text.lower():continue
  a=authors.setdefault(handle,{'account':handle,'avatar':row.get('userProfileImageUrl') or user.get('profileImageUrl') or user.get('profile_image_url_https'),'name':row.get('userName') or user.get('name') or handle,'text':text,'url':'https://x.com/'+handle+'/status/'+tid,'publishedAt':date,'count':0,'followers':row.get('userFollowers') or user.get('followersCount'),'identity':'近期讨论者，KOL 身份未核实'})
  observations.setdefault(handle,[]).append(discussion_quality.observation(row,date))
  a['count']+=1
  if date>a['publishedAt']:a.update(text=text,url='https://x.com/'+handle+'/status/'+tid,publishedAt=date)
 candidates=sorted(authors.values(),key=lambda a:a['publishedAt'],reverse=True)
 enrich_avatars(candidates+p.get('team',[]),request)
 discussion_quality.mark_shared_text(observations)
 for a in candidates:a['quality']=discussion_quality.quality(observations[a['account']])
 selected=discussion_quality.rank([a for a in candidates if eligible_discussant(a)])[:12]
 return {'status':'ok','discussants':selected,'team':[],'updatedAt':int(time.time()*1000),'message':'近 7 天提及官方账号，粉丝数至少 20,000；按样本持续性和内容形式排序；最多检索 40 条，非全量名单'}
