const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {sourceHealth,providerHealth}=vm.runInNewContext(fs.readFileSync('dist/source-status.js','utf8')+';({sourceHealth,providerHealth})');
const now=10000000;
test('failed authenticated collection is not shown as missing credentials',()=>{
 const message=providerHealth({near:{OpenTwitter:{status:'error'},OpenNews:{status:'ok',lastSuccessAt:now,count:2}}},now);
 assert.match(message,/X 采集异常/);assert.match(message,/OpenNews 采集正常/);assert.doesNotMatch(message,/未配置/);
});
test('empty successful query differs from stale or failed retained results',()=>{
 assert.equal(sourceHealth({status:'ok',count:0,lastSuccessAt:now},now).label,'本轮未检索到相关内容');
 assert.equal(sourceHealth({status:'ok',count:3,lastSuccessAt:now-46*60000},now).kind,'stale');
 assert.match(sourceHealth({status:'error',lastSuccessAt:now-1000},now).label,/保留上次/);
 assert.equal(sourceHealth({status:'missing_credential'},now).kind,'missing');
});
test('keyword query failure remains visible alongside successful coin query',()=>{
 assert.match(providerHealth({near:{OpenNews:{status:'ok',lastSuccessAt:now},OpenNews关键词:{status:'error'}}},now),/OpenNews 采集异常/);
});
