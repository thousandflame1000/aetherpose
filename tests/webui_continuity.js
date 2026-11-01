// Full browser recovery scenarios. Synthetic poses are explicit and local to this test.
(async()=>{
  const checks=[],assert=(ok,name)=>{if(!ok)throw Error(name);checks.push(name);};
  const $=id=>document.getElementById(id);
  const joints=()=>[[0,0,0],[-.09,-.08,0],[.09,-.08,0],[0,.12,0],[-.09,-.45,0],[.09,-.45,0],
    [0,.28,0],[-.09,-.86,0],[.09,-.86,0],[0,.4,0],[-.09,-.9,.12],[.09,-.9,.12],
    [0,.54,0],[-.15,.42,0],[.15,.42,0],[0,.68,0],[-.22,.4,0],[.22,.4,0],
    [-.4,.27,0],[.4,.27,0],[-.58,.15,0],[.58,.15,0],[-.64,.15,0],[.64,.15,0]];
  let version=1,hidden=false;
  Object.defineProperty(document,'hidden',{configurable:true,get:()=>hidden});
  const packet=data=>meshWs.onmessage({data:JSON.stringify(data)});
  const frame=(status='Streaming #1 DEBUG mask=test live 0/6',j=joints())=>packet({status,joints:j,joints_version:version++});
  const tick=seconds=>{window.testClock+=seconds*1000;avatar.tick(seconds,performance.now()/1000);updateReachClock(performance.now());AetherCombat.tick(performance.now()/1000);};
  const start=mode=>{if(game.state==='playing')endGame('Round ended');AetherCombat.stopRound('Round stopped.');dismissRoundResult();chooseGame(mode);frame();startGame();};
  try {
    assert(!window.testErrors.length,'initializes');
    chooseGame('reach');avatar.disconnect();startGame();
    assert(game.state==='playing'&&poseContinuity.held,'start queues once when no pose is available');
    const waitingDeadline=game.deadline;tick(20);
    assert(game.state==='playing'&&game.score===0,'long initial wait does not end or score the round');
    frame();
    assert(!poseContinuity.held&&game.deadline===waitingDeadline+20000,'fresh input automatically starts queued round with all time preserved');

    game.score=7;const deadline=game.deadline,history=roundHistory.length;
    meshWs.readyState=3;meshWs.onclose();tick(75);
    assert(game.state==='playing'&&game.score===7&&roundHistory.length===history,'75 second disconnect outlasts the round without losing score or creating a result');
    meshWs.readyState=1;frame();
    assert(!poseContinuity.held&&game.deadline===deadline+75000,'reconnection resumes the same round without a second start');
    assert($('game-result').style.display!=='block','automatic recovery does not show a result dialog');

    const overlapDeadline=game.deadline;
    meshWs.readyState=3;refreshPoseContinuity();tick(1);toggleGamePause();tick(1);
    meshWs.readyState=1;frame();tick(1);
    assert(game.paused&&poseContinuity.held,'network recovery respects a simultaneous manual pause');
    toggleGamePause();
    assert(!poseContinuity.held&&game.deadline===overlapDeadline+3000,'overlapping interruption and manual pause extend clock only once');

    meshWs.readyState=3;meshWs.onclose();startBodyCalibration();
    assert(pendingBodyCalibration&&bodyCalibrationPhase==='requested','calibration can queue during a disconnected service');
    cancelBodyCalibration();assert(!pendingBodyCalibration&&bodyCalibrationPhase==='idle','queued calibration can be cancelled');
    startBodyCalibration();meshWs.readyState=1;meshWs.onopen();
    assert(!pendingBodyCalibration&&JSON.parse(meshWs.sent.at(-1)).cmd==='calibrate_body','queued calibration is sent automatically on reconnection');
    packet({calibration:{phase:'done',message:'Done'}});frame();
    assert(game.state==='playing'&&!poseContinuity.held,'queued calibration returns to the existing round');

    game.score=9;const resetDeadline=game.deadline;
    cmd('ResetMounting');tick(.2);
    assert(game.state==='playing'&&game.score===9&&poseContinuity.held,'mounting reset preserves active round');
    frame();assert(!poseContinuity.held&&game.score===9&&game.deadline===resetDeadline+200,'mounting reset resumes on the next real pose');

    const calDeadline=game.deadline;startBodyCalibration();tick(3);
    assert(game.state==='playing'&&game.score===9&&poseContinuity.held,'body calibration waits inside the same round');
    packet({calibration:{phase:'failed',message:'Try again',seconds_left:0}});frame();
    assert(!poseContinuity.held&&game.score===9&&game.deadline===calDeadline+3000,'failed calibration returns to play without discarding the round');
    frame('Streaming #2 LIVE 6/6 · 6 uncalibrated');
    assert(game.state==='playing'&&!poseContinuity.held,'uncalibrated status is a notice rather than a hard gameplay gate');

    hidden=true;document.dispatchEvent(new Event('visibilitychange'));const hiddenDeadline=game.deadline;tick(12);
    assert(game.state==='playing'&&game.score===9,'background tab preserves round and score');
    hidden=false;document.dispatchEvent(new Event('visibilitychange'));frame();
    assert(!poseContinuity.held&&game.deadline===hiddenDeadline+12000,'foreground resumes without losing background time');

    const beforeCameraScore=game.score;
    renderCameraAnchor({enabled:true,state:'tracking',aligned:true,can_score:true,position:[0,0,0],epoch:1});frame();
    renderCameraAnchor({enabled:true,state:'lost',aligned:true,can_score:false,position:[0,0,0],epoch:1});tick(.1);frame();
    assert(game.state==='playing'&&!poseContinuity.held&&game.score===beforeCameraScore,'camera marker loss keeps body gameplay available at the last position');
    renderCameraAnchor({enabled:false,state:'off',epoch:1});frame();
    sceneWorldChanged();frame();assert(game.state==='playing'&&game.score===9,'scene editing preserves round');

    start('memory');const bent=joints();bent[15][0]=.4;
    for(let i=0;i<28;i++){tick(.1);frame(undefined,bent);}
    assert(!game.calibrating&&game.state==='playing','standing alignment cannot block a game indefinitely');
    start('memory');game.calibrating=false;game.bodyGame=BodyGames.create('memory',()=>0);
    for(let i=0;i<25;i++){tick(.1);frame('Streaming #3 LIVE 6/6');}
    assert(game.bodyGame.phase==='answer','source change resets once rather than restarting the gesture on every later frame');
    assert(game.source.signature==='demo:0','round provenance stays conservative after returning to live input');
    endGame('Round ended');

    start('combat');const combatTime=+$('round-time').textContent;
    selectTab('cal');assert(AetherCombat.isRunning(),'opening settings does not end combat');
    $('recenter-btn').click();tick(.3);frame();
    assert(AetherCombat.isRunning()&&!AetherCombat.isHeld(),'recenter continues same combat round');
    $('combat-distance').value='1.5';$('combat-distance').dispatchEvent(new Event('input'));
    assert(AetherCombat.isRunning(),'opponent distance adjustment does not reset round');
    const hp=+$('player-hp-text').textContent,enemyHp=+$('enemy-hp-text').textContent;
    const historyBefore=roundHistory.length;
    meshWs.readyState=3;meshWs.onclose();tick(125);
    assert(AetherCombat.isRunning()&&AetherCombat.isHeld()&&+$('player-hp-text').textContent===hp,'125 second outage preserves combat beyond its normal round length');
    meshWs.readyState=1;frame();tick(.01);
    assert(AetherCombat.isRunning()&&!AetherCombat.isHeld()&&+$('round-time').textContent>=combatTime-1,'combat reconnects with round time preserved');
    assert(+$('enemy-hp-text').textContent===enemyHp&&roundHistory.length===historyBefore,'recovery creates neither artificial hits nor an unfinished history row');
    frame('Streaming #3 LIVE 6/6');tick(.1);frame('Streaming #4 DEBUG mask=test live 2/6');
    assert(AetherCombat.isRunning()&&!AetherCombat.isHeld(),'source changes continue with the currently available pose');
    packet({calibration:{phase:'tpose',message:'Hold'}});tick(3);
    assert(AetherCombat.isRunning()&&AetherCombat.isHeld(),'combat holds during calibration');
    packet({calibration:{phase:'done',message:'Done'}});frame();tick(.01);
    assert(AetherCombat.isRunning()&&!AetherCombat.isHeld(),'combat resumes after calibration');
    AetherCombat.onSceneChanged();assert(AetherCombat.isRunning(),'combat scene edit preserves round');

    hidden=true;document.dispatchEvent(new Event('visibilitychange'));tick(6);
    hidden=false;document.dispatchEvent(new Event('visibilitychange'));frame();tick(.01);
    assert(AetherCombat.isRunning()&&!AetherCombat.isHeld(),'combat survives background and foreground');
    $('combat-stop').click();
    assert(!AetherCombat.isRunning()&&roundHistory.length===historyBefore+1,'explicit stop still finishes and records exactly one round');
    assert(roundHistory[0].source==='demo:0','a round containing demonstration input cannot become a pure-live record');

    start('reach');game.score=5;
    const extension=renderer.getContext().getExtension('WEBGL_lose_context');
    extension.loseContext();await new Promise(resolve=>setTimeout(resolve,60));
    assert(game.state==='playing'&&poseContinuity.held&&game.score===5,'real WebGL loss preserves round');
    extension.restoreContext();await new Promise(resolve=>setTimeout(resolve,100));frame();
    assert(!poseContinuity.held&&game.state==='playing'&&game.score===5,'real WebGL restoration resumes same round');
    game.deadline=performance.now();updateReachClock(performance.now());
    assert(game.state==='over'&&roundHistory[0].completed,'normal timeout still completes a round');
    assert(!window.testErrors.length,'no runtime errors during recovery');
    document.body.dataset.testResult=JSON.stringify({ok:true,checks});
  } catch(error){document.body.dataset.testResult=JSON.stringify({ok:false,checks,error:error.stack});}
})();
