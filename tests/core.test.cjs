const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const os=require('node:os');const path=require('node:path');
const {parsePlan}=require('../server/agent.cjs');const {validateAction}=require('../server/tools.cjs');const {Store}=require('../server/store.cjs');
test('planner rejects unregistered tools and extra parameters',()=>{
 assert.throws(()=>parsePlan('{"reply":"ok","actions":[{"tool":"run_code","params":{}}]}'));
 assert.throws(()=>validateAction({tool:'crop_image',params:{command:'anything'}}));
 assert.equal(parsePlan('{"reply":"planned","actions":[{"tool":"crop_image","params":{"left":20}}]}').actions[0].params.left,20);
});
test('version lookup is workspace-scoped and interrupted tasks persist honestly',()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'stereo-store-'));const store=new Store(dir);const first=store.db.sessions[0];const second=store.createSession();const asset=store.addAsset(first.id,{name:'sample'});
 assert.throws(()=>store.asset(asset.id,second.id));store.db.tasks.push({status:'running'});store.save();const restored=new Store(dir);assert.equal(restored.db.tasks[0].status,'interrupted');
});
test('deletion removes only the selected workspace records and keeps at least one workspace',()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'stereo-delete-'));const store=new Store(dir);const first=store.db.sessions[0];const other=store.createSession();
 const file=path.join(dir,'keep.png');fs.writeFileSync(file,'file must remain');const removed=store.addAsset(first.id,{name:'removed',file});const kept=store.addAsset(other.id,{name:'kept'});store.db.tasks.push({id:'one',sessionId:first.id,status:'completed'},{id:'two',sessionId:other.id,status:'completed'});store.save();
 const result=store.removeSession(first.id);assert.equal(result.fallbackSessionId,other.id);assert.throws(()=>store.session(first.id));assert.throws(()=>store.asset(removed.id,first.id));assert.equal(store.asset(kept.id,other.id).name,'kept');assert.deepEqual(store.db.tasks.map(t=>t.id),['two']);assert.ok(fs.existsSync(file));
 const reopened=new Store(dir);assert.equal(reopened.db.sessions.length,1);assert.throws(()=>reopened.removeSession('missing'));reopened.removeSession(other.id);assert.equal(reopened.db.sessions.length,1);assert.notEqual(reopened.db.sessions[0].id,other.id);assert.deepEqual(reopened.db.sessions[0].messages,[]);assert.equal(reopened.db.assets.length,0);assert.equal(reopened.db.tasks.length,0);
});
