// Reuse the film's own drawing functions without changing its source.
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module');
const root=path.resolve(__dirname,'..'),dir=path.join(root,'video/campaign-motion');
const {createCanvas,GlobalFonts}=require(path.join(dir,'node_modules/@napi-rs/canvas'));
for(const [file,name] of [['BebasNeue-Regular.ttf','Bebas Neue'],['DMSans.ttf','DM Sans']])GlobalFonts.registerFromPath(path.join(root,'static/brand',file),name);
const filename=path.join(dir,'film-polished.js'),mod=new Module(filename,module);mod.filename=filename;mod.paths=Module._nodeModulePaths(dir);
mod._compile(fs.readFileSync(filename,'utf8').replace('const film={drawFrame,setLogoImage,duration:91.2,fps:60};','const film={drawFrame,setLogoImage,localMap,country,aed,crisisRadio,batteryMarker,databaseIcon,pin,crisisOffline,crisisHardware,duration:91.2,fps:60};'),filename);
const f=mod.exports;
function render(name,w,h,draw){const canvas=createCanvas(w*2,h*2),c=canvas.getContext('2d');c.scale(2,2);c.lineCap='round';c.lineJoin='round';draw(c);fs.writeFileSync(path.join(root,'static/campaign',name+'.png'),canvas.toBuffer('image/png'));}
render('aed',460,480,c=>f.aed(c,230,255,2.25,2));
render('lora',640,470,c=>{c.strokeStyle='#91c899';c.lineWidth=2;c.setLineDash([4,8]);c.beginPath();c.moveTo(190,110);c.bezierCurveTo(270,20,370,20,450,100);c.stroke();c.setLineDash([]);f.crisisRadio(c,190,280,1.55,-.10,42,true);f.crisisRadio(c,450,295,1.35,.10,42,false);});
render('battery',200,160,c=>f.batteryMarker(c,100,80,5,2));
render('database',150,150,c=>f.databaseIcon(c,75,75,3));
render('pin',150,150,c=>f.pin(c,75,135,2.4,'#00843d'));
render('poland',960,540,c=>f.country(c,30));
render('offline',960,540,c=>f.crisisOffline(c,47));
console.log('Extracted seven assets directly from film-polished.js');
// Matching geography at both stages: only the record-resolution state changes.
for (const [name,time] of [['poland-before',21],['poland-after',29]]) {
 render(name,740,540,c=>{c.translate(-110,0);f.country(c,time);});
}

render('bydgoszcz-route',740,600,c=>{
 c.fillStyle='#e9e7db';c.fillRect(0,0,740,600);
 const scale=2.05,px=420,py=190;
 f.localMap(c,scale,px,py);
 const route=require(path.join(dir,'geo.js')).route.map(([x,y])=>[px+x*scale,py+y*scale]);
 function stroke(color,width){c.beginPath();route.forEach(([x,y],i)=>i?c.lineTo(x,y):c.moveTo(x,y));c.strokeStyle=color;c.lineWidth=width;c.stroke();}
 stroke('#f6f2e5',12);stroke('#00843d',6);
 const [x,y]=route[0];c.beginPath();c.arc(x,y,12,0,Math.PI*2);c.fillStyle='#00843d';c.fill();c.strokeStyle='#fffdf3';c.lineWidth=5;c.stroke();
 f.pin(c,px,py,1.45,'#00843d');
 c.fillStyle='#0b3928';c.font='26px "Bebas Neue"';c.fillText('BYDGOSZCZ GŁÓWNA',px+32,py-43);
 c.font='14px "DM Sans"';c.fillText('AED',px+32,py-19);
});
