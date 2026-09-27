const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'dist/preferences.js'),'utf8');
const settle=()=>new Promise(resolve=>setImmediate(resolve));
test('a local edit during a remote poll is preserved and uploaded',async()=>{
 const defaults={hiddenProjects:[],pinnedProjects:[],projectGroups:{},projectOrder:['near'],unreadProjectsOnly:false,saved:[],read:[]};
 let remote=structuredClone(defaults),release,delay=false,poll;
 const context={state:{...structuredClone(defaults),projects:['near'],project:null,view:'feed'},catalog:[{id:'near'}],persist(){},render(){},toast(){},document:{hidden:false,querySelector(){return {textContent:''}},addEventListener(){}},window:{addEventListener(){}},setInterval(fn){poll=fn},fetch:async(url,options)=>{
  if(options.method==='POST'){const body=JSON.parse(options.body);remote={...remote,...body.values};return {ok:true,json:async()=>({values:structuredClone(remote)})}}
  const snapshot=structuredClone(remote);
  if(delay)await new Promise(resolve=>release=resolve);
  return {ok:true,json:async()=>({values:snapshot})};
 }};
 vm.createContext(context);vm.runInContext(source,context);await settle();
 delay=true;const waiting=poll();await settle();
 context.state.saved=[123];vm.runInContext('persist()',context);
 release();await waiting;await settle();
 assert.deepEqual(remote.saved,[123]);assert.equal(context.state.saved[0],123);
});
