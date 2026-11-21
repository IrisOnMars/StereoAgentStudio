const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {startServer}=require('../server/index.cjs');

test('a right-view request saves only the compensated right view and its anaglyph',async()=>{
  const dataRoot=fs.mkdtempSync(path.join(os.tmpdir(),'stereo-right-view-'));
  const stereoRoot=path.join(dataRoot,'runtime');
  const scripts=path.join(stereoRoot,'scripts');
  const weights=path.join(stereoRoot,'assets','weights');
  fs.mkdirSync(scripts,{recursive:true});
  fs.mkdirSync(weights,{recursive:true});
  fs.writeFileSync(path.join(weights,'mono2stereo_runtime_fp16.pt'),'fixture');
  fs.writeFileSync(path.join(scripts,'run_mono2stereo_tensorrt_image.py'),`
import argparse
import json
from pathlib import Path

from PIL import Image

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--postprocess", choices=["appearance_multiband"], required=True)
parser.add_argument("--fit", required=True)
parser.add_argument("--right-pair", action="store_true")
args, _ = parser.parse_known_args()
if not args.right_pair:
    parser.error("Expected right pair")
for name in ("right.png", "anaglyph.png"):
    Image.new("RGB", (448, 256)).save(args.output / name)
(args.output / "summary.json").write_text(
    json.dumps({"postprocess": {"method": args.postprocess}, "fit": args.fit}),
    encoding="utf-8",
)
`);
  const instance=await startServer({
    port:17877,modelPort:17878,autoStartModel:false,stereoEnabled:true,stereoBackend:'pytorch',dataRoot,stereoRoot,
  });
  const post=async(route,body)=>{
    const response=await fetch(instance.url+'/api/'+route,{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),
    });
    return {status:response.status,body:await response.json()};
  };
  try{
    const session=instance.store.db.sessions[0];
    const base64=fs.readFileSync(path.join(__dirname,'fixtures/sample.png')).toString('base64');
    const source=await post('upload',{sessionId:session.id,name:'sample.png',base64});
    assert.equal(source.status,201);
    const generated=await post('tool',{
      sessionId:session.id,action:{tool:'generate_stereo',params:{format:'right',postprocess:'legacy_high_frequency'}},
    });
    assert.equal(generated.status,200,generated.body.error);
    const state=await(await fetch(instance.url+'/api/state')).json();
    const outputs=state.assets.filter(asset=>asset.stereoJobId);
    assert.deepEqual(outputs.map(asset=>asset.stereoFormat),['right','anaglyph']);
    const [right,anaglyph]=outputs;
    assert.equal(right.id,generated.body.asset);
    assert.equal(state.sessions[0].activeAssetId,right.id);
    assert.ok(outputs.every(asset=>asset.parentId===source.body.id&&asset.stereoJobId===right.stereoJobId));
    assert.ok(outputs.every(asset=>asset.operation.params.postprocess==='appearance_multiband'));

    const chosen=await post('tool',{sessionId:session.id,action:{tool:'select_stereo',params:{format:'anaglyph'}}});
    assert.equal(chosen.status,200,chosen.body.error);
    assert.equal(chosen.body.asset,anaglyph.id);
    assert.deepEqual(fs.readdirSync(path.join(dataRoot,'stereo')),[right.stereoJobId]);
  }finally{await instance.close();}
});
