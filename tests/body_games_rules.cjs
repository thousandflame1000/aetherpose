const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const context=vm.createContext({});
vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../webui/body-games.js'),'utf8')+';globalThis.rules=BodyGames',context);
const R=context.rules;
function pose(){const j=Array.from({length:24},()=>[0,1,0]);j[10]=[-.1,0,0];j[11]=[.1,0,0];j[15]=[0,1.7,0];j[16]=[-.2,1.4,0];j[17]=[.2,1.4,0];return j;}
let now=0;
function tick(s,j,n){let score=0;for(let i=0;i<n;i++){now+=100;score+=R.step(s,j,now,1.7,1);}return score;}
const m=R.create('memory',()=>0),j=pose();tick(m,j,15);assert.equal(m.phase,'answer');
const left=pose();left[15][0]=-.2;
assert.equal(tick(m,left,5),10);assert.equal(m.sequence.length,2);
tick(m,j,26);assert.equal(m.phase,'answer');
const right=pose();right[15][0]=.2;tick(m,right,5);assert.equal(m.mistakes,1);assert.equal(m.phase,'preview');
const f=R.create('freeze');tick(f,j,27);assert.equal(f.phase,'amber');tick(f,j,10);assert.equal(f.phase,'red');
const arm=pose();arm[20][0]=.2;tick(f,arm,1);assert.equal(f.mistakes,1);assert.equal(f.phase,'green');
tick(f,j,35);assert.equal(f.phase,'red');now+=1000;R.step(f,j,now,1.7,1);assert.equal(f.phase,'green');assert.equal(f.mistakes,1);
console.log('Body-game rules: sequence success/wrong order, full-body freeze violation, stale-pose recovery passed');
