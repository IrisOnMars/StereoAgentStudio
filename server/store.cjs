const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
class Store {
  constructor(root) {
    this.root=root; fs.mkdirSync(root,{recursive:true}); this.file=path.join(root,'workspace.json');
    this.db=fs.existsSync(this.file)?JSON.parse(fs.readFileSync(this.file,'utf8')):{sessions:[],assets:[],tasks:[]};
    for(const t of this.db.tasks) if(['running','queued'].includes(t.status)){t.status='interrupted';t.error='Application stopped before this task completed.';}
    if(!this.db.sessions.length)this.createSession(); this.save();
  }
  save(){fs.writeFileSync(this.file+'.tmp',JSON.stringify(this.db,null,2));fs.renameSync(this.file+'.tmp',this.file);}
  createSession(){const s={id:randomUUID(),title:'Untitled workspace',createdAt:new Date().toISOString(),messages:[],activeAssetId:null};this.db.sessions.unshift(s);this.save();return s;}
  session(id){const s=this.db.sessions.find(s=>s.id===id);if(!s)throw new Error('Workspace not found.');return s;}
  removeSession(id){
    this.session(id);
    this.db.sessions=this.db.sessions.filter(s=>s.id!==id);
    this.db.assets=this.db.assets.filter(a=>a.sessionId!==id);
    this.db.tasks=this.db.tasks.filter(t=>t.sessionId!==id);
    // Remove workspace records, not source/exported files or arbitrary paths.
    if(!this.db.sessions.length)this.createSession();else this.save();
    return {deletedId:id,fallbackSessionId:this.db.sessions[0].id};
  }
  asset(id,sessionId){const a=this.db.assets.find(a=>a.id===id&&a.sessionId===sessionId);if(!a)throw new Error('Image version not found in this workspace.');return a;}
  addAsset(sessionId,metadata){this.session(sessionId);const a={id:randomUUID(),sessionId,createdAt:new Date().toISOString(),...metadata};this.db.assets.push(a);this.session(sessionId).activeAssetId=a.id;this.save();return a;}
  addStereoOutputs(sessionId, outputs, format){
    const session=this.session(sessionId);
    const previous=session.activeAssetId;
    const createdAt=new Date().toISOString();
    const assets=outputs.map(output=>({id:randomUUID(),sessionId,createdAt,...output}));
    const active=assets.find(asset=>asset.stereoFormat===format);
    this.db.assets.push(...assets);
    session.activeAssetId=active.id;
    try{this.save();}
    catch(error){
      this.db.assets.length-=assets.length;
      session.activeAssetId=previous;
      throw error;
    }
    return active;
  }
  view(){return {sessions:this.db.sessions,assets:this.db.assets.map(({file,thumbnail,...a})=>a),tasks:this.db.tasks};}
}
module.exports={Store};
