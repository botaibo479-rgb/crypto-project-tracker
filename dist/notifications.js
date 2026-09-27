/* Foreground-page notifications only; no background push subscription. */
function freshNotifications(alerts, seen, since, now) {
 const known=new Set(seen);
 return alerts.filter(a=>{if(!a.id||known.has(a.id)||!Number.isFinite(a.at)||a.at<=since||a.at>now||now-a.at>120000)return false;known.add(a.id);return true});
}
if(typeof document!=='undefined'){
 const key='signal-browser-notifications-v1';
 let initialized=false,startedAt=Date.now(),problem='';
 const supported=()=>typeof Notification!=='undefined'&&window.isSecureContext&&Boolean(navigator.locks);
 const load=()=>{try{return JSON.parse(localStorage.getItem(key)||'{}')}catch{return {}}};
 const save=v=>localStorage.setItem(key,JSON.stringify(v));
 function panel(){
  const old=document.getElementById('browser-notifications');if(old)old.remove();
  const box=document.createElement('section');box.id='browser-notifications';box.className='evidence';
  const enabled=load().enabled&&supported()&&Notification.permission==='granted';
  const message=!supported()?'当前浏览器不支持此功能。':Notification.permission==='denied'?'通知权限已被拒绝，可在浏览器的网站设置中更改。':enabled?'已开启本浏览器提醒。':'尚未开启。';
  const p=document.createElement('p');p.textContent=message+' 需要页面保持打开；手机后台可能暂停，关闭页面后不会推送。后台触发记录仍会保留。';box.append(p);
  const button=document.createElement('button');button.className='secondary';button.textContent=enabled?'关闭浏览器提醒':'开启浏览器提醒';button.disabled=!supported()||Notification.permission==='denied';
  button.addEventListener('click',async()=>{
   try{
    if(enabled){await navigator.locks.request(key,()=>save({...load(),enabled:false}));}
    else{
     const permission=await Notification.requestPermission();
     if(permission==='granted')await navigator.locks.request(key,()=>{const old=load();save({...old,enabled:true,enabledAt:Date.now(),seen:[...new Set([...(old.seen||[]),...(liveData?.alertState?.alerts||[]).map(a=>a.id)])].slice(-1000)});});
    }
    problem='';
   }catch{problem='无法保存或开启通知，站内记录不受影响。'}
   panel();
  });box.append(button);
  if(problem){const error=document.createElement('p');error.setAttribute('role','status');error.textContent=problem;box.append(error);}
  document.getElementById('feed').prepend(box);
 }
 const prior=renderRules;renderRules=function(){prior();panel()};
 async function deliver(data){
  if(!supported())return;
  try{await navigator.locks.request(key,()=>{
   const config=load(),alerts=data.alertState?.alerts||[],now=Date.now();
   const fresh=initialized&&config.enabled&&Notification.permission==='granted'?freshNotifications(alerts,config.seen||[],Math.max(startedAt,config.enabledAt||0),now):[];
   initialized=true;
   // Persist before delivery: multiple tabs must not notify for the same record.
   save({...config,seen:[...new Set([...(config.seen||[]),...alerts.map(a=>a.id)])].slice(-1000)});
   if(!fresh.length)return;
   const latest=fresh[fresh.length-1];
   const notification=new Notification(fresh.length>1?`Signal · ${fresh.length} 条新提醒`:`Signal · ${latest.ruleName}`,{body:fresh.length>1?'打开提醒规则查看触发依据。':latest.type==='news'?(latest.titleZh||'新的重点消息候选，点击查看原文与依据。'):latest.title,tag:'signal-'+latest.id});
   notification.onclick=()=>{window.focus();state.view='rules';state.project=null;state.query='';$('#search').value='';render();notification.close()};
  });}catch{problem='浏览器通知暂不可用，触发记录仍在站内保留。'}
 }
 window.addEventListener('signal-live',event=>{deliver(event.detail)});
 window.addEventListener('storage',event=>{if(event.key===key&&state.view==='rules'&&!state.project)panel()});
 if(state.view==='rules'&&!state.project)panel();
}
