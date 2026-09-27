/* Shared preferences for the single-owner service. Notification permission stays local. */
{
 const fields=['hiddenProjects','pinnedProjects','projectGroups','projectOrder','unreadProjectsOnly','saved','read'];
 const clone=x=>JSON.parse(JSON.stringify(x));
 const equal=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
 const snapshot=()=>Object.fromEntries(fields.map(k=>[k,clone(state[k])]));
 const localPersist=persist;
 let baseline={},desired=snapshot(),observed=snapshot(),ready=false,busy=false,dirty=false,message='正在同步阅读偏好…';
 function status(text){message=text;const node=document.querySelector('footer span');if(node)node.textContent=text}
 function apply(values){
  for(const k of fields)if(k in values)state[k]=clone(values[k]);
  state.projects=catalog.filter(p=>!state.hiddenProjects.includes(p.id)).map(p=>p.id).sort((a,b)=>{const ai=state.projectOrder.indexOf(a),bi=state.projectOrder.indexOf(b);return (ai<0?9999:ai)-(bi<0?9999:bi)});
  if(state.project&&!state.projects.includes(state.project)){state.project=null;state.view='feed'}
  observed=snapshot();localPersist();render();status(message);
 }
 persist=function(){
  localPersist();const current=snapshot();
  for(const k of fields)if(!equal(current[k],observed[k])){desired[k]=clone(current[k]);dirty=true}
  observed=current;if(dirty){status('偏好待同步…');flush()}
 };
 const priorRender=render;render=function(){priorRender();status(message)};
 async function flush(){
  if(!ready||busy||!dirty)return;busy=true;
  try{
   const sent=clone(desired),values={},base={};
   for(const k of fields)if(!equal(sent[k],baseline[k])){values[k]=sent[k];base[k]=baseline[k]??null}
   if(!Object.keys(values).length){dirty=false;status('阅读偏好已同步');return}
   const response=await fetch('/api/preferences',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base,values})});
   const data=await response.json();
   if(response.status===409){baseline=data.values;desired={...snapshot(),...clone(data.values)};dirty=false;status('同步冲突：已载入服务器版本，请重做刚才的修改');apply(data.values);toast('另一设备修改了相同偏好，已载入服务器版本');return}
   if(!response.ok)throw Error(data.error||'同步失败');
   baseline=data.values;
   // Preserve edits made while this request was in flight.
   for(const k of fields)if(equal(desired[k],sent[k])&&k in data.values)desired[k]=clone(data.values[k]);
   dirty=fields.some(k=>!equal(desired[k],baseline[k]));
   status(dirty?'偏好待同步…':'阅读偏好已同步');apply(desired);
  }catch{status('偏好未同步，已保留本机修改；连接恢复后重试')}
  finally{busy=false}
 }
 async function sync(){
  if(busy)return;if(ready&&dirty){await flush();return}busy=true;const beforePoll=clone(desired);
  try{
   const response=await fetch('/api/preferences',{cache:'no-store'});if(!response.ok)throw Error('读取失败');const data=await response.json();
   baseline=data.values;
   if(!ready){
    const pending=clone(desired),changed=dirty;
    if(Object.keys(baseline).length){desired={...snapshot(),...clone(baseline)};if(changed)for(const k of fields)if(!equal(pending[k],initial[k]))desired[k]=pending[k]}
    dirty=fields.some(k=>!equal(desired[k],baseline[k]));ready=true;
   }else{const pending=clone(desired);desired={...snapshot(),...clone(baseline)};for(const k of fields)if(!equal(pending[k],beforePoll[k]))desired[k]=pending[k];dirty=fields.some(k=>!equal(desired[k],baseline[k]))}
   status(dirty?'正在保存阅读偏好…':'阅读偏好已同步');apply(desired);
  }catch{status('偏好同步不可用，当前使用本机记录')}
  finally{busy=false}
  if(ready&&dirty)await flush();
 }
 const initial=clone(desired);
 sync();setInterval(sync,15000);window.addEventListener('online',sync);
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)sync()});
}
