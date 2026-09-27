const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const freshNotifications=vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'dist/notifications.js'),'utf8')+';freshNotifications');
test('old, future, stale and previously delivered records do not notify',()=>{
 const now=1000000,since=900000;
 const rows=[{id:'old',at:since},{id:'future',at:now+1},{id:'seen',at:now-1},{id:'fresh',at:now-1}];
 assert.deepEqual(freshNotifications(rows,['seen'],since,now).map(a=>a.id),['fresh']);
 assert.deepEqual(freshNotifications([{id:'stale',at:now-120001}],[],0,now),[]);
});
test('repeated snapshots and duplicates produce at most one candidate',()=>{
 const a={id:'one',at:990000};
 assert.equal(freshNotifications([a,a],[],900000,1000000).length,1);
 assert.equal(freshNotifications([a],['one'],900000,1000000).length,0);
});
test('enabling notifications never catches up historical records',()=>{
 assert.equal(freshNotifications([{id:'before-opt-in',at:990000}],[],995000,1000000).length,0);
});
