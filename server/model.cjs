const fs=require('node:fs');
const path=require('node:path');
const net=require('node:net');const {randomUUID}=require('node:crypto');
const {spawn}=require('node:child_process');
const {repetitionReason}=require('./generation.cjs');
const {STEREO_POSTPROCESS}=require('./tools.cjs');
const MODELS={
  '2b':{label:'Qwen3-VL · 2B Q4',model:'Qwen3VL-2B-Instruct-Q4_K_M.gguf',projector:'mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf'},
  '8b':{label:'Qwen3-VL · 8B Q4',model:'Qwen3-VL-8B-Instruct-Q4_K_M.gguf',projector:'mmproj-Qwen3-VL-8B-Instruct-F16.gguf'}
};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const PLAN_SCHEMA={type:'object',properties:{reply:{type:'string'},actions:{type:'array',maxItems:6,items:{type:'object',properties:{tool:{type:'string',enum:['inspect_image','crop_image','resize_image','adjust_color','rotate_image','export_image','undo','generate_stereo','select_stereo']},source:{type:'string'},params:{type:'object',properties:{left:{type:'integer'},right:{type:'integer'},top:{type:'integer'},bottom:{type:'integer'},width:{type:'integer'},height:{type:'integer'},saturation:{type:'number'},brightness:{type:'number'},contrast:{type:'number'},degrees:{type:'number'},format:{type:'string'},strength:{type:'number'},resolution:{type:'string'},fit:{type:'string',enum:['pad','center_crop','strict']},postprocess:{type:'string',enum:Object.keys(STEREO_POSTPROCESS)}},additionalProperties:false}},required:['tool','source','params'],additionalProperties:false}}},required:['reply','actions'],additionalProperties:false};
class Model {
  constructor(root,config){this.root=root;this.config=config;this.child=null;this.state={phase:'stopped',label:MODELS[config.model].label,message:'Local model is stopped.'};this.base=`http://127.0.0.1:${config.modelPort}`;this.timer=null;this.key=randomUUID();}
  async start(){
    if(this.child)return;const m=MODELS[this.config.model];
    const exe=path.join(this.root,'runtime/llama/llama-server.exe');
    const files=[exe,path.join(this.root,'models',m.model),path.join(this.root,'models',m.projector)];
    if(!files.every(f=>fs.existsSync(f)))throw new Error('Model or runtime missing. See README.md.');
    await new Promise((resolve,reject)=>{const s=net.createServer();s.once('error',()=>reject(new Error('Model port is occupied; this application will not attach to another process.')));s.listen(this.config.modelPort,'127.0.0.1',()=>s.close(resolve));});
    this.state={phase:'loading',label:m.label,message:'Loading local model…'};
    const log=fs.createWriteStream(path.join(this.root,'logs/model.log'),{flags:'a'});
    log.write(`\n=== StereoAgent ${new Date().toISOString()} ${m.label} ===\n`);
    const child=spawn(exe,['--model',files[1],'--mmproj',files[2],'--alias','stereo-agent-local','--api-key',this.key,'--host','127.0.0.1','--port',String(this.config.modelPort),'--ctx-size','8192','--parallel','1','--n-gpu-layers','99','--batch-size','256','--ubatch-size','128','--no-mmproj-offload','--jinja','--no-webui'],{cwd:path.dirname(exe),windowsHide:true,env:{...process.env,GGML_VK_VISIBLE_DEVICES:'0'},stdio:['ignore','pipe','pipe']});
    this.child=child;child.stdout.pipe(log,{end:false});child.stderr.pipe(log,{end:false});
    child.on('error',e=>{this.state.phase='error';this.state.message=e.message;});
    child.once('exit',code=>{if(this.child===child){this.child=null;this.state.phase='stopped';this.state.message=`Model stopped (${code}).`;}clearInterval(this.timer);log.end();});
    this.timer=setInterval(async()=>{if(this.child!==child)return;try{const r=await fetch(this.base+'/health',{headers:{Authorization:'Bearer '+this.key},signal:AbortSignal.timeout(1200)});if(r.ok){this.state.phase='ready';this.state.message='Local inference · no cloud API';}}catch{}},1500);
  }
  async stop(){clearInterval(this.timer);const child=this.child;if(!child)return;this.child=null;await new Promise(resolve=>{child.once('exit',resolve);child.kill();setTimeout(resolve,8000).unref();});this.state.phase='stopped';this.state.message='Local model is stopped.';}
  async ready(signal){if(!this.child)await this.start();for(let i=0;i<150;i++){signal?.throwIfAborted();if(this.state.phase==='ready')return;if(!this.child)throw new Error(this.state.message);await sleep(1000);}throw new Error('Model startup timed out. Inspect logs/model.log.');}
  async complete(messages,signal){
    await this.ready(signal);
    const response=await fetch(this.base+'/v1/chat/completions',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+this.key},signal:AbortSignal.any([signal,AbortSignal.timeout(180000)].filter(Boolean)),body:JSON.stringify({model:'stereo-agent-local',messages,temperature:0.1,top_p:0.8,top_k:20,min_p:0,presence_penalty:0.1,max_tokens:2800,stream:false,response_format:{type:'json_schema',json_schema:{name:'image_action_plan',strict:true,schema:PLAN_SCHEMA}}})});
    if(!response.ok)throw new Error('Model request failed: '+(await response.text()).slice(0,500));
    const result=await response.json();if(result.choices?.[0]?.finish_reason==='length')throw new Error('Model response exceeded token budget; simplify the request.');
    const value=result.choices?.[0]?.message?.content||'';if(repetitionReason(value))throw new Error('Repeated model output detected; no tools executed.');return value;
  }
}
module.exports={Model,MODELS};
