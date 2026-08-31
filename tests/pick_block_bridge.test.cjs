const {readFileSync}=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const assert=require('node:assert/strict');
const source=readFileSync(path.join(__dirname,'../static/js/inventar/user-inventory.js'),'utf8');
const start=source.indexOf('  function bindExternalEvents()');
const end=source.indexOf('\n  function ',start+10);
assert(start>=0 && end>start);
function bridge(referrer='http://localhost:5100/editor') {
  const events={},calls=[],parent={};
  const context={window:{parent,addEventListener:(name,handler)=>{events[name]=handler;}},
    document:{referrer,addEventListener:()=>{}},URL,Number,EVENTS:{setSlot:'vectoplan:user-inventory-set-slot'},
    setSlotItem:(...args)=>calls.push(args),error:()=>{}};
  vm.runInNewContext(source.slice(start,end)+'\nbindExternalEvents();',context);
  return {calls,send:(extra={})=>events.message({source:parent,origin:'http://localhost:5100',
    data:{source:'vectoplan-editor',type:context.EVENTS.setSlot,detail:{slotIndex:9,item:{family_id:'wall'}}},...extra})};
}
test('host middle-pick goes through normal persistent slot handling',()=>{
  const b=bridge();b.send();assert.equal(b.calls.length,1);
  assert.equal(b.calls[0][0],9);assert.equal(b.calls[0][1].family_id,'wall');
  assert.equal(b.calls[0][2].persist,true);assert.equal(b.calls[0][2].select,true);
});
test('untrusted source/origin and missing referrer cannot mutate the user inventory',()=>{
  const b=bridge();b.send({origin:'https://untrusted.example'});b.send({source:{}});assert.equal(b.calls.length,0);
  const missing=bridge('');missing.send();assert.equal(missing.calls.length,0);
});
