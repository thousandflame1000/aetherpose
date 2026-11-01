// Reaction Lights: independent rules, driven only by fresh observed poses.
const ReactionGame=(()=>{
  const create=()=>({phase:'release',target:0,previous:0,lastAt:null,correct:0,wrong:0,early:0,missed:0,totalMs:0,bestMs:null,lastMs:null,message:'雙手放下，準備下一個燈號。'});
  const reset=s=>{s.phase='release';s.lastAt=null;s.message='雙手放下，重新準備。';};
  function step(s,input,now,random=Math.random) {
    if (s.lastAt!==null && (now<s.lastAt || now-s.lastAt>250)) reset(s);
    s.lastAt=now;
    if (s.phase==='release') {
      if(input.neutral) {s.phase='wait';s.due=now+800+Math.floor(random()*1200);s.message='等待亮燈，先不要舉手。';}
      return null;
    }
    if (s.phase==='wait') {
      if(input.raised) {s.early++;s.phase='release';s.message='搶先動作！放下雙手再試。';return {kind:'early'};}
      if(now>=s.due) {
        const choices=[1,2,3].filter(value=>value!==s.previous);
        s.target=choices[Math.min(choices.length-1,Math.floor(random()*choices.length))];s.previous=s.target;
        s.phase='signal';s.cueAt=now;s.message={1:'左手舉過肩膀！',2:'右手舉過肩膀！',3:'雙手舉過肩膀！'}[s.target];
        return {kind:'signal'};
      }
      return null;
    }
    if(now-s.cueAt>=2500) {s.missed++;s.phase='release';s.message='超時，放下雙手準備下一題。';return {kind:'missed'};}
    if(input.raised===s.target) {
      const ms=Math.max(0,Math.round(now-s.cueAt));s.correct++;s.totalMs+=ms;s.lastMs=ms;s.bestMs=s.bestMs===null?ms:Math.min(s.bestMs,ms);
      s.phase='release';s.message=`正確！系統觀測 ${ms} ms，放下雙手。`;return {kind:'correct',ms};
    }
    if(input.raised && s.target!==3) {s.wrong++;s.phase='release';s.message='舉錯手，放下雙手再試。';return {kind:'wrong'};}
    return null;
  }
  return {create,reset,step};
})();

let reactionPractice=null;
function startReactionPractice() {
  if (game.state==='playing' || combatMode) {showPanelNotice('請先結束目前回合，再開鍵盤試玩。',4);return false;}
  const dialog=document.getElementById('reaction-practice');
  reactionPractice={rules:ReactionGame.create(),keys:new Set(),until:performance.now()+60000,done:false};
  if (!dialog.open) dialog.showModal();
  tickReactionPractice();return true;
}
function closeReactionPractice() {reactionPractice=null;document.getElementById('reaction-practice').close();}
function tickReactionPractice(now=performance.now()) {
  const p=reactionPractice,dialog=document.getElementById('reaction-practice');
  if (!p || !dialog.open || p.done) return;
  if (document.hidden) {p.done=true;p.keys.clear();document.getElementById('reaction-practice-message').textContent='試玩已停止：頁面切到背景。';return;}
  if (now>=p.until) {p.done=true;p.keys.clear();document.getElementById('reaction-practice-message').textContent='試玩結束！可重新開始。';return;}
  const raised=p.keys.has(' ')?3:(p.keys.has('a')?1:0)|(p.keys.has('l')?2:0);
  ReactionGame.step(p.rules,{raised,neutral:raised===0},now);
  document.querySelectorAll('[data-practice-lamp]').forEach(lamp=>lamp.classList.toggle('on',p.rules.phase==='signal'&&Number(lamp.dataset.practiceLamp)===p.rules.target));
  document.getElementById('reaction-practice-message').textContent=p.rules.message;
  document.getElementById('reaction-practice-stats').textContent=`剩 ${Math.max(0,Math.ceil((p.until-now)/1000))} 秒 · `+reactionResultLines(p.rules).slice(0,2).join(' · ');
}
for(const type of ['keydown','keyup']) document.addEventListener(type,event=>{
  if(!reactionPractice || !document.getElementById('reaction-practice').open) return;
  const key=event.key.toLowerCase();if(!['a','l',' '].includes(key)) return;
  event.preventDefault();
  if(type==='keydown') reactionPractice.keys.add(key);else reactionPractice.keys.delete(key);
  tickReactionPractice();
});
document.getElementById('reaction-practice').addEventListener('close',()=>{reactionPractice=null;});
window.addEventListener('blur',()=>{if(reactionPractice&&!reactionPractice.done){reactionPractice.keys.clear();ReactionGame.reset(reactionPractice.rules);}});
