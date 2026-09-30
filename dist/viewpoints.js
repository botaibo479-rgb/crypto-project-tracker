/* Source-backed local research journal. No position or profitability inference. */
(()=>{
 const cache=new Map(),pending=new Set(),names={positive:'明确看好',concern:'明确看空',unclear:'未明确 / 待判断'};
 const esc=escapeHtml;
 async function load(pid,force=false){if(pending.has(pid)||(!force&&Date.now()-(cache.get(pid)?.loadedAt||0)<60000))return;pending.add(pid);try{const r=await fetch('/api/viewpoints?project='+encodeURIComponent(pid));if(!r.ok)throw Error();cache.set(pid,{...await r.json(),loadedAt:Date.now()})}catch{cache.set(pid,{...cache.get(pid),error:true,loadedAt:Date.now()})}finally{pending.delete(pid);if(state.project===pid)render()}}
 function post(row){return `<article class="opinion-post"><small>@${esc(row.account)} · ${formatTime(row.publishedAt)} · ${names[row.stance]||names.unclear}</small><p>${esc((row.textZh||row.text).slice(0,160))}${(row.textZh||row.text).length>160?'…':''}</p>${(row.textZh||row.text).length>160?`<details><summary>展开全文</summary><p>${esc(row.textZh||row.text)}</p></details>`:''}${row.textZh&&row.textZh!==row.text?`<details><summary>显示原文</summary><p>${esc(row.text)}</p></details>`:''}<a href="${esc(safeUrl(row.url))}" target="_blank" rel="noopener noreferrer">核对原帖 ↗</a></article>`}
 function panel(p,x){if(!x)return `<section id="opinion-panel" class="project-section"><h3>观点与关注度</h3><p>正在加载本地观察记录…</p></section>`;
 const a=x.attention||{},coverage=x.coverage||{},latest=new Map();for(const r of x.posts||[])if(!latest.has(r.account))latest.set(r.account,r);
 return `<section id="opinion-panel" class="project-section"><div class="project-section-title"><h3>观点与关注度</h3><button class="secondary" data-op-watch>管理自选账号</button></div><p class="module-note">近 7 天原文 · 每位作者以最新一条归类 · 规则识别，仅识别直接表达，不推断持仓。${x.error?'读取失败，暂保留缓存。':''}</p><div class="attention-stats"><div><strong>${a.authors24h??'—'}</strong><small>24h 独立作者</small></div><div><strong>${a.posts24h??'—'}</strong><small>24h 原帖</small></div><div><strong>${a.newInSample??'积累中'}</strong><small>较前日样本新增作者</small></div><div><strong>${a.topShare==null?'—':Math.round(a.topShare*100)+'%'}</strong><small>单一作者占比最高</small></div></div><p class="module-note">仅代表已采集样本，不是全网热度或多空投票。最近成功：${formatTime(coverage.lastSuccessAt)}${coverage.status==='error'?' · 采集失败，旧数据':''}${coverage.limited?' · 返回数量触顶，样本可能截断':''}${coverage.watchErrors?.length?' · 部分自选账号查询失败':''}</p><div class="opinion-counts">${Object.entries(names).map(([k,n])=>`<span>${n} · ${[...latest.values()].filter(r=>r.stance===k).length}</span>`).join('')}</div><div class="opinion-columns">${Object.entries(names).map(([key,name])=>{const rows=[...latest.values()].filter(r=>r.stance===key);if(!rows.length)return '';return `<div><h4>${name} <span>${rows.length}</span></h4>${rows.slice(0,3).map(post).join('')||'<p class="module-note">尚无符合条件的原文</p>'}${rows.length>3?`<details><summary>更多 ${rows.length-3} 位作者</summary>${rows.slice(3).map(post).join('')}</details>`:''}</div>`}).join('')}</div><details><summary>按账号查看观点记录</summary><div class="opinion-accounts">${[...latest.keys()].map(account=>`<button class="secondary" data-op-history="${esc(account)}">@${esc(account)}</button>`).join('')||'等待下一轮采集'}</div></details><details><summary>观点变化线索 · ${x.changes?.length||0}</summary><label><input type="checkbox" data-op-alert ${x.enabled?'checked':''}> 记录此项目的明确方向变化（站内）</label><p class="module-note">仅比较同一作者 7 天内前后原文；开启后新发表内容才触发，历史补录不提醒。条件句、引用、期权和对冲表述不判方向。</p>${(x.changes||[]).slice().reverse().map(c=>`<details><summary>@${esc(c.after.account)} · ${names[c.before.stance]} → ${names[c.after.stance]} · ${formatTime(c.at)}</summary>${post(c.before)}${post(c.after)}</details>`).join('')}</details><details><summary>事件后续观察 · ${x.tracking?.length||0}</summary><p class="module-note">从点击跟踪时的行情开始，观察 1h / 24h / 7d，不是发帖成交价或 KOL 收益；本地服务需持续运行，错过的窗口显示缺失。</p>${(x.tracking||[]).map(t=>`<article class="opinion-post"><a href="${esc(safeUrl(t.url))}" target="_blank" rel="noopener noreferrer">${esc(t.title.replace(/<[^>]*>/g,' ').slice(0,180))}</a><p>起点 $${number(t.price)} · ${formatTime(t.priceAt)} · ${esc(t.source)}</p><p>${[['1h',3600000],['24h',86400000],['7d',604800000]].map(([k,ms])=>`${k}：${t.samples[k]?pct(t.samples[k].change):Date.now()>t.startedAt+ms+180000?'窗口已错过':'等待采样'}`).join(' · ')}</p><details><summary>跟踪后的项目动态（不代表同一事件进展）</summary>${events.filter(e=>(e.projectIds||[e.p]).includes(t.p)&&e.type==='news'&&!e.providerKind&&e.publishedAt>t.startedAt).slice(0,3).map(e=>`<p><button class="text-button" data-event="${e.id}">${esc(e.titleZh||e.title)}</button></p>`).join('')||'<p>暂无新收录动态</p>'}</details><button class="text-button" data-op-untrack="${esc(t.id)}">停止并移除</button></article>`).join('')||'<p>从资讯卡片点击「跟踪后续」开始。</p>'}</details></section>`;
 }
 const oldRender=render;render=function(){oldRender();document.querySelector('#opinion-panel')?.remove();if(state.project){const p=catalog.find(p=>p.id===state.project);if(p){(document.querySelector('#project-overview .news-divider')||document.querySelector('#project-overview')).insertAdjacentHTML(document.querySelector('#project-overview .news-divider')?'beforebegin':'beforeend',panel(p,cache.get(p.id)));load(p.id)}}};
 const oldCard=eventCard;eventCard=function(e){const html=oldCard(e);return e.type==='news'&&!e.providerKind?html.replace('<div class="event-bottom">',`<div class="event-bottom"><button class="text-button" data-op-track="${e.id}">跟踪后续</button>`):html};
 function watchForm(){const x=cache.get(state.project)||{};showForm(`${formTitle('自选 X 账号')}<p>不受 20k 粉丝限制。每半小时按关联项目检索提及官方账号的原帖；每个账号与项目组合最多 40 条，消耗现有 OpenTwitter 额度。不会在 X 上关注账号。</p>${(x.watches||[]).map(w=>`<p>@${esc(w.account)} · ${esc(w.note)}<small> ${w.projectIds.map(id=>esc(catalog.find(p=>p.id===id)?.symbol||id)).join(' / ')}</small> <button class="text-button" data-op-remove="${esc(w.account)}">移除</button></p>`).join('')}<form id="op-watch-form"><label class="field">账号<input name="account" required pattern="@?[A-Za-z0-9_]{1,15}" placeholder="@username"></label><label class="field">关联项目（可多选）<select name="projectIds" multiple required>${catalog.map(p=>`<option value="${esc(p.id)}" ${p.id===state.project?'selected':''}>${esc(p.symbol)}</option>`).join('')}</select></label><label class="field">私人备注<input name="note" maxlength="300"></label><p class="form-error"></p><button class="primary">保存 / 更新账号</button></form>`);$('#op-watch-form').onsubmit=async e=>{e.preventDefault();const f=new FormData(e.target);try{await postAPI('/api/viewpoints',{action:'watch',account:f.get('account'),projectIds:f.getAll('projectIds'),note:f.get('note')});await load(state.project,true);watchForm()}catch(err){e.target.querySelector('.form-error').textContent=err.message}}}
 document.addEventListener('change',async e=>{if(!e.target.matches('[data-op-alert]'))return;try{await postAPI('/api/viewpoints',{action:'alerts',projectId:state.project,enabled:e.target.checked});await load(state.project,true)}catch(err){e.target.checked=!e.target.checked;toast(err.message)}});
 document.addEventListener('click',async e=>{const b=e.target.closest('button');if(!b)return;const d=b.dataset;try{
 if('opWatch'in d)watchForm();
 if(d.opHistory){const rows=(cache.get(state.project)?.posts||[]).filter(r=>r.account===d.opHistory);showForm(`${formTitle('@'+d.opHistory+' · 最近观点')}${rows.map(post).join('')||'<p>暂未采集到符合条件的原文，等待下一轮采集。</p>'}`)}
 if(d.opRemove){await postAPI('/api/viewpoints',{action:'remove',account:d.opRemove});cache.clear();await load(state.project,true);watchForm()}
 if(d.opUntrack){await postAPI('/api/viewpoints',{action:'untrack',id:d.opUntrack});await load(state.project,true)}
 if(d.opTrack){const event=events.find(r=>r.id===Number(d.opTrack));if(!event)return;const pid=state.project||(event.projectIds||[event.p])[0];await postAPI('/api/viewpoints',{action:'track',projectId:pid,eventId:event.newsId});cache.delete(pid);await load(pid,true);toast('已开始观察，可在项目页查看后续')}
 }catch(err){toast(err.message)}});
 render();
})();

/* Compact project modules; expansion is a per-project, browser-local preference. */
(()=>{
 const storageKey='signal-project-module-expansion-v1';
 const modules=new Map([['项目资料与订阅','resources'],['资金与市场异动','market'],['团队成员的 X 账号','team'],['近期讨论者 / KOL','discussants'],['观点与关注度','opinions']]);
 let expanded={};
 try{const saved=JSON.parse(localStorage.getItem(storageKey)||'{}');if(saved&&typeof saved==='object'&&!Array.isArray(saved))expanded=saved}catch{}
 function apply(section,button,body,open){
  section.classList.toggle('module-collapsed',!open);body.hidden=!open;
  button.setAttribute('aria-expanded',String(open));
  button.querySelector('.module-toggle-label').textContent=open?'收起':'展开';
 }
 function foldModules(){
  if(!state.project)return;
  document.querySelectorAll('#project-overview .project-section').forEach(section=>{
   if(section.dataset.foldModule)return;
   const heading=section.querySelector(':scope > h3, :scope > .project-section-title > h3');
   const name=heading?.textContent.trim(),kind=modules.get(name);if(!kind)return;
   const key=state.project+':'+kind;section.dataset.foldModule=kind;section.classList.add('collapsible-module');
   let header=heading.parentElement;
   if(header===section){header=document.createElement('div');header.className='project-section-title';heading.before(header);header.append(heading)}
   const body=document.createElement('div');body.className='module-body';body.id='project-module-'+encodeURIComponent(state.project)+'-'+kind;
   for(const child of [...section.childNodes])if(child!==header)body.append(child);
   section.append(body);
   const button=document.createElement('button');button.type='button';button.className='module-toggle';button.setAttribute('aria-controls',body.id);
   const title=document.createElement('span');title.textContent=name;
   const label=document.createElement('span');label.className='module-toggle-label';
   button.append(title,label);heading.replaceChildren(button);
   apply(section,button,body,expanded[key]===true);
   button.addEventListener('click',()=>{
    const open=button.getAttribute('aria-expanded')!=='true';expanded[key]=open;apply(section,button,body,open);
    try{localStorage.setItem(storageKey,JSON.stringify(expanded))}catch{}
   });
  });
 }
 const previous=render;render=function(){previous();foldModules()};
 foldModules();
})();
