/* Local reading sessions and evidence-linked navigation. No remote publication. */
function progressVersion(e){return (e.progressCandidates||[]).map(u=>u.key).sort().join('|')}
function readingUpdateAt(e){return Math.max(e.publishedAt||0,...(e.progressCandidates||[]).map(u=>u.publishedAt||0))}
function catchupItems(rows,projects,read,versions,since,now=Date.now()){
 return rows.filter(e=>e.type==='news'&&projects.includes(e.p)&&readingUpdateAt(e)<=now&&readingUpdateAt(e)>since&&(!read.includes(e.id)||(versions[e.id]!==undefined&&versions[e.id]!==progressVersion(e))))
 .sort((a,b)=>Number(b.high)-Number(a.high)||readingUpdateAt(b)-readingUpdateAt(a));
}
if(typeof document!=='undefined'){
 let ledger={};try{ledger=JSON.parse(localStorage.getItem('signal-reading-v2')||'{}')}catch{}
 const openedAt=Date.now(),since=Math.min(Number(ledger.lastVisit)||openedAt-86400000,openedAt);
 let versions=ledger.versions||{},catchupOnly=false,alertContext=null;
 function saveLedger(){try{localStorage.setItem('signal-reading-v2',JSON.stringify({lastVisit:Date.now(),versions}))}catch{}}
 setInterval(()=>{if(document.visibilityState==='visible')saveLedger()},30000);
 window.addEventListener('pagehide',saveLedger);
 document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')saveLedger()});
 function freshItems(){return catchupItems(events,state.projects,state.read,versions,since)}
 function translationNotice(e){
  if(e.type!=='news'||e.translationStatus==='ready'||originalSelections.has(e.id))return '';
  const details=Object.values(e.translationDetails||{}),retry=Math.max(0,...details.map(x=>x.retryAt||0),liveData?.translation?.retryAt||0);
  const limited=details.some(x=>x.status==='rate_limited')||liveData?.translation?.status==='rate_limited';
  const failed=details.some(x=>x.status==='failed');
  return `<p class="translation-note">${limited?'翻译服务限流':failed?'本次翻译失败':'中文译文待处理'} · 未就绪部分先显示原文${retry?' · '+formatTime(retry)+' 后自动重试':' · 后台自动处理'}</p>`;
 }
 const oldFilter=filteredEvents;
 filteredEvents=function(){const rows=oldFilter();return catchupOnly&&state.view==='feed'?rows.filter(e=>freshItems().some(x=>x.id===e.id)):rows};
 const oldCard=eventCard;
 eventCard=function(e){let html=oldCard(e);const changed=state.read.includes(e.id)&&versions[e.id]!==undefined&&versions[e.id]!==progressVersion(e);
  return html.replace('<div class="event-bottom">',translationNotice(e)+(changed?'<p class="translation-note">已读事件有新增进展</p>':'')+'<div class="event-bottom">');
 };
 const oldDetail=openDetail;
 openDetail=function(id){const e=events.find(x=>x.id===id);if(e){versions[id]=progressVersion(e);saveLedger()}oldDetail(id);if(!e||e.type!=='news')return;
  const footer=$('#detail-content .modal-footer');footer?.insertAdjacentHTML('beforebegin',translationNotice(e));
  if(e.relatedItems?.length){
   // Replace the old related-report block with one chronological timeline.
   document.querySelectorAll('#detail-content .quality-evidence').forEach(n=>{if(n.textContent.includes('相关报道与各方表述'))n.remove()});
   const timeline=e.relatedItems.slice().sort((a,b)=>(a.publishedAt||0)-(b.publishedAt||0));
   footer?.insertAdjacentHTML('beforebegin',`<section class="event-timeline"><h3>同一事件的时间线</h3><p class="module-note">${escapeHtml(e.clusterReason||'保留各方原文；不代表独立证实')}。新增表述属于待核对候选。</p>${timeline.map((item,i)=>{const u=(e.progressCandidates||[]).find(x=>x.url===item.url&&x.publishedAt===item.publishedAt);const role=item.channel==='team'?'团队表述':item.channel==='x'?'官方账号':item.channel==='opennews'?'聚合报道':'来源报道';return `<details ${u||i===0?'open':''} class="related-report"><summary>${formatTime(item.publishedAt)} · ${escapeHtml(role)} · ${escapeHtml(item.source)} ${u?'· 新增进展':''}</summary>${u?`<div class="evidence">新增表述：${escapeHtml(u.signals.join('、'))}</div>`:''}<p>${escapeHtml(originalSelections.has(id)?item.summary:(item.summaryZh??item.summary))}</p>${!item.summaryZh?'<small>此段为原文，译文待就绪</small>':''}<a class="evidence-link" target="_blank" rel="noopener noreferrer" href="${escapeHtml(safeUrl(item.url))}">核对这条原文 ↗</a></details>`}).join('')}</section>`);
  }
 };
 const oldRender=render;
 render=function(){for(const e of events){if(state.read.includes(e.id)&&versions[e.id]===undefined)versions[e.id]=progressVersion(e)}oldRender();
  const items=freshItems();
  if(state.view==='feed'&&!state.project){
   const groups=catalog.filter(p=>state.projects.includes(p.id)).map(p=>({p,items:items.filter(e=>e.p===p.id)})).filter(g=>g.items.length);
   $('#feed').insertAdjacentHTML('afterbegin',`<section class="catchup-panel"><div class="project-section-title"><h3>${ledger.lastVisit?'上次看完后发生了什么':'先看最近 24 小时的更新'}</h3><button class="text-button" data-catchup-toggle>${catchupOnly?'显示全部资讯':'只看这些更新'}</button></div><p class="module-note">${ledger.lastVisit?'本浏览器上次访问':'统计起点'} ${formatTime(since)} · 所有关注项目 · ${items.length} 件未读更新 · ${items.filter(e=>e.high).length} 件重点候选。按事件整理已有标题，不生成未经核对的结论。</p>${groups.map(g=>`<div class="catchup-group"><strong>${escapeHtml(g.p.name)} · ${g.items.length} 件</strong>${g.items.slice(0,2).map(e=>`<button class="catchup-item" data-event="${e.id}">${e.high?'● ':''}${escapeHtml(e.titleZh||e.title)}${e.progressCandidates?.length?' · 含后续进展':''}</button>`).join('')}</div>`).join('')||'<p>暂时没有新的未读更新。</p>'}${items.length?'<button class="secondary" data-catchup-read>将本次更新全部标为已读</button>':''}</section>`);
  }
  if(state.view==='rules'){
   const rows=liveData?.alertState?.alerts||[];
   document.querySelectorAll('.alert-history details').forEach((node,i)=>{const a=rows[rows.length-1-i];if(!a)return;
    const para=node.querySelector('p');if(para&&['news','listing','funding','liquidation','flow'].includes(a.type)&&!a.titleZh)para.textContent=a.title+'（原文）';
    node.insertAdjacentHTML('beforeend',`<p class="module-note">触发于 ${formatTime(a.at)} · ${escapeHtml(a.evidence?.source||(['news','listing','funding','liquidation','flow'].includes(a.type)?'来源见原文':'历史记录未保存来源'))}${a.ruleSnapshot?' · 当时规则：'+escapeHtml(ruleDescription({...a.ruleSnapshot,type:a.type})):''}</p><button class="secondary" data-alert-context="${escapeHtml(a.id)}">${['news','listing','funding','liquidation','flow'].includes(a.type)?'查看事件与原文':'查看项目 K 线'}</button>`);
   });
  }
  if(alertContext&&state.project===alertContext.p){
   const a=alertContext;$('#project-overview').insertAdjacentHTML('afterbegin',`<div class="alert-context evidence">正在回看提醒 · ${escapeHtml(a.ruleName)} · ${formatTime(a.at)}<br>${escapeHtml(a.title)}<br>图表展示当前所选窗口；触发时数值以原始记录为准。<button class="text-button" data-alert-back>返回触发记录</button></div>`);
  }
 };
 document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;
  if(b.hasAttribute('data-catchup-toggle')){catchupOnly=!catchupOnly;render()}
  if(b.hasAttribute('data-catchup-read')){for(const item of freshItems()){if(!state.read.includes(item.id))state.read.push(item.id);versions[item.id]=progressVersion(item)}state.read=state.read.slice(-5000);saveLedger();persist();render()}
  if(b.dataset.alertContext){const a=liveData?.alertState?.alerts.find(x=>x.id===b.dataset.alertContext);if(!a)return;
   if(['news','listing','funding','liquidation','flow'].includes(a.type)){const event=events.find(x=>(a.evidence?.eventId&&x.newsId===a.evidence.eventId)||(a.evidence?.url&&(x.url===a.evidence.url||x.relatedItems?.some(r=>r.url===a.evidence.url))));if(event){openDetail(event.id);return}toast('该事件已不在当前缓存，可从记录打开来源原文');return}
   alertContext=a;catchupOnly=false;state.project=a.p;state.view='feed';state.filter='all';state.query='';$('#search').value='';newsSource='all';$('#news-source').value='all';chartSettings.period=['1h','4h','1d'].includes(a.ruleSnapshot?.period)?a.ruleSnapshot.period:'4h';render();document.querySelector('.linked-chart')?.scrollIntoView({behavior:'smooth',block:'center'});
  }
  if(b.hasAttribute('data-alert-back')){alertContext=null;state.project=null;state.view='rules';render()}
 });
 render();
}
