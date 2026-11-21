const {app,BrowserWindow}=require('electron');const path=require('node:path');const fs=require('node:fs');
const ROOT=path.resolve(__dirname,'..');app.setPath('userData',path.join(ROOT,'data/electron'));let instance,win;
fs.mkdirSync(path.join(ROOT,'logs'),{recursive:true});
if(!app.requestSingleInstanceLock()){app.quit();}else{
  app.on('second-instance',()=>{if(win){if(win.isMinimized())win.restore();win.show();win.focus();}});
  app.whenReady().then(async()=>{
    instance=await require('../server/index.cjs').startServer();
    win=new BrowserWindow({width:1480,height:940,minWidth:1050,minHeight:700,backgroundColor:'#f7f8fa',title:'StereoAgent Studio',autoHideMenuBar:true,webPreferences:{contextIsolation:true,nodeIntegration:false,sandbox:true}});
    win.webContents.setWindowOpenHandler(()=>({action:'deny'}));win.webContents.on('will-navigate',(e,url)=>{if(!url.startsWith(instance.url+'/'))e.preventDefault();});
    await win.loadURL(instance.url);
  }).catch(e=>{fs.appendFileSync(path.join(ROOT,'logs/app.log'),e.stack+'\n');require('electron').dialog.showErrorBox('StereoAgent Studio',e.message);app.quit();});
  let quitting=false;app.on('before-quit',e=>{if(instance&&!quitting){e.preventDefault();quitting=true;instance.close().finally(()=>app.quit());}});app.on('window-all-closed',()=>app.quit());
}
