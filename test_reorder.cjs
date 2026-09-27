const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const reorder=vm.runInNewContext(fs.readFileSync(path.join(__dirname,'dist/reorder.js'),'utf8')+';reorderProjects');
const input=()=>({projects:['soon','near','pha'],pinnedProjects:[],projectGroups:{near:'AI'}});
test('dropping after a later row actually moves downward',()=>{
 const s=input(),next=reorder(s,'soon','near',true);
 assert.equal(next.projects.join(','),'near,soon,pha');assert.equal(s.projects.join(','),'soon,near,pha');
 assert.equal(next.projectGroups.soon,'AI');
});
test('dropping before an earlier row moves upward',()=>{assert.equal(reorder(input(),'pha','soon').projects.join(','),'pha,soon,near')});
test('target pin group is inherited and invalid drops are no-ops',()=>{
 const s=input();s.pinnedProjects=['near'];assert.equal(reorder(s,'pha','near').pinnedProjects.join(','),'near,pha');
 assert.equal(reorder(s,'soon','missing'),null);assert.equal(reorder(s,'near','near'),null);
});
