const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const os=require('node:os');const path=require('node:path');
const {startServer}=require('../server/index.cjs');
test('upload, deterministic edit chain, undo, persistence and failure recovery',async()=>{
 const dataRoot=fs.mkdtempSync(path.join(os.tmpdir(),'stereo-integration-'));const instance=await startServer({port:17873,modelPort:17874,autoStartModel:false,stereoEnabled:false,dataRoot});
 const call=async(route,body)=>{const r=await fetch(instance.url+'/api/'+route,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return {status:r.status,data:await r.json()};};
 try{
  const state=(await call('state')).data;const sessionId=state.sessions[0].id;
  const uploaded=await call('upload',{sessionId,name:'sample.png',base64:fs.readFileSync(path.join(__dirname,'fixtures/sample.png')).toString('base64')});assert.equal(uploaded.status,201);assert.equal(uploaded.data.width,320);
  let result=await call('tool',{sessionId,action:{tool:'crop_image',params:{left:20}}});assert.equal(result.status,200);
  let s=(await call('state')).data;let active=s.assets.find(a=>a.id===s.sessions[0].activeAssetId);assert.equal(active.width,300);assert.equal(active.parentId,uploaded.data.id);
  result=await call('tool',{sessionId,action:{tool:'crop_image',params:{left:9999}}});assert.equal(result.status,400);assert.equal((await call('state')).data.sessions[0].activeAssetId,active.id);
  await call('tool',{sessionId,action:{tool:'adjust_color',params:{saturation:1.1}}});await call('tool',{sessionId,action:{tool:'resize_image',params:{width:150}}});
  s=(await call('state')).data;active=s.assets.find(a=>a.id===s.sessions[0].activeAssetId);assert.equal(active.width,150);assert.equal(active.height,100);
  await call('tool',{sessionId,action:{tool:'undo',params:{}}});s=(await call('state')).data;assert.equal(s.assets.find(a=>a.id===s.sessions[0].activeAssetId).width,300);
  result=await call('tool',{sessionId,action:{tool:'generate_stereo',params:{}}});assert.equal(result.status,400);assert.match(result.data.error,/not enabled/);
  instance.model.complete=async()=>'{"reply":"I will crop then adjust saturation.","actions":[{"tool":"crop_image","params":{"right":10}},{"tool":"adjust_color","params":{"saturation":1.2}}]}';
  const task=(await call('chat',{sessionId,text:'Crop right 10px and increase saturation'})).data;for(let i=0;i<60;i++){await new Promise(r=>setTimeout(r,100));const t=instance.store.db.tasks.find(t=>t.id===task.id);if(t.status!=='running'){assert.equal(t.status,'completed');assert.equal(t.steps.length,2);break;}if(i===59)assert.fail('Task did not finish');}
  assert.ok(instance.store.db.sessions[0].messages.some(m=>m.role==='assistant'&&m.content.includes('✓')));
  instance.model.complete=(_messages,signal)=>new Promise((resolve,reject)=>{signal.addEventListener('abort',()=>reject(new Error('Aborted')),{once:true});});
  const pending=(await call('chat',{sessionId,text:'A task used to test cancellation'})).data;assert.equal((await call('sessions/delete',{sessionId,confirmed:true})).status,409);assert.ok(instance.store.session(sessionId));await call('cancel',{});for(let i=0;i<10&&instance.agent.running;i++)await new Promise(r=>setTimeout(r,25));assert.equal(instance.store.db.tasks.find(t=>t.id===pending.id).status,'cancelled');
  const exported=await call('tool',{sessionId,action:{tool:'export_image',params:{format:'jpg'}}});assert.equal(exported.status,200);const restored=(await call('state')).data;const exportAsset=restored.assets.find(a=>a.id===exported.data.asset);assert.equal(exportAsset.format,'jpg');assert.equal(exportAsset.width,290);
  const download=await fetch(instance.url+'/media/'+exportAsset.id+'?download');assert.equal(download.status,200);assert.match(download.headers.get('content-type'),/image\/jpeg/);
  const forbidden=await fetch(instance.url+'/api/sessions',{method:'POST',headers:{Origin:'http://evil.example','Content-Type':'application/json'},body:'{}'});assert.equal(forbidden.status,403);
  assert.equal((await call('sessions/delete',{sessionId})).status,400);assert.ok(instance.store.session(sessionId));
  const other=(await call('sessions',{})).data;assert.equal((await call('sessions/delete',{sessionId,confirmed:true})).status,200);assert.equal((await call('state')).data.sessions[0].id,other.id);assert.equal((await fetch(instance.url+'/media/'+uploaded.data.id)).status,404);assert.ok(fs.existsSync(uploaded.data.file));
  const last=await call('sessions/delete',{sessionId:other.id,confirmed:true});assert.equal(last.status,200);assert.notEqual(last.data.fallbackSessionId,other.id);assert.equal((await call('state')).data.sessions.length,1);
  console.log('Integration data:',dataRoot);
 }finally{await instance.close();}
});

test('chat persists the sent image and executes edits on the selected version',async()=>{
 const dataRoot=fs.mkdtempSync(path.join(os.tmpdir(),'stereo-chat-image-'));
 const instance=await startServer({port:17875,modelPort:17876,autoStartModel:false,dataRoot});
 const call=async(route,body)=>{
  const response=await fetch(instance.url+'/api/'+route,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  return {status:response.status,data:await response.json()};
 };
 const waitForTask=async(id)=>{
  for(let i=0;i<100;i++){
   const task=instance.store.db.tasks.find(task=>task.id===id);
   if(task?.finishedAt)return task;
   await new Promise(resolve=>setTimeout(resolve,25));
  }
  assert.fail('Chat image task did not finish.');
 };
 try{
  const session=instance.store.db.sessions[0];
  const sessionId=session.id;
  const base64=fs.readFileSync(path.join(__dirname,'fixtures/sample.png')).toString('base64');
  const inputs=[];
  instance.model.complete=async messages=>{
   inputs.push(messages[1].content);
   return JSON.stringify({reply:'Cropping the image.',actions:[{tool:'crop_image',source:'current',params:{left:20}}]});
  };
  const sent=await call('chat',{sessionId,text:'Crop the new image.',attachment:{name:'New image.png',base64}});
  assert.equal(sent.status,202);
  const first=await waitForTask(sent.data.id);
  assert.equal(first.status,'completed',first.error);
  const original=instance.store.asset(first.sourceAssetId,sessionId);
  const edit=instance.store.asset(first.steps[0].assetId,sessionId);
  assert.equal(edit.parentId,original.id);
  assert.equal(edit.width,300);
  assert.equal(session.activeAssetId,edit.id);
  assert.equal(session.messages[0].assetId,original.id);
  assert.equal(session.messages[0].content,'Crop the new image.');
  assert.equal(inputs[0][1].image_url.url,'data:image/jpeg;base64,'+fs.readFileSync(original.thumbnail).toString('base64'));

  const followUp=await call('chat',{sessionId,text:'Crop the original again.',assetId:original.id});
  assert.equal(followUp.status,202);
  const second=await waitForTask(followUp.data.id);
  assert.equal(second.status,'completed',second.error);
  assert.equal(instance.store.asset(second.steps[0].assetId,sessionId).parentId,original.id);
  assert.equal(instance.store.asset(second.steps[0].assetId,sessionId).width,300);
  const saved=JSON.parse(fs.readFileSync(path.join(dataRoot,'workspace.json'),'utf8'));
  assert.deepEqual(saved.sessions[0].messages.filter(message=>message.role==='user').map(message=>message.assetId),[original.id,original.id]);

  const detached=await call('chat',{sessionId,text:'Crop without an attached image.',assetId:null});
  assert.equal(detached.status,202);
  const noImage=await waitForTask(detached.data.id);
  assert.equal(noImage.status,'failed');
  assert.match(noImage.error,/Attach an image/);
  assert.equal(inputs[2].length,1);
  assert.equal(instance.store.db.assets.length,3);

  const imageOnly=await call('chat',{sessionId,text:'',assetId:edit.id});
  assert.equal(imageOnly.status,202);
  const description=await waitForTask(imageOnly.data.id);
  assert.equal(description.status,'completed',description.error);
  assert.equal(description.steps.length,0);
  assert.equal(instance.store.db.assets.length,3);
  assert.equal(session.messages.at(-2).assetId,edit.id);

  const other=(await call('sessions',{})).data;
  const foreign=await call('chat',{sessionId:other.id,text:'Describe this image.',assetId:original.id});
  assert.equal(foreign.status,400);
  assert.equal(other.messages.length,0);
  assert.equal(instance.store.session(other.id).messages.length,0);
  assert.equal(inputs.length,4);
 }finally{await instance.close();}
});
