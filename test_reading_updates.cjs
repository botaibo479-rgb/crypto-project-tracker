const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const {catchupItems,progressVersion}=vm.runInNewContext(fs.readFileSync('dist/reading-updates.js','utf8')+';({catchupItems,progressVersion})');
const item={id:1,p:'near',type:'news',discoveredAt:100,publishedAt:90};
test('catchup excludes read, old, hidden, future and market snapshots',()=>{
 const rows=[item,{...item,id:2,p:'other'},{...item,id:3,publishedAt:20},{...item,id:4,publishedAt:300},{...item,id:5,type:'market'}];
 assert.equal(catchupItems(rows,['near'],[],{},50,200).length,1);
 assert.equal(catchupItems(rows,['near'],[1],{'1':''},50,200).length,0);
});
test('new progress revives a read event once but a duplicate report does not',()=>{
 const changed={...item,progressCandidates:[{key:'a',publishedAt:150}]};
 assert.equal(catchupItems([changed],['near'],[1],{'1':''},120,200).length,1);
 assert.equal(catchupItems([changed],['near'],[1],{'1':progressVersion(changed)},120,200).length,0);
 assert.equal(catchupItems([{...item,lastRelatedAt:160,revision:'different'}],['near'],[1],{'1':''},50,200).length,0);
});

test("newly fetched historical news does not masquerade as a recent update",()=>{assert.equal(catchupItems([{...item,publishedAt:10,discoveredAt:150}],["near"],[],{},100,200).length,0)});

test('alert links open the matching event or chart without guessing absent URLs',()=>{
 const handlers={},nodes={},opened=[],notices=[];
 const ctx={
  document:{visibilityState:'visible',addEventListener:(name,fn)=>handlers[name]=fn,querySelectorAll:()=>[],querySelector:()=>({scrollIntoView(){}})},
  window:{addEventListener(){}},localStorage:{getItem:()=>null,setItem(){}},setInterval(){},
  events:[{id:1,type:'news',p:'near'},{id:2,newsId:'specific',type:'news',p:'near',url:'https://example.com/item'}],
  state:{view:'rules',projects:['near'],read:[]},catalog:[],originalSelections:new Set(),
  liveData:{alertState:{alerts:[{id:'missing',type:'news',evidence:{}},{id:'news',type:'news',evidence:{eventId:'specific'}},{id:'market',type:'oi',p:'near',evidence:{source:'Binance'}}]}},
  filteredEvents:()=>[],eventCard:()=>'',openDetail:id=>opened.push(id),render(){},persist(){},
  $:selector=>nodes[selector]||(nodes[selector]={value:'',insertAdjacentHTML(){}}),
  escapeHtml:String,formatTime:String,ruleDescription:()=>'',safeUrl:String,toast:t=>notices.push(t),chartSettings:{period:'1d'},newsSource:'team'
 };
 vm.runInNewContext(fs.readFileSync('dist/reading-updates.js','utf8'),ctx);
 const click=id=>handlers.click({target:{closest:()=>({dataset:{alertContext:id},hasAttribute:()=>false})}});
 click('missing');assert.equal(opened.length,0);assert.equal(notices.length,1);
 click('news');assert.deepEqual(opened,[2]);assert.ok(ctx.state.read.length===0);
 click('market');assert.equal(ctx.state.project,'near');assert.equal(ctx.state.view,'feed');assert.equal(ctx.chartSettings.period,'4h');assert.equal(ctx.newsSource,'all');
});
