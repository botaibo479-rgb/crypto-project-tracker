const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const ctx={};vm.createContext(ctx);vm.runInContext(fs.readFileSync('dist/workspace.js','utf8'),ctx);
test('views AND fields, OR words, exclusions win, saved and project restrictions',()=>{
 const e={type:'news',channel:'team',title:'NEAR mainnet launch',summary:'long article',projectIds:['near','pha']};
 assert.equal(ctx.viewMatches(e,{include:['hack','mainnet'],channels:['team'],projectIds:['pha']},false),true);
 assert.equal(ctx.viewMatches(e,{include:['mainnet'],exclude:['launch']},false),false);
 assert.equal(ctx.viewMatches(e,{savedOnly:true},false),false);
 assert.equal(ctx.viewMatches(e,{projectIds:['nil']},true),false);
});
test('unrelated removes only one project and undo restores it',()=>{
 const e={id:1,p:'near',projectIds:['near','pha'],url:'https://example.com/a'};
 const feedback=[{kind:'unrelated',projectId:'near',eventKey:e.url}];
 assert.equal(ctx.visibleProjects(e,feedback).join(','),'pha');
 assert.equal(ctx.feedbackReason(e,feedback,null,['near','pha']),'');
 assert.notEqual(ctx.feedbackReason(e,feedback,'near',['near','pha']),'');
 assert.equal(ctx.visibleProjects(e,[]).join(','),'near,pha');
});
test('muting by stable feed URL survives source label changes',()=>{
 const e={p:'near',source:'new name',sourceUrl:'https://example.com/feed'};
 assert.notEqual(ctx.feedbackReason(e,[{kind:'source',value:e.sourceUrl}],null,['near']),'');
 assert.equal(ctx.feedbackReason(e,[{kind:'topic',value:'security',projectId:'pha'}],null,['near']),'');
});
