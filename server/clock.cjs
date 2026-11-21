// Runtime facts come from the OS clock, never from model training data.
function clockSnapshot(timeZone='Asia/Shanghai',now=new Date()){
  const format=new Intl.DateTimeFormat('en-GB',{timeZone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'});
  const parts=Object.fromEntries(format.formatToParts(now).map(p=>[p.type,p.value]));
  return {date:`${parts.year}-${parts.month}-${parts.day}`,time:`${parts.hour}:${parts.minute}:${parts.second}`,timeZone,utc:now.toISOString(),source:'Operating system clock'};
}
function isLocalClockRequest(text){
  const normalized=text.trim().replace(/[\s，。！？、：；,.?!:;]/g,'').toLowerCase();
  return /^(?:请|请问|告诉我|麻烦告诉我)?(?:今天|现在|当前)(?:的)?(?:日期|时间|几点|几点了|几号|几号了|星期几|周几|是几号|是几月几号|是星期几|是周几|是什么日期|是什么时间|日期和时间|日期和当前时间|日期及时间|日期与时间|日期和现在时间|日期是多少|时间是多少)(?:是什么|是多少|呢|吗)?$/.test(normalized)
    ||/^(?:what(?:'s|is)(?:the)?(?:current|today'?s)?(?:date|time|dateandtime)|(?:current|today'?s)(?:date|time|dateandtime)|whattimeisit(?:now)?|whatisthedatetoday|whatdayisittoday)$/.test(normalized);
}
function clockReply(text,snapshot){
  const day=new Intl.DateTimeFormat(/[\u3400-\u9fff]/.test(text)?'zh-CN':'en-GB',{timeZone:snapshot.timeZone,weekday:'long'}).format(new Date(snapshot.utc));
  return /[\u3400-\u9fff]/.test(text)?`今天是 ${snapshot.date}，${day}，当前时间为 ${snapshot.time}（${snapshot.timeZone}）。\n\n时间来自本机系统时钟，按上述时区显示。`:`Today is ${snapshot.date}, ${day}. The current time is ${snapshot.time} (${snapshot.timeZone}).\n\nSource: the local system clock, displayed in the stated time zone.`;
}
module.exports={clockSnapshot,isLocalClockRequest,clockReply};
