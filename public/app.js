const $=s=>document.querySelector(s);
let state=null,sessionId=localStorage.getItem('stereo-session'),lastKey='',lastSessionsKey='',lastVersionsKey='';
let sending=false,selectingImage=false,stereoPending=false,stereoSource,deleteTargetId=null,deleting=false;
let stateRequest=0,lastAppliedStateRequest=0;
const drafts=new Map();
window.__errors=[];
window.addEventListener('error',e=>window.__errors.push(e.message));
async function api(route,body){const r=await fetch('/api/'+route,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw new Error(data.error||'Request failed');return data;}
function el(tag,className,text){const n=document.createElement(tag);if(className)n.className=className;if(text!==undefined)n.textContent=text;return n;}
function messageContent(message){const content=el('div','message-content');if(message.role==='assistant'&&window.marked&&window.DOMPurify){content.classList.add('formatted');content.innerHTML=DOMPurify.sanitize(marked.parse(String(message.content||''),{breaks:true,gfm:true}),{ALLOWED_TAGS:['p','br','strong','em','ul','ol','li','code','pre','blockquote','h1','h2','h3','h4','hr','table','thead','tbody','tr','th','td'],ALLOWED_ATTR:[]});}else content.textContent=message.content;return content;}
let toastTimer;function toast(text){$('#toast').textContent=text;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,6500);}
function current(){return state?.sessions.find(s=>s.id===sessionId);}
let scrollSessionId=null,followConversation=true;
function draft(){
 if(!drafts.has(sessionId))drafts.set(sessionId,{text:'',file:null,url:null,useSelected:true});
 return drafts.get(sessionId);
}
function activeImage(){
 return state?.assets.find(asset=>asset.id===current()?.activeAssetId&&asset.sessionId===sessionId);
}
function clearDraftFile(entry){
 if(entry?.url)URL.revokeObjectURL(entry.url);
 if(entry){entry.file=null;entry.url=null;}
}
function chooseSession(id){
 if(id!==sessionId)$('#prompt').value=drafts.get(id)?.text||'';
 sessionId=id;
 localStorage.setItem('stereo-session',id);
 followConversation=true;
 render();
}
function actionPending(){
 return sending||selectingImage||stereoPending||deleting;
}
function renderComposer(asset=activeImage()){
 if(!current())return;
 const entry=draft();
 const selected=entry.useSelected?asset:null;
 const name=entry.file?.name||selected?.name;
 const url=entry.url||(selected&&'/media/'+selected.id+'?preview');
 $('#attachment').hidden=!url;
 const image=$('#attachment-preview');
 if(url&&image.getAttribute('src')!==url)image.src=url;
 if(!url&&image.hasAttribute('src'))image.removeAttribute('src');
 $('#attachment-name').textContent=name||'';
 $('#attachment-name').title=name||'';
 $('#attachment-kind').textContent=entry.file?'Attached image':'Selected image';
 $('#attach').disabled=sending||selectingImage;
 $('#detach-image').disabled=sending||selectingImage;
 $('#prompt').readOnly=sending;
 $('#send').disabled=state.busy||actionPending()||(!$('#prompt').value.trim()&&!url);
}
function render(){
 if(!state)return;
 if(!current()){
  sessionId=state.sessions[0].id;
  $('#prompt').value=drafts.get(sessionId)?.text||'';
 }
 localStorage.setItem('stereo-session',sessionId);
 const s=current();
 $('#workspace-title').textContent=s.title;$('#model-label').textContent=state.model.label;$('#model-status').textContent=sending?'Sending message…':state.model.message;$('.model-dot').classList.toggle('ready',state.model.phase==='ready');
 $('#new-chat').disabled=state.busy||actionPending();$('#stereo-badge').textContent=state.config.stereoEnabled?'Enabled':'Disabled';
 $('#stereo-badge').classList.toggle('pending',!state.config.stereoEnabled);
 const sessionsKey=JSON.stringify([sessionId,$('#search').value,state.busy,actionPending(),state.sessions.map(s=>[s.id,s.title])]);if(sessionsKey!==lastSessionsKey){lastSessionsKey=sessionsKey;const list=$('#sessions');const sessionScroll=list.scrollTop;list.replaceChildren();for(const item of state.sessions.filter(s=>s.title.toLowerCase().includes($('#search').value.toLowerCase()))){const row=el('div','session-row'+(s.id===item.id?' active':''));row.dataset.sessionId=item.id;const b=el('button','session'+(s.id===item.id?' active':''),'◦  '+item.title);b.title=item.title;b.onclick=()=>{if(state.busy||actionPending())return toast('Wait for the task or stop it before switching.');chooseSession(item.id);};const remove=el('button','session-delete');remove.title='Delete conversation';remove.setAttribute('aria-label','Delete conversation: '+item.title);remove.disabled=state.busy||actionPending();remove.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M9 6V4h6v2M5 6l1 14h12l1-14M10 10v6M14 10v6"/></svg>';remove.onclick=()=>openDeleteDialog(item.id);row.append(b,remove);list.append(row);}list.scrollTop=sessionScroll;}
 const tasks=state.tasks.filter(t=>t.sessionId===sessionId);const running=tasks.find(t=>t.status==='running');$('#working').hidden=!running;$('#working-text').textContent=running?.phase==='executing'?'Executing and checking image tools…':'Planning with the local model…';
 const assets=state.assets.filter(a=>a.sessionId===sessionId);const a=assets.find(a=>a.id===s.activeAssetId);$('#asset-count').textContent=assets.length;
 renderComposer(a);
 const key=JSON.stringify([sessionId,s.messages,tasks.map(t=>[t.id,t.status,t.steps]),assets.map(asset=>asset.id)]);
 if(key!==lastKey){
  lastKey=key;
  renderConversation(s.messages,tasks,running,assets);
 }
 $('#open-stereo').hidden=a?.type!=='image'||!state.config.stereoEnabled;
 const hasDraftImage=Boolean(draft().file);
 $('#open-stereo').disabled=state.busy||actionPending()||hasDraftImage;
 $('#open-stereo').title=hasDraftImage?'Send the attached image to use it for stereo generation.':'';
 $('#stereo-view-label').hidden=!a?.stereoJobId;
 $('#stereo-controls').hidden=$('#open-stereo').hidden&&$('#stereo-view-label').hidden;
 const view=$('#stereo-view');view.disabled=state.busy||actionPending();
 const availableViews=a?.stereoJobId?stereoViews(a,assets).map(asset=>asset.stereoFormat):[];
 for(const option of view.options){
  option.hidden=option.disabled=!availableViews.includes(option.value);
 }
 if(a?.stereoFormat&&!stereoPending)view.value=a.stereoFormat;
 if(a){let img=$('#preview-box img');if(!img){$('#preview-box').replaceChildren();img=el('img');img.alt='Active image version';img.tabIndex=0;img.setAttribute('role','button');img.setAttribute('aria-label','Open full-resolution image preview');img.onclick=()=>openImageViewer(img.dataset.id);img.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openImageViewer(img.dataset.id);}};$('#preview-box').append(img);}if(img.dataset.id!==a.id){img.src='/media/'+a.id+'?preview';img.dataset.id=a.id;}
 $('#asset-meta').replaceChildren(el('strong','',a.name),el('span','',`${a.width} × ${a.height} · ${a.format.toUpperCase()} · ${a.type.replaceAll('_',' ')}`));$('#asset-actions').hidden=false;$('#undo').disabled=!a.parentId||state.busy||actionPending();$('#download').href='/media/'+a.id+'?download';$('#download').download='';
 }else{if(!$('#preview-box .empty-preview')){const empty=el('div','empty-preview');empty.append(el('span','','▧'),el('strong','','Your canvas starts here'),el('p','','Images appear here after you send them.'));const b=el('button','','Attach image');b.onclick=()=>$('#file-input').click();empty.append(b);$('#preview-box').replaceChildren(empty);}$('#asset-meta').replaceChildren();$('#asset-actions').hidden=true;}
 renderVersions(s,assets);
}
function renderVersions(session,assets){
 const key=JSON.stringify([sessionId,session.activeAssetId,state.busy,actionPending(),assets.map(asset=>asset.id)]);
 if(key===lastVersionsKey)return;
 lastVersionsKey=key;
 const list=$('#versions');
 const scroll=list.scrollTop;
 list.replaceChildren();
 if(!assets.length)list.append(el('p','muted','Sent images and edits appear here.'));
 for(const asset of [...assets].reverse()){
  const active=asset.id===session.activeAssetId;
  const row=el('div','version-entry'+(active?' active':''));
  const button=el('button','version'+(active?' active':''));
  button.type='button';
  button.dataset.assetId=asset.id;
  button.setAttribute('aria-pressed',String(active));
  button.title='Use in chat: '+asset.name;
  button.disabled=state.busy||actionPending();
  const image=el('img');
  image.src='/media/'+asset.id+'?preview';
  image.alt='';
  const info=el('div');
  const kind=asset.operation?.tool==='import_image'?'Upload':asset.stereoFormat?'Stereo':'Edit';
  info.append(el('strong','',asset.name),el('small','',kind+' · '+asset.width+' × '+asset.height));
  button.append(image,info);
  button.onclick=()=>selectAsset(asset);
  const preview=el('button','version-preview','↗');
  preview.type='button';
  preview.title='Open image preview';
  preview.setAttribute('aria-label','Preview '+asset.name);
  preview.onclick=()=>openImageViewer(asset.id);
  row.append(button,preview);
  list.append(row);
 }
 list.scrollTop=scroll;
}
const stereoLabels={left:'Left view',right:'Right view',baseline_right:'Original right',sbs:'Side by side',anaglyph:'Red/cyan'};
function stereoViews(asset,assets){
 if(!asset.stereoJobId)return [asset];
 const group=assets.filter(item=>item.sessionId===asset.sessionId&&item.stereoJobId===asset.stereoJobId&&item.operation?.tool==='generate_stereo');
 const views=Object.keys(stereoLabels).map(format=>format===asset.stereoFormat?asset:group.find(item=>item.stereoFormat===format)).filter(Boolean);
 return views.length?views:[asset];
}
function stereoCards(task,assets){
 const groups=new Map();
 for(const step of task?.steps||[]){
  if(step.status!=='completed'||!['generate_stereo','select_stereo'].includes(step.tool))continue;
  const asset=assets.find(item=>item.id===step.assetId);
  if(asset)groups.set(asset.stereoJobId||asset.id,asset);
 }
 return Array.from(groups.values(),asset=>{
  const card=el('div','stereo-result');
  const views=el('div','stereo-result-views');
  for(const view of stereoViews(asset,assets)){
   const label=stereoLabels[view.stereoFormat]||view.name;
   const button=el('button','stereo-result-view'+(view.id===asset.id?' selected':''));
   button.type='button';
   button.dataset.assetId=view.id;
   button.setAttribute('aria-label','Preview '+label);
   const thumbnail=el('img');
   thumbnail.src='/media/'+view.id+'?preview';
   thumbnail.alt='';
   thumbnail.loading='lazy';
   button.append(thumbnail,el('span','',label));
   button.onclick=()=>openImageViewer(view.id);
   views.append(button);
  }
  card.append(views);
  return card;
 });
}
function renderConversation(messages,tasks,running,assets){
 const conversation=$('#conversation');
 const oldTop=conversation.scrollTop;
 const shouldFollow=scrollSessionId!==sessionId||followConversation;
 scrollSessionId=sessionId;
 const timeline=[...messages];
 const linkedTasks=new Set(messages.map(message=>message.taskId));
 for(const task of tasks){
  if(task.status!=='completed'||task.request!=='Direct action: generate_stereo'||linkedTasks.has(task.id))continue;
  const time=task.finishedAt||task.createdAt;
  const position=timeline.findIndex(message=>message.time&&message.time>time);
  const message={role:'assistant',content:'Stereo views are ready.',taskId:task.id,time};
  timeline.splice(position===-1?timeline.length:position,0,message);
 }
 $('#welcome').hidden=timeline.length>0;
 const list=$('#messages');
 list.replaceChildren();
 for(const message of timeline){
  const box=el('div','message '+message.role);
  box.setAttribute('aria-label',message.role==='user'?'Your message':'Assistant response');
  const image=message.role==='user'?assets.find(asset=>asset.id===message.assetId):null;
  if(image)box.append(messageImage(image));
  if(message.content)box.append(messageContent(message));
  const task=tasks.find(item=>item.id===message.taskId);
  if(task?.steps?.length)box.append(stepList(task.steps));
  box.append(...stereoCards(task,assets));
  list.append(box);
 }
 if(running?.steps.length)list.append(stepList(running.steps));
 conversation.scrollTop=shouldFollow?conversation.scrollHeight:oldTop;
}
function messageImage(asset){
 const button=el('button','message-image');
 button.type='button';
 button.dataset.assetId=asset.id;
 button.setAttribute('aria-label','Preview '+asset.name);
 const image=el('img');
 image.src='/media/'+asset.id+'?preview';
 image.alt=asset.name;
 const scale=Math.min(1,300/asset.width,240/asset.height);
 image.width=Math.max(1,Math.round(asset.width*scale));
 image.height=Math.max(1,Math.round(asset.height*scale));
 button.append(image);
 button.onclick=()=>openImageViewer(asset.id);
 return button;
}
function stepList(steps){const box=el('div','steps');for(const s of steps){const row=el('div','step '+s.status,`${s.status==='completed'?'✓':s.status==='failed'?'!':'◌'}  ${s.tool.replaceAll('_',' ')}`);row.append(el('small','',s.error||s.summary||JSON.stringify(s.params)));box.append(row);}return box;}
async function refresh(){
 const request=++stateRequest;
 try{
  const next=await api('state');
  if(request<lastAppliedStateRequest)return;
  lastAppliedStateRequest=request;
  state=next;
  render();
 }catch(error){
  if(request>=lastAppliedStateRequest)$('#model-status').textContent='Application service unavailable.';
 }
}
function stageImage(file){
 if(!file||!current()||sending||selectingImage)return;
 if(!['image/png','image/jpeg','image/webp'].includes(file.type)&&!/\.(png|jpe?g|webp)$/i.test(file.name)){
  return toast('Choose a PNG, JPEG or WebP image.');
 }
 if(!file.size||file.size>20*1024*1024)return toast('Choose an image up to 20 MB.');
 const entry=draft();
 clearDraftFile(entry);
 entry.file=file;
 entry.url=URL.createObjectURL(file);
 render();
 $('#prompt').focus();
}
async function selectAsset(asset){
 if(state.busy||actionPending())return;
 const entry=draft();
 selectingImage=true;
 render();
 try{
  await api('active',{sessionId,assetId:asset.id});
  clearDraftFile(entry);
  entry.useSelected=true;
  await refresh();
  $('#prompt').focus();
 }catch(error){toast(error.message);}
 finally{selectingImage=false;render();}
}
function attachmentData(file){
 return new Promise((resolve,reject)=>{
  const reader=new FileReader();
  reader.onload=()=>resolve(reader.result.split(',',2)[1]);
  reader.onerror=()=>reject(new Error('Could not read the attached image.'));
  reader.readAsDataURL(file);
 });
}
$('#detach-image').onclick=()=>{
 const entry=draft();
 clearDraftFile(entry);
 entry.useSelected=false;
 render();
 $('#prompt').focus();
};
$('#prompt').oninput=()=>{
 if(!current())return;
 draft().text=$('#prompt').value;
 renderComposer();
};
$('#composer').onsubmit=async event=>{
 event.preventDefault();
 if(!current()||state.busy||actionPending())return;
 const entry=draft();
 const text=$('#prompt').value.trim();
 const assetId=entry.useSelected?activeImage()?.id:null;
 if(!text&&!entry.file&&!assetId)return;
 if(!state.capabilities?.chatImageAttachments)return toast('Fully close and reopen StereoAgent Studio to send messages from the updated composer.');
 sending=true;
 render();
 try{
  const payload={sessionId,text};
  if(entry.file)payload.attachment={name:entry.file.name,base64:await attachmentData(entry.file)};
  else payload.assetId=assetId??null;
  await api('chat',payload);
  if(entry.file)entry.useSelected=true;
  clearDraftFile(entry);
  entry.text=$('#prompt').value='';
  followConversation=true;
  await refresh();
 }catch(error){toast(error.message);}
 finally{sending=false;render();}
};
$('#prompt').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('#composer').requestSubmit();}});
$('#new-chat').onclick=async()=>{try{const s=await api('sessions',{});await refresh();chooseSession(s.id);}catch(e){toast(e.message);}};$('#search').oninput=render;
$('#attach').onclick=()=>$('#file-input').click();
$('#upload-preview').onclick=()=>$('#file-input').click();
$('#file-input').onchange=event=>{
 const file=event.target.files[0];
 event.target.value='';
 stageImage(file);
};
document.addEventListener('paste',event=>{
 const clipboard=event.clipboardData;
 if(!clipboard||$('dialog[open]'))return;
 const item=[...clipboard.items].find(item=>item.kind==='file'&&item.type.startsWith('image/'));
 const file=item?.getAsFile()||clipboard.files[0];
 if(file){event.preventDefault();stageImage(file);}
});
document.addEventListener('dragover',event=>{
 if(event.dataTransfer.types.includes('Files'))event.preventDefault();
});
document.addEventListener('drop',event=>{
 if(event.dataTransfer.files.length){
  event.preventDefault();
  stageImage(event.dataTransfer.files[0]);
 }
});
$('#undo').onclick=async()=>{try{await api('tool',{sessionId,action:{tool:'undo',params:{}}});await refresh();}catch(e){toast(e.message);}};
$('#open-stereo').onclick=()=>{
 const asset=activeImage();
 if(!asset||asset.type!=='image')return;
 stereoSource=asset.id;
 $('#stereo-detail-label').hidden=!state.capabilities?.stereoDetailModes;
 if(!state.capabilities?.chatImageAttachments)return toast('Fully close and reopen StereoAgent Studio to use the updated stereo tools.');
 const needsFraming=asset.width*256!==asset.height*448;
 $('#stereo-fit').value='pad';
 $('#stereo-fit').onchange();
 $('#stereo-fit-label').hidden=!needsFraming;
 $('#stereo-fit-note').hidden=!needsFraming;
 $('#stereo-dialog').showModal();
};
$('#stereo-fit').onchange=()=>{
 $('#stereo-fit-note').textContent=$('#stereo-fit').value==='pad'?
  'Fit adds borders to keep the whole image in view.':'Center crop trims the edges of the generated views.';
};
$('#stereo-close').onclick=()=>$('#stereo-dialog').close();
async function stereoAction(action,success){
 if(actionPending()||state.busy)return;
 stereoPending=true;render();
 try{
  await api('tool',{sessionId,action});
  if(action.tool==='select_stereo'&&!draft().file)draft().useSelected=true;
  toast(success);
 }
 catch(error){toast(error.message);}
 finally{await refresh();stereoPending=false;render();}
}
$('#stereo-form').onsubmit=event=>{
 event.preventDefault();
 $('#stereo-dialog').close();
 followConversation=true;
 stereoAction({tool:'generate_stereo',source:stereoSource,params:{
  resolution:$('#stereo-resolution').value,strength:$('#stereo-strength').valueAsNumber,
  ...(state.capabilities?.stereoDetailModes?{postprocess:$('#stereo-detail').value}:{}),
  fit:$('#stereo-fit').value
 }},'Stereo views are ready to preview and export.');
};
$('#stereo-view').onchange=event=>{
 stereoAction({tool:'select_stereo',source:current().activeAssetId,params:{format:event.target.value}},'Stereo view selected.');
};
$('#cancel').onclick=async()=>{try{await api('cancel',{});await refresh();}catch(e){toast(e.message);}};
async function openDeleteDialog(id){if(state.busy||actionPending())return toast('Wait for the current task before deleting.');const target=state.sessions.find(s=>s.id===id);if(!target)return;deleteTargetId=id;$('#delete-target').textContent=target.title;$('#delete-error').hidden=true;$('#delete-confirm').disabled=true;$('#delete-dialog').showModal();try{const health=await api('health');if(deleteTargetId!==id||!$('#delete-dialog').open)return;if(health.features?.sessionDeletion!==true)throw new Error('The application backend is an older version. Fully close StereoAgent Studio and reopen start.vbs; refreshing the page does not update the backend. No conversation was deleted.');$('#delete-confirm').disabled=false;}catch(e){if(deleteTargetId===id){$('#delete-error').textContent=e.message;$('#delete-error').hidden=false;}}}
function closeDeleteDialog(){if(!deleting)$('#delete-dialog').close();}
$('#delete-cancel').onclick=closeDeleteDialog;$('#delete-close').onclick=closeDeleteDialog;
$('#delete-dialog').addEventListener('cancel',e=>{if(deleting)e.preventDefault();});
$('#delete-dialog').addEventListener('close',()=>{deleteTargetId=null;});
$('#delete-confirm').onclick=async()=>{
 if(!deleteTargetId||deleting)return;const id=deleteTargetId;
 if(state.busy||actionPending()){$('#delete-error').textContent='A task is running. Stop or finish it before deleting.';$('#delete-error').hidden=false;return;}
 deleting=true;$('#delete-confirm').disabled=true;$('#delete-cancel').disabled=true;$('#delete-close').disabled=true;
 try{const result=await api('sessions/delete',{sessionId:id,confirmed:true});clearDraftFile(drafts.get(id));drafts.delete(id);if(sessionId===id){sessionId=result.fallbackSessionId;$('#prompt').value=drafts.get(sessionId)?.text||'';localStorage.setItem('stereo-session',sessionId);lastKey='';followConversation=true;$('#search').value='';if($('#image-viewer').open)$('#image-viewer').close();}await refresh();$('#delete-dialog').close();toast('Conversation deleted.');}
 catch(e){$('#delete-error').textContent=e.message==='Endpoint not found.'?'The application backend is an older version. Fully close the app and reopen start.vbs, then try again. No conversation was deleted.':e.message;$('#delete-error').hidden=false;}
 finally{deleting=false;$('#delete-confirm').disabled=false;$('#delete-cancel').disabled=false;$('#delete-close').disabled=false;render();}
};
function settings(){ $('#model-select').value=state.config.model;$('#stereo-enabled').checked=state.config.stereoEnabled;$('#settings-state').textContent=state.model.message;$('#settings').showModal();}
$('#settings-button').onclick=settings;$('#model-chip').onclick=settings;
$('#load-model').onclick=async()=>{try{await api('model',{model:$('#model-select').value});await refresh();$('#settings-state').textContent='Loading selected local model…';}catch(e){toast(e.message);}};
$('#stop-model').onclick=async()=>{try{await api('model',{action:'stop'});await refresh();$('#settings-state').textContent='Model stopped. A new request will start it again.';}catch(e){toast(e.message);}};
$('#save-settings').onclick=async()=>{try{await api('settings',{stereoEnabled:$('#stereo-enabled').checked});await refresh();$('#settings-state').textContent='Stereo setting saved.';}catch(e){toast(e.message);}};
$('#inspector-toggle').onclick=()=>$('.app-shell').classList.toggle('hide-inspector');
document.querySelectorAll('[data-prompt]').forEach(button=>button.onclick=()=>{
 if(sending)return;
 $('#prompt').value=button.dataset.prompt;
 $('#prompt').oninput();
 $('#prompt').focus();
});
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();$('#new-chat').click();}});
$('#conversation').addEventListener('scroll',()=>{const c=$('#conversation');followConversation=c.scrollHeight-c.scrollTop-c.clientHeight<80;});
const viewer=$('#image-viewer'),viewerCanvas=$('#viewer-canvas'),viewerImage=$('#viewer-image');
let viewerViews=[],viewerIndex=0,viewerScale=1,viewerZoomChanged=false;
function initialViewerScale(asset){
 return Math.min(1,Math.max(1,viewerCanvas.clientWidth-40)/asset.width,Math.max(1,viewerCanvas.clientHeight-40)/asset.height);
}
function setViewerZoom(nextScale,point){
 const asset=viewerViews[viewerIndex];
 if(!asset)return;
 const minimum=Math.min(0.05,initialViewerScale(asset));
 const origin=point&&viewerImage.getBoundingClientRect();
 viewerScale=Math.max(minimum,Math.min(5,nextScale));
 viewerImage.style.width=Math.max(1,asset.width*viewerScale)+'px';
 viewerImage.style.height=Math.max(1,asset.height*viewerScale)+'px';
 $('#viewer-percent').textContent=Math.round(viewerScale*100)+'%';
 $('#viewer-minus').disabled=viewerScale<=minimum;
 $('#viewer-plus').disabled=viewerScale>=5;
 if(origin&&origin.width&&origin.height){
  const resized=viewerImage.getBoundingClientRect();
  const imageX=(point.clientX-origin.left)/origin.width;
  const imageY=(point.clientY-origin.top)/origin.height;
  viewerCanvas.scrollLeft+=resized.left+imageX*resized.width-point.clientX;
  viewerCanvas.scrollTop+=resized.top+imageY*resized.height-point.clientY;
 }else{
  viewerCanvas.scrollLeft=(viewerCanvas.scrollWidth-viewerCanvas.clientWidth)/2;
  viewerCanvas.scrollTop=(viewerCanvas.scrollHeight-viewerCanvas.clientHeight)/2;
 }
}
function displayViewerImage(){
 const asset=viewerViews[viewerIndex];
 const multi=viewerViews.length>1;
 $('#viewer-title').textContent=asset.name;
 $('#viewer-meta').textContent=asset.width+' × '+asset.height+' · '+asset.format.toUpperCase();
 $('#viewer-status').textContent=multi?[stereoLabels[asset.stereoFormat],(viewerIndex+1)+' / '+viewerViews.length].join(' · '):'';
 $('#viewer-prev').hidden=$('#viewer-next').hidden=!multi;
 viewerImage.alt=asset.name;
 viewerImage.src='/media/'+asset.id;
 $('#viewer-download').href='/media/'+asset.id+'?download';
 setViewerZoom(viewerZoomChanged?viewerScale:initialViewerScale(asset));
}
function openImageViewer(id){
 const asset=state?.assets.find(item=>item.id===id&&item.sessionId===sessionId);
 if(!asset)return;
 viewerViews=stereoViews(asset,state.assets);
 viewerIndex=viewerViews.findIndex(item=>item.id===asset.id);
 viewerZoomChanged=false;
 if(!viewer.open)viewer.showModal();
 displayViewerImage();
}
function moveViewer(direction){
 if(viewerViews.length<2)return;
 viewerIndex=(viewerIndex+direction+viewerViews.length)%viewerViews.length;
 displayViewerImage();
}
function adjustViewerZoom(factor,point){
 viewerZoomChanged=true;
 setViewerZoom(viewerScale*factor,point);
}
viewerImage.onerror=()=>{if(viewer.open)$('#viewer-status').textContent='Could not load this image.';};
viewerCanvas.addEventListener('wheel',event=>{
 if(!event.deltaY)return;
 event.preventDefault();
 const delta=event.deltaMode===1?event.deltaY*16:event.deltaY;
 adjustViewerZoom(Math.exp(-Math.max(-100,Math.min(100,delta))*0.0022),event);
},{passive:false});
viewer.addEventListener('keydown',event=>{
 if(viewerViews.length<2||!['ArrowLeft','ArrowRight'].includes(event.key))return;
 event.preventDefault();
 moveViewer(event.key==='ArrowLeft'?-1:1);
});
$('#viewer-close').onclick=()=>viewer.close();
$('#viewer-actual').onclick=()=>{viewerZoomChanged=true;setViewerZoom(1);};
$('#viewer-plus').onclick=()=>adjustViewerZoom(1.25);
$('#viewer-minus').onclick=()=>adjustViewerZoom(1/1.25);
$('#viewer-prev').onclick=()=>moveViewer(-1);
$('#viewer-next').onclick=()=>moveViewer(1);
$('#image-viewer').addEventListener('click',e=>{if(e.target!==e.currentTarget)return;const r=e.currentTarget.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.currentTarget.close();});
viewer.addEventListener('close',()=>{if(!viewer.open){viewerImage.removeAttribute('src');viewerViews=[];}});
refresh();setInterval(refresh,1400);
