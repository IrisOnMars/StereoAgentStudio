const http=require('node:http');const fs=require('node:fs');const path=require('node:path');
const {Store}=require('./store.cjs');const {Model,MODELS}=require('./model.cjs');const {Tools}=require('./tools.cjs');const {Agent}=require('./agent.cjs');
const ROOT=path.resolve(__dirname,'..');
function resolveBundledPaths(config){
  for(const key of ['python','stereoPython','stereoRoot']){
    if(typeof config[key]==='string'&&!path.isAbsolute(config[key]))config[key]=path.resolve(ROOT,config[key]);
  }
  return config;
}
const MIME={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.svg':'image/svg+xml'};
async function startServer(options={}){
  const config=resolveBundledPaths({...JSON.parse(fs.readFileSync(path.join(ROOT,'config.json'),'utf8')),...options});
  fs.mkdirSync(path.join(ROOT,'logs'),{recursive:true});
  const store=new Store(options.dataRoot||path.join(ROOT,'data'));const model=new Model(ROOT,config);const tools=new Tools(ROOT,config,store,model);const agent=new Agent(store,model,tools);
  let controlBusy=false,directController;
  const json=(res,status,value)=>{res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});res.end(JSON.stringify(value));};
  const body=req=>new Promise((resolve,reject)=>{let length=0,chunks=[];req.on('data',d=>{length+=d.length;if(length>29*1024*1024){reject(new Error('Request too large.'));req.destroy();}else chunks.push(d);});req.on('end',()=>{try{resolve(JSON.parse(Buffer.concat(chunks).toString()||'{}'));}catch{reject(new Error('Invalid JSON request.'));}});req.on('error',reject);});
  const server=http.createServer(async(req,res)=>{
    try{
      if(req.headers.host!==`127.0.0.1:${config.port}`&&req.headers.host!==`localhost:${config.port}`)return json(res,403,{error:'Invalid host.'});
      const origin=req.headers.origin;if(origin&&!['http://127.0.0.1:'+config.port,'http://localhost:'+config.port].includes(origin))return json(res,403,{error:'Cross-origin requests are not accepted.'});
      res.setHeader('X-Content-Type-Options','nosniff');res.setHeader('Content-Security-Policy',"default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'");
      const url=new URL(req.url,`http://127.0.0.1:${config.port}`);const route=url.pathname;
      if(req.method==='GET'&&route==='/api/state')return json(res,200,{...store.view(),model:model.state,busy:!!agent.running||controlBusy,models:MODELS,config:{model:config.model,stereoEnabled:config.stereoEnabled},capabilities:{imageEditing:true,stereoAdapter:true,stereoDetailModes:true,chatImageAttachments:true,stereoEnabled:config.stereoEnabled,videoEditing:false,automaticVisualRecovery:false}});
      if(req.method==='GET'&&route==='/api/health')return json(res,200,{ok:true,name:'StereoAgent Studio',apiVersion:6,features:{sessionDeletion:true,runtimeClock:true,webSearch:false,chatImageAttachments:true}});
      if(req.method==='POST'){
        const input=await body(req);
        if(route==='/api/cancel'){agent.cancel();directController?.abort();return json(res,200,{ok:true});}
        if(agent.running||controlBusy)return json(res,409,{error:'Another task or model operation is running.'});
        if(route==='/api/sessions')return json(res,201,store.createSession());
        if(route==='/api/sessions/delete'){
          if(input.confirmed!==true)return json(res,400,{error:'Explicit confirmation is required to delete a workspace.'});
          return json(res,200,store.removeSession(input.sessionId));
        }
        if(route==='/api/chat'){
          const message=input.text??'';
          if(typeof message!=='string'||message.length>5000)throw new Error('Enter a request up to 5,000 characters.');
          if(input.attachment===undefined)return json(res,202,await agent.run(input.sessionId,message,input.assetId));
          store.session(input.sessionId);
          if(input.assetId!==undefined)throw new Error('Choose one image for this message.');
          const {base64,name}=input.attachment??{};
          if(typeof base64!=='string'||!base64.length||(name!==undefined&&typeof name!=='string'))throw new Error('Choose a valid image attachment.');
          controlBusy=true;
          try{
            const asset=await tools.import(input.sessionId,Buffer.from(base64,'base64'),name);
            return json(res,202,await agent.run(input.sessionId,message,asset.id));
          }finally{controlBusy=false;}
        }
        if(route==='/api/upload'){
          store.session(input.sessionId);if(typeof input.base64!=='string'||!input.base64.length)throw new Error('Empty upload.');
          controlBusy=true;try{return json(res,201,await tools.import(input.sessionId,Buffer.from(input.base64,'base64'),input.name));}finally{controlBusy=false;}
        }
        if(route==='/api/active'){store.asset(input.assetId,input.sessionId);store.session(input.sessionId).activeAssetId=input.assetId;store.save();return json(res,200,{ok:true});}
        if(route==='/api/tool'){
          store.session(input.sessionId);
          const controller=new AbortController();
          directController=controller;controlBusy=true;
          const task={id:require('node:crypto').randomUUID(),sessionId:input.sessionId,request:'Direct action: '+input.action?.tool,status:'running',phase:'executing',steps:[],createdAt:new Date().toISOString()};
          try{
            store.db.tasks.push(task);store.save();
            const result=await tools.execute(input.sessionId,input.action,controller.signal);
            task.status='completed';task.steps=[{tool:input.action.tool,status:'completed',summary:result.summary,assetId:result.asset?.id}];
            return json(res,200,{ok:true,asset:result.asset?.id});
          }catch(e){task.status=controller.signal.aborted?'cancelled':'failed';task.error=e.message;throw e;}
          finally{directController=null;controlBusy=false;task.finishedAt=new Date().toISOString();store.save();}
        }
        if(route==='/api/model'){
          controlBusy=true;try{if(input.action==='stop')await model.stop();else if(input.action==='start')await model.start();else if(input.model&&MODELS[input.model]){await model.stop();config.model=input.model;model.state.label=MODELS[input.model].label;const saved=JSON.parse(fs.readFileSync(path.join(ROOT,'config.json'),'utf8'));saved.model=input.model;fs.writeFileSync(path.join(ROOT,'config.json'),JSON.stringify(saved,null,2));await model.start();}else throw new Error('Unsupported model action.');return json(res,200,{ok:true});}finally{controlBusy=false;}
        }
        if(route==='/api/settings'){config.stereoEnabled=input.stereoEnabled===true;const saved=JSON.parse(fs.readFileSync(path.join(ROOT,'config.json'),'utf8'));saved.stereoEnabled=config.stereoEnabled;fs.writeFileSync(path.join(ROOT,'config.json'),JSON.stringify(saved,null,2));return json(res,200,{ok:true});}
        return json(res,404,{error:'Endpoint not found.'});
      }
      if(req.method==='GET'&&route.startsWith('/media/')){
        const id=route.slice(7);const a=store.db.assets.find(a=>a.id===id);if(!a)return json(res,404,{error:'Image not found.'});const file=url.searchParams.has('preview')?a.thumbnail:a.file;
        if(url.searchParams.has('download'))res.setHeader('Content-Disposition',`attachment; filename="stereo-agent-${a.id}.${a.format}"`);
        res.writeHead(200,{'Content-Type':MIME[path.extname(file)]||'application/octet-stream','Cache-Control':'no-store'});return fs.createReadStream(file).pipe(res);
      }
      const files={'/':'index.html','/app.js':'app.js','/styles.css':'styles.css','/vendor/marked.umd.js':'vendor/marked.umd.js','/vendor/purify.min.js':'vendor/purify.min.js'};if(req.method==='GET'&&files[route]){const file=path.join(ROOT,'public',files[route]);res.writeHead(200,{'Content-Type':MIME[path.extname(file)],'Cache-Control':'no-store'});return fs.createReadStream(file).pipe(res);}
      json(res,404,{error:'Not found.'});
    }catch(e){fs.appendFileSync(path.join(ROOT,'logs/app.log'),new Date().toISOString()+' '+e.stack+'\n');if(!res.headersSent)json(res,400,{error:e.message});else res.end();}
  });
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(config.port,'127.0.0.1',resolve);});
  if(config.autoStartModel&&!process.env.STEREO_AGENT_NO_MODEL)model.start().catch(e=>{model.state.phase='error';model.state.message=e.message;});
  return {server,store,model,tools,agent,config,url:`http://127.0.0.1:${config.port}`,close:async()=>{agent.cancel();directController?.abort();await model.stop();await new Promise(resolve=>server.close(resolve));}};
}
if(require.main===module){startServer().then(instance=>{console.log('StereoAgent Studio '+instance.url);let closing=false;for(const sig of ['SIGINT','SIGTERM'])process.on(sig,async()=>{if(closing)return;closing=true;await instance.close();process.exit(0);});}).catch(e=>{console.error(e);process.exitCode=1;});}
module.exports={startServer};
