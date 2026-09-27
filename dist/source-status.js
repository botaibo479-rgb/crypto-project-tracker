// Source health is independent from credentials and from the age of an article.
function sourceHealth(source, now=Date.now()) {
 if(!source)return {kind:'pending',label:'等待首次采集'};
 if(source.status==='missing_credential')return {kind:'missing',label:'未配置凭证'};
 const success=Number(source.lastSuccessAt)||0;
 if(source.status==='error')return {kind:'error',label:success?'采集失败，保留上次结果':'采集失败，尚无成功记录'};
 if(source.status==='partial')return {kind:'partial',label:'部分账号采集失败'};
 if(source.status==='ok'){
  if(!success||now-success>45*60*1000)return {kind:'stale',label:'采集结果待更新'};
  return {kind:'ok',label:Number(source.count)===0?'本轮未检索到相关内容':'本轮获取 '+(source.count??'—')+' 条'};
 }
 return {kind:'limited',label:source.message||'来源暂不可用'};
}
function providerHealth(sources, now=Date.now()) {
 return [['X','OpenTwitter'],['OpenNews','OpenNews']].map(([label,key])=>{
  const rows=Object.values(sources||{}).flatMap(s=>Object.entries(s).filter(([name])=>name===key||(key==='OpenNews'&&name==='OpenNews关键词')).map(([,value])=>sourceHealth(value,now)));
  if(!rows.length)return label+' 等待采集';
  if(rows.every(s=>s.kind==='missing'))return label+' 未配置凭证';
  if(rows.every(s=>s.kind==='ok'))return label+' 采集正常';
  if(rows.some(s=>s.kind==='error'||s.kind==='partial'))return label+' 采集异常';
  if(rows.some(s=>s.kind==='stale'))return label+' 待更新';
  return label+' 部分来源待接入';
 }).join(' · ');
}
