const fs=require('node:fs');const path=require('node:path');const {randomUUID}=require('node:crypto');const {spawn}=require('node:child_process');
const STEREO_OUTPUTS={left:'left.png',right:'right.png',sbs:'side_by_side.png',anaglyph:'anaglyph.png'};
const RIGHT_VIEW_OUTPUTS=['right','anaglyph'];
const BASELINE_VIEW='baseline_right';
const SINGLE_STEREO_VIEWS=['stereo_left','stereo_right','stereo_baseline_right'];
const STEREO_POSTPROCESS={
  legacy_high_frequency:'Legacy high-frequency detail compensation',
  appearance_multiband:'Appearance-aligned detail compensation',
  baseline:'No detail compensation',
};
const ALLOWED={crop_image:['left','top','right','bottom'],resize_image:['width','height'],adjust_color:['saturation','brightness','contrast'],rotate_image:['degrees'],export_image:['format'],inspect_image:[],undo:[],generate_stereo:['strength','resolution','format','fit','postprocess'],select_stereo:['format']};
function validateAction(a){
  if(!a||!Object.hasOwn(ALLOWED,a.tool))throw new Error('Unknown or unsupported tool.');
  if(!a.params||Array.isArray(a.params)||typeof a.params!=='object')throw new Error('Tool params must be an object.');
  if(Object.keys(a.params).some(k=>!ALLOWED[a.tool].includes(k)))throw new Error('Unsupported tool parameter.');
  if(a.source!==undefined&&typeof a.source!=='string')throw new Error('Source must be an image version ID.');
  return a;
}
function runPython(exe,script,request,signal){return new Promise((resolve,reject)=>{
  const child=spawn(exe,['-IB',script],{windowsHide:true,stdio:['pipe','pipe','pipe']});let out='',err='';let settled=false;
  const timer=setTimeout(()=>{child.kill();finish(new Error('Image operation timed out.'));},60000);
  const abort=()=>{child.kill();finish(new Error('Task cancelled.'));};
  function finish(error,data){if(settled)return;settled=true;clearTimeout(timer);signal?.removeEventListener('abort',abort);error?reject(error):resolve(data);}
  signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted){abort();return;}
  child.stdout.on('data',d=>out+=d);child.stderr.on('data',d=>err+=d);child.on('error',e=>finish(e));child.on('close',()=>{try{const result=JSON.parse(out);if(!result.ok)finish(new Error(result.error));else finish(null,result);}catch{finish(new Error(err.slice(-500)||'Image worker returned invalid output.'));}});
  child.stdin.on('error',()=>{});child.stdin.end(JSON.stringify(request));
});}
class Tools{
  constructor(root,config,store,model){Object.assign(this,{root,config,store,model});}
  async import(sessionId,buffer,name){
    if(buffer.length>20*1024*1024)throw new Error('Maximum upload size is 20 MB.');
    const dir=path.join(this.store.root,'artifacts');fs.mkdirSync(dir,{recursive:true});const raw=path.join(dir,randomUUID()+'.upload');const target=path.join(dir,randomUUID()+'.png');fs.writeFileSync(raw,buffer);
    let result;try{result=await runPython(this.config.python,path.join(this.root,'server/image_worker.py'),{tool:'import_image',source:raw,target});}finally{fs.unlinkSync(raw);}
    return this.store.addAsset(sessionId,{name:path.basename(name||'Uploaded image'),type:'image',file:target,...result,parentId:null,operation:{tool:'import_image',params:{}}});
  }
  async execute(sessionId,action,signal){
    validateAction(action);signal?.throwIfAborted();const s=this.store.session(sessionId);const a=this.store.asset(action.source&&action.source!=='current'?action.source:s.activeAssetId,sessionId);
    if(action.tool==='inspect_image')return {summary:`${a.width} × ${a.height} · ${a.type} · ${a.format}`,asset:a};
    if(action.tool==='undo'){
      if(!a.parentId)throw new Error('This image has no parent version.');s.activeAssetId=a.parentId;this.store.save();return {summary:'Restored previous image version.',asset:this.store.asset(a.parentId,sessionId)};
    }
    if(action.tool==='generate_stereo')return this.stereo(sessionId,a,action.params,signal);
    if(action.tool==='select_stereo'){
      const {format}=action.params;
      if(!Object.hasOwn(STEREO_OUTPUTS,format)&&format!==BASELINE_VIEW)throw new Error('Unsupported stereo format.');
      if(!a.stereoJobId)throw new Error('Select an image from a stereo generation first.');
      const asset=this.store.db.assets.find(item=>item.sessionId===sessionId&&item.stereoJobId===a.stereoJobId&&item.stereoFormat===format&&item.operation?.tool==='generate_stereo');
      if(!asset)throw new Error('Stereo output is unavailable.');
      s.activeAssetId=asset.id;
      this.store.save();
      return {asset,summary:format===BASELINE_VIEW?'Selected the original right view.':'Selected the existing stereo '+format+' image.'};
    }
    const exporting=action.tool==='export_image';
    if(!exporting&&a.type!=='image'&&!SINGLE_STEREO_VIEWS.includes(a.type)){
      throw new Error('Select a left or right view in Workspace assets before editing a combined stereo image.');
    }
    const ext=exporting?(action.params.format||'png').toLowerCase():'png';if(!['png','jpg','webp'].includes(ext))throw new Error('Unsupported format.');
    const target=path.join(this.store.root,'artifacts',randomUUID()+'.'+ext);
    const result=await runPython(this.config.python,path.join(this.root,'server/image_worker.py'),{tool:action.tool,source:a.file,target,params:action.params},signal);
    const stereoLineage=exporting&&a.stereoJobId?{stereoJobId:a.stereoJobId,stereoFormat:a.stereoFormat}:{};
    const asset=this.store.addAsset(sessionId,{...result,...stereoLineage,type:exporting?a.type:'image',name:action.tool.replaceAll('_',' ')+' · '+a.name,file:target,parentId:a.id,operation:action});
    return {asset,summary:`${action.tool} completed · ${asset.width} × ${asset.height}`,checks:result.checks};
  }
  async stereo(sessionId,a,p,signal){
    if(!this.config.stereoEnabled)throw new Error('Stereo execution is not enabled. Enable the bundled stereo runtime in Settings first.');
    if(a.type!=='image')throw new Error('Stereo conversion requires a mono image source.');
    const {strength=4.8,resolution='preview',format='anaglyph',fit='pad',postprocess:requestedPostprocess='legacy_high_frequency'}=p;
    if(!Number.isFinite(strength)||strength<0.5||strength>8)throw new Error('Stereo strength must be 0.5–8.');
    if(!['preview','final'].includes(resolution))throw new Error('Resolution must be preview or final.');
    if(!Object.hasOwn(STEREO_OUTPUTS,format))throw new Error('Unsupported stereo format.');
    if(!['pad','strict','center_crop'].includes(fit))throw new Error('Unsupported stereo source fitting mode.');
    if(typeof requestedPostprocess!=='string'||!Object.hasOwn(STEREO_POSTPROCESS,requestedPostprocess))throw new Error('Unsupported detail compensation option.');
    const rightViewRequest=format==='right';
    const postprocess=rightViewRequest?'appearance_multiband':requestedPostprocess;
    const [w,h]=resolution==='final'?[896,512]:[448,256];
    const needsFraming=a.width*h!==a.height*w;
    if(fit==='strict'&&needsFraming)throw new Error('Choose Fit whole image or Center crop to 7:4. The source has a different aspect ratio.');

    const {stereoRoot,stereoPython,stereoBackend='pytorch'}=this.config;
    const args=['-IB',path.join(stereoRoot,'scripts/run_mono2stereo_tensorrt_image.py')];
    const engine=path.join(stereoRoot,`assets/engines/mono2stereo_${w}x${h}_fp16.plan`);
    const required=[stereoPython,args[1],path.join(stereoRoot,'assets/weights/mono2stereo_runtime_fp16.pt')];
    if(stereoBackend==='tensorrt')required.push(engine);
    if(!required.every(file=>fs.existsSync(file)))throw new Error('Stereo runtime files are missing. Check the extracted package.');
    if(!['pytorch','tensorrt'].includes(stereoBackend))throw new Error('Unsupported stereo backend.');

    await this.model.stop();
    signal?.throwIfAborted();
    const stereoJobId=randomUUID();
    const output=path.join(this.store.root,'stereo',stereoJobId);
    fs.mkdirSync(output,{recursive:true});
    args.push('--input-image',a.file,'--output',output,'--width',String(w),'--height',String(h),
      '--viewpoint-scale',String(strength),'--backend',stereoBackend,'--engine',engine,
      '--postprocess',postprocess,'--fit',fit);
    if(rightViewRequest)args.push('--right-pair');
    await runStereo(stereoPython,args,stereoRoot,output,signal);
    const report=JSON.parse(fs.readFileSync(path.join(output,'summary.json'),'utf8'));
    if(report.postprocess?.method!==postprocess)throw new Error('Stereo runtime did not report the requested detail compensation option.');
    if(report.fit!==fit)throw new Error('Stereo runtime did not report the requested image framing.');
    const outputFiles=rightViewRequest?RIGHT_VIEW_OUTPUTS.map(view=>[view,STEREO_OUTPUTS[view]]):Object.entries(STEREO_OUTPUTS);
    if(!rightViewRequest&&postprocess!=='baseline')outputFiles.push([BASELINE_VIEW,'right_baseline.png']);

    const targets=[];
    try{
      const assets=[];
      for(const [stereoFormat,file] of outputFiles){
        const target=path.join(this.store.root,'artifacts',randomUUID()+'.png');
        targets.push(target,target.replace(/\.png$/,'.preview.jpg'));
        const result=await runPython(this.config.python,path.join(this.root,'server/image_worker.py'),
          {tool:'import_image',source:path.join(output,file),target},signal);
        if(result.width!==(stereoFormat==='sbs'?w*2:w)||result.height!==h){
          throw new Error('Unexpected stereo output dimensions.');
        }
        const label=stereoFormat===BASELINE_VIEW?'Original right':`Stereo ${stereoFormat}`;
        assets.push({...result,name:`${label} · ${a.name}`,type:'stereo_'+stereoFormat,file:target,
          parentId:a.id,stereoFormat,stereoJobId,operation:{tool:'generate_stereo',params:{strength,resolution,fit,format:stereoFormat,postprocess}}});
      }
      signal?.throwIfAborted();
      const asset=this.store.addStereoOutputs(sessionId,assets,format);
      const summary=rightViewRequest?'The compensated right view and red/cyan anaglyph are ready.':
        postprocess==='baseline'?'Stereo views are ready without detail compensation.':
        `Stereo views are ready. Applied ${STEREO_POSTPROCESS[postprocess].toLowerCase()}.`;
      const framingNote=needsFraming&&fit==='pad'?' Borders keep the full source image in view.':'';
      return {asset,summary:summary+framingNote};
    }catch(error){
      for(const file of targets)try{fs.rmSync(file,{force:true});}catch{}
      throw error;
    }
  }
}
function runStereo(exe,args,cwd,output,signal){
  const log=path.join(output,'adapter.log');
  const fd=fs.openSync(log,'w');
  return new Promise((resolve,reject)=>{
    let child;
    try{
      child=spawn(exe,args,{cwd,windowsHide:true,stdio:['ignore',fd,fd],
        env:{...process.env,HF_HUB_OFFLINE:'1'}});
    }finally{fs.closeSync(fd);}
    const abort=()=>child.kill();
    let timedOut=false,spawnError;
    const timer=setTimeout(()=>{timedOut=true;child.kill();},600000);
    child.on('error',error=>{spawnError=error;});
    child.on('close',code=>{
      clearTimeout(timer);
      signal?.removeEventListener('abort',abort);
      if(signal?.aborted)return reject(new Error('Stereo task cancelled.'));
      if(timedOut)return reject(new Error('Stereo generation timed out.'));
      if(spawnError)return reject(spawnError);
      if(code===0)return resolve();
      const tail=fs.readFileSync(log,'utf8').trim().split(/\r?\n/).at(-1)?.slice(0,300);
      reject(new Error(`Stereo generation failed. ${tail||''} See ${path.relative(cwd,log)}.`));
    });
    signal?.addEventListener('abort',abort,{once:true});
    if(signal?.aborted)abort();
  });
}
module.exports={Tools,validateAction,runPython,ALLOWED,STEREO_POSTPROCESS};
