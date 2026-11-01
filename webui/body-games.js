// Rules consume reconstructed body coordinates, never keyboard events.
const BodyGames=(()=>{
  const names=['左傾','右傾','蹲低'];
  function create(mode,random=Math.random) {
    return {mode,random,phase:'preview',sequence:[Math.floor(random()*3)],index:0,elapsed:0,hold:0,last:null,previous:null,baseline:null,round:0,mistakes:0,message:''};
  }
  function interrupt(s) {s.last=null;s.previous=null;s.baseline=null;s.hold=0;s.elapsed=0;s.steps=0;s.previousSide=0;s.lastAction=null;s.phase=s.mode==='memory'?'preview':'green';s.index=0;}
  function step(s,j,now,height,hipHeight) {
    if(!Array.isArray(j)||j.length<24||!j.every(p=>p.length>=3&&p.slice(0,3).every(Number.isFinite))) {interrupt(s);return 0;}
    const dt=s.last===null?0:now-s.last;
    if(dt<0||dt>250) interrupt(s);
    s.last=now;
    if(dt<=0||dt>250)return 0;
    s.elapsed+=dt;
    const scale=Math.max(.8,height),hip=j[0];
    const floor=Math.min(j[10][1],j[11][1]);
    const pose=j.map(p=>p.map((v,k)=>(v-(k===1?floor:hip[k]))/scale));
    // Shoulder axis makes lean independent of world-facing direction.
    const dx=j[17][0]-j[16][0],dz=j[17][2]-j[16][2],len=Math.hypot(dx,dz)||1;
    const lean=((j[15][0]-hip[0])*dx+(j[15][2]-hip[2])*dz)/len/scale;
    const squat=(hipHeight-(hip[1]-Math.min(j[10][1],j[11][1])))/scale;
    const action=squat>.09?2:lean<-.08?0:lean>.08?1:-1;
    const neutral=action===-1;
    if(s.mode==='memory') {
      if(s.phase==='preview') {
        const index=Math.floor(s.elapsed/1200);
        s.message=index<s.sequence.length?`記住順序 ${index+1}/${s.sequence.length}：${names[s.sequence[index]]}`:'回到站姿，準備重現';
        if(index>=s.sequence.length&&neutral){s.phase='answer';s.elapsed=0;}
      } else if(s.phase==='release') {
        s.message='回到站姿再做下一個動作';
        if(neutral){s.phase='answer';s.hold=0;}
      } else {
        s.message=`重現順序：第 ${s.index+1}/${s.sequence.length} 個（保持片刻）`;
        if(action!==s.lastAction)s.hold=0;
        s.lastAction=action;
        s.hold=action===-1?0:s.hold+dt;
        if(s.hold>=350) {
          s.hold=0;
          if(action!==s.sequence[s.index]) {s.mistakes++;s.index=0;s.phase='preview';s.elapsed=0;s.message='順序錯誤，重新觀看';return 0;}
          s.index++;
          if(s.index===s.sequence.length){s.round++;s.index=0;s.sequence.push(Math.floor(s.random()*3));if(s.sequence.length>6)s.sequence.shift();s.phase='preview';s.elapsed=0;return 10;}
          s.phase='release';
        }
      }
    } else {
      if(s.phase==='preview')s.phase='green';
      if(s.phase==='green') {
        s.message='綠燈：交替抬腳前進；黃燈即將到來';
        const foot=j[10][1]-j[11][1],side=foot>.06?1:foot<-.06?-1:0;
        if(side&&s.previousSide!==side){s.previousSide=side;s.steps=(s.steps||0)+1;}
        if(s.elapsed>=2500){s.phase='amber';s.elapsed=0;}
      } else if(s.phase==='amber') {
        s.message='黃燈：準備全身定格';
        if(s.elapsed>=1000){s.phase='red';s.elapsed=0;s.baseline=pose;s.previous=pose;}
      } else {
        s.message='紅燈：保持全身不動';
        const motion=Math.max(...pose.map((p,i)=>Math.hypot(...p.map((v,k)=>v-s.baseline[i][k]))));
        if(motion>.06){s.mistakes++;s.phase='green';s.elapsed=0;s.steps=0;s.message='紅燈移動：這段前進不計分';return 0;}
        if(s.elapsed>=1800){const score=Math.min(10,s.steps||0);s.round++;s.phase='green';s.elapsed=0;s.steps=0;return score;}
      }
    }
    return 0;
  }
  return {create,interrupt,step};
})();

// A pose replay explains the rules using the same 24-joint input and state machine.
// It is synthetic, unranked, and never writes tracker state, history or records.
let bodyReplay=null;
function startBodyReplay() {
  const mode=document.getElementById('game-mode').value;
  if(!['memory','freeze'].includes(mode)||game.state==='playing'||combatMode)return false;
  let dialog=document.getElementById('body-replay');
  if(!dialog){
    dialog=document.createElement('dialog');dialog.id='body-replay';
    dialog.innerHTML='<h2>姿態回放試玩</h2><p>合成骨架自動示範規則，不代表真人追蹤效果，不列入紀錄。</p><svg id="body-replay-figure" viewBox="-1 -2 2 2.3" style="width:100%;height:240px" aria-label="全身姿態示範"></svg><p id="body-replay-message" aria-live="polite"></p><p id="body-replay-score"></p><button type="button" class="btn">關閉</button>';
    dialog.querySelector('button').onclick=()=>dialog.close();
    dialog.addEventListener('close',()=>{bodyReplay=null;});document.body.append(dialog);
  }
  bodyReplay={rules:BodyGames.create(mode,()=>0),score:0,started:performance.now(),last:null};
  dialog.showModal();return true;
}
function tickBodyReplay(now) {
  const r=bodyReplay;if(!r)return;
  if(document.hidden){document.getElementById('body-replay').close();return;}
  if(r.last!==null&&now-r.last<50)return;r.last=now;
  const j=[[0,1,0],[-.1,.9,0],[.1,.9,0],[0,1.1,0],[-.1,.5,0],[.1,.5,0],[0,1.3,0],[-.1,.1,0],[.1,.1,0],[0,1.4,0],[-.1,0,0],[.1,0,0],[0,1.55,0],[-.15,1.45,0],[.15,1.45,0],[0,1.7,0],[-.22,1.4,0],[.22,1.4,0],[-.4,1.2,0],[.4,1.2,0],[-.5,1,0],[.5,1,0],[-.55,1,0],[.55,1,0]];
  if(r.rules.mode==='memory'&&r.rules.phase==='answer')for(const i of [3,6,9,12,13,14,15,16,17,18,19,20,21,22,23])j[i][0]-=.2;
  if(r.rules.mode==='freeze'&&(r.rules.phase==='green'||r.rules.phase==='preview')){
    const foot=Math.floor((now-r.started)/400)%2?10:11;j[foot][1]+=.12;
  }
  r.score+=BodyGames.step(r.rules,j,now,1.7,1);
  const parents=[-1,0,0,0,1,2,3,4,5,6,7,8,9,9,9,12,13,14,16,17,18,19,20,21];
  document.getElementById('body-replay-figure').innerHTML=parents.map((p,i)=>p<0?'':`<line x1="${j[p][0]}" y1="${-j[p][1]}" x2="${j[i][0]}" y2="${-j[i][1]}" stroke="${r.rules.phase==='red'?'#f87171':'#60a5fa'}" stroke-width=".025"/>`).join('');
  document.getElementById('body-replay-message').textContent=r.rules.message;
  document.getElementById('body-replay-score').textContent=`示範分數 ${r.score} · 完成 ${r.rules.round} 段`;
}
