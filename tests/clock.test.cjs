const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');const os=require('node:os');
const {clockSnapshot,isLocalClockRequest,clockReply}=require('../server/clock.cjs');const {Store}=require('../server/store.cjs');const {Agent}=require('../server/agent.cjs');
test('time zones and date rollovers use the OS instant, not a fixed calendar date',()=>{
 const instant=new Date('2026-11-04T20:30:45Z');const china=clockSnapshot('Asia/Shanghai',instant);const ny=clockSnapshot('America/New_York',instant);
 assert.equal(china.date,'2026-11-05');assert.equal(china.time,'04:30:45');assert.equal(ny.date,'2026-11-04');assert.equal(ny.time,'15:30:45');assert.match(clockReply('现在几点',china),/Asia\/Shanghai/);assert.match(clockReply('What time is it?',ny),/America\/New_York/);
});
test('only pure supported local-clock requests bypass the model',()=>{
 for(const s of ['今天日期和当前时间','现在几点？','请问今天是星期几？','今天几号','当前时间','What time is it now?','What is the current date and time?'])assert.ok(isLocalClockRequest(s),s);
 for(const s of ['明天北京天气怎么样','纽约现在几点','现在几点，顺便裁剪左边20px','今天有什么新闻','生成图片，文字写今天日期','2024年10月25日是星期几'])assert.equal(isLocalClockRequest(s),false,s);
});
test('simple date query uses no model and no image; other questions receive fresh runtime context',async()=>{
 const store=new Store(fs.mkdtempSync(path.join(os.tmpdir(),'stereo-clock-')));const s=store.db.sessions[0];let calls=0,captured;
 const model={complete:async messages=>{calls++;captured=messages;return '{"reply":"This build cannot verify live news.","actions":[]}';}};
 const agent=new Agent(store,model,{config:{timeZone:'Asia/Shanghai',stereoEnabled:false}});
 const timeTask=await agent.run(s.id,'今天日期和当前时间');for(let i=0;i<10&&agent.running;i++)await new Promise(r=>setTimeout(r,10));assert.equal(calls,0);assert.equal(timeTask.status,'completed');assert.match(s.messages.at(-1).content,/Asia\/Shanghai/);assert.equal(timeTask.runtimeClock.date,clockSnapshot().date);
 await agent.run(s.id,'今天新闻有哪些');for(let i=0;i<20&&agent.running;i++)await new Promise(r=>setTimeout(r,10));assert.equal(calls,1);const payload=JSON.parse(captured[1].content[0].text.split('\nUSER REQUEST: ')[0]);assert.equal(payload.runtimeClock.date,clockSnapshot().date);assert.equal(payload.webSearchAvailable,false);
});
