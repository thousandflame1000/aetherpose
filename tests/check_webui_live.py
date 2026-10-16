r"""Smoke-test the running backend/bridge/UI with Chromium and real pose data.

Run with the project environment (websockets required):
  ..\.venv\Scripts\python.exe tests/check_webui_live.py
The services must already be running (webui/run.ps1 -NoBrowser).
"""
import argparse
import asyncio
import base64
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request

import websockets

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('simulate_trackers', ROOT / 'tools' / 'simulate_trackers.py')
simulator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(simulator)


async def inspect_page(endpoint, screenshot, view):
    async with websockets.connect(endpoint) as socket:
        sequence = 0
        errors = []
        warnings = []
        async def call(method, params=None):
            nonlocal sequence
            sequence += 1
            request_id = sequence
            await socket.send(json.dumps({'id':request_id,'method':method,'params':params or {}}))
            while True:
                msg = json.loads(await asyncio.wait_for(socket.recv(),10))
                if msg.get('method') == 'Runtime.exceptionThrown':
                    errors.append(msg.get('params',{}).get('exceptionDetails',{}))
                if msg.get('method') == 'Runtime.consoleAPICalled' and msg.get('params',{}).get('type') in ('warning','error'):
                    warnings.append([v.get('description',v.get('value')) for v in msg['params'].get('args',[])])
                if msg.get('id') == request_id:
                    if 'error' in msg: raise RuntimeError(msg['error'])
                    return msg.get('result',{})
        async def evaluate(expression):
            result = await call('Runtime.evaluate', {'expression':expression,'returnByValue':True,'awaitPromise':True})
            if 'exceptionDetails' in result: raise RuntimeError(result['exceptionDetails'])
            return result['result'].get('value')
        await call('Runtime.enable')
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            ready = await evaluate("typeof avatar !== 'undefined' && avatar.fresh() && !!avatar.root.getObjectByName('aether-body') && !!scene.getObjectByName('aether-opponent-model')?.userData.assetLoaded")
            if ready: break
            await asyncio.sleep(.25)
        else:
            state = await evaluate('''({url:location.href,title:document.title,
              errors:typeof avatar==='undefined'?'app not initialized':{
                fresh:avatar.fresh(),children:avatar.root.children.map(o=>o.name),
                status:document.getElementById('tp-status').textContent,
                meshSocket:meshWs?.readyState,poseVersion:lastJointVersion}})''')
            raise RuntimeError('No fresh body mesh within 20 seconds: ' + json.dumps({'state':state,'errors':errors}))
        report_expression = '''(() => {
          if (!avatar.fresh() || lastJointVersion==null || meshWs.readyState!==1) return null;
          selectTab('cal');
          window.liveSmokeBody = avatar.root.getObjectByName('aether-body');
          const initial = camera.position.clone();
          for(let i=0;i<10;i++){selectTab('combat');selectTab('cal');}
          const result = {
            canvasCount: document.querySelectorAll('canvas').length,
            unifiedWorld:poseScene.visible && scene.getObjectByName('combat-world').visible,
            onlineAssetLoaded:!!scene.getObjectByName('aether-opponent-model')?.userData.assetLoaded,
            animationTime:scene.getObjectByName('aether-opponent-model').userData.animationTime||0,
            vertexCount: liveSmokeBody.geometry.attributes.position.count,
            jointCount: avatar.joints.length,
            source: document.getElementById('tp-status').textContent,
            cameraRestored: initial.distanceTo(camera.position)<1e-6,
            bodyPreserved: liveSmokeBody === avatar.root.getObjectByName('aether-body'),
            backendConnected: document.getElementById('status-text').textContent === '已連線',
            poseVersion: lastJointVersion,
          };
          selectTab('combat'); document.getElementById('start-btn').click();
          result.roundStarted = document.getElementById('start-btn').textContent === '重新開始';
          return result;
        })()'''
        report=await evaluate(report_expression)
        reconnect_deadline=time.monotonic()+10
        while report is None:
            if time.monotonic()>=reconnect_deadline: raise RuntimeError('Tracking did not recover before round start')
            await asyncio.sleep(.2)
            report=await evaluate(report_expression)
        await asyncio.sleep(1.2)
        after = await evaluate('''({
          poseVersion:lastJointVersion,
          timeLeft:+document.getElementById('round-time').textContent,
          fresh:avatar.fresh(),
          bodyPreserved: liveSmokeBody === avatar.root.getObjectByName('aether-body')
        })''')
        # First-use GLTF/shadow shader compilation can briefly delay rendering
        # on software WebGL. Observe fresh progress rather than one fixed frame.
        progress_deadline=time.monotonic()+10
        while not (after['fresh'] and after['poseVersion']>report['poseVersion'] and after['timeLeft']<90):
            if time.monotonic()>=progress_deadline: break
            await asyncio.sleep(.2)
            after=await evaluate('''({poseVersion:lastJointVersion,
              timeLeft:+document.getElementById('round-time').textContent,fresh:avatar.fresh(),
              bodyPreserved:liveSmokeBody===avatar.root.getObjectByName('aether-body')})''')
        report['after'] = after
        report['runtimeMetrics'] = await evaluate("document.getElementById('pose-performance').textContent")
        report['sceneImport'] = await evaluate('''(async()=>{
          const body=avatar.root.getObjectByName('aether-body');
          const data=await (await fetch('assets/robot/RobotExpressive.glb')).arrayBuffer();
          await sceneAssets.load({name:'RobotExpressive.glb',size:data.byteLength,arrayBuffer:async()=>data});
          const loaded=Boolean(sceneAssets.model && scenePhysics.colliders.includes(sceneAssets.model));
          const firstModel=sceneAssets.model;
          await sceneAssets.load({name:'RobotExpressive-2.glb',size:data.byteLength,arrayBuffer:async()=>data});
          const multiple=sceneAssets.models.length===2 && scenePhysics.colliders.includes(firstModel) && scenePhysics.colliders.length===5;
          sceneAssets.place(1.8,-1.5);
          const positioned=sceneAssets.model && sceneAssets.model.position.x===1.8;
          sceneAssets.reshape(1.25,45);
          const transformed=sceneAssets.model && sceneAssets.model.scale.x===1.25 && Math.abs(sceneAssets.model.rotation.y-Math.PI/4)<1e-6;
          sceneAssets.resetPlacement();
          const reset=sceneAssets.model && sceneAssets.model.scale.x===1 && sceneAssets.model.rotation.y===0 && sceneAssets.model.position.x===1.6;
          sceneAssets.place(.8,-1); sceneAssets.reshape(1.25,30);
          sceneAssets.rename('Training obstacle'); sceneAssets.elevate(.6);
          const saved=await sceneStorage.save();
          sceneAssets.clearAll();
          const restored=await sceneStorage.restore();
          const persisted=saved && restored && sceneAssets.models.length===2 && sceneAssets.model.userData.assetName==='Training obstacle' && sceneAssets.model.position.x===.8 && Math.abs(sceneAssets.model.position.y-.5875)<1e-6 && sceneAssets.model.scale.x===1.25 && Math.abs(THREE.MathUtils.radToDeg(sceneAssets.model.rotation.y)-30)<1e-5;
          const portable=await sceneStorage.packageScene().arrayBuffer();
          sceneAssets.clearAll();
          const portableRestored=await sceneStorage.importFile({size:portable.byteLength,arrayBuffer:async()=>portable});
          const portablePassed=portableRestored && sceneAssets.models.length===2 && sceneAssets.model.userData.assetName==='Training obstacle' && sceneAssets.model.position.x===.8 && Math.abs(sceneAssets.model.position.y-.5875)<1e-6 && sceneAssets.model.scale.x===1.25;
          const restoredModels=sceneAssets.models;
          const forgotten=await sceneStorage.forget();
          const saveDeleted=forgotten && !await sceneStorage.restore() && sceneAssets.model===restoredModels[1];
          sceneAssets.clear();
          const removedSelected=sceneAssets.model===restoredModels[0] && scenePhysics.colliders.length===4;
          sceneAssets.clearAll();
          // Every training prop loads from the page server at its real size (a kettlebell stays ~0.3 m tall).
          const propIds=['training_cone','plyo_box','dumbbell','kettlebell','standing_bag','hurdle','gym_ball','bench','potted_plant','balance_pad'];
          const propHeights={};
          for (const id of propIds) {
            sceneAssets.clearAll(); await sceneAssets.loadBuiltin(id);
            const prop=sceneAssets.model;
            propHeights[id]=prop?+new THREE.Box3().setFromObject(prop).getSize(new THREE.Vector3()).y.toFixed(3):null;
          }
          const propsLoaded=propIds.every(id=>propHeights[id]>0.03 && propHeights[id]<1.6) && propHeights.kettlebell<0.4 && propHeights.standing_bag>1.2;
          sceneAssets.clearAll();
          await sceneAssets.loadBuiltin('lantern');
          const lantern=sceneAssets.model;
          let lanternMeshes=0; lantern?.traverse(node=>{if(node.isMesh)lanternMeshes++;});
          const libraryLoaded=lantern && lantern.userData.assetName==='木燈籠' && lanternMeshes>0 && scenePhysics.colliders.includes(lantern);
          document.getElementById('scene-assets').open=true; document.getElementById('scene-move-tool').checked=true; syncSceneMoveTool();
          const moveOrigin=lantern.position.clone(); scene.updateMatrixWorld(true); camera.updateMatrixWorld(true);
          const pointer=lantern.getWorldPosition(new THREE.Vector3()).project(camera);
          sceneMoveTool.axis='X'; sceneMoveTool.pointerDown({x:pointer.x,y:pointer.y,button:0});
          const dragStarted=sceneMoveTool.dragging && !controls.enabled;
          sceneMoveTool.pointerMove({x:pointer.x+.03,y:pointer.y,button:-1});
          sceneMoveTool.pointerUp({x:pointer.x+.03,y:pointer.y,button:0});
          const moved=lantern.position.distanceTo(moveOrigin)>1e-4;
          const moveToolPassed=dragStarted && moved && controls.enabled && sceneAssets.undo() && lantern.position.distanceTo(moveOrigin)<1e-6;
          setSceneToolSnap(true); scene.updateMatrixWorld(true); camera.updateMatrixWorld(true);
          const snapPointer=lantern.getWorldPosition(new THREE.Vector3()).project(camera);
          sceneMoveTool.axis='X'; sceneMoveTool.pointerDown({x:snapPointer.x,y:snapPointer.y,button:0});
          sceneMoveTool.pointerMove({x:snapPointer.x+.063,y:snapPointer.y,button:-1});
          sceneMoveTool.pointerUp({x:snapPointer.x+.063,y:snapPointer.y,button:0});
          const snapToolPassed=lantern.position.distanceTo(moveOrigin)>1e-4 && Math.abs(lantern.position.x*10-Math.round(lantern.position.x*10))<1e-6 && controls.enabled && sceneAssets.undo() && lantern.position.distanceTo(moveOrigin)<1e-6;
          setSceneToolSnap(false);
          setSceneToolMode('scale'); scene.updateMatrixWorld(true); camera.updateMatrixWorld(true);
          const scaleOrigin=lantern.scale.x;
          const scaleStart=lantern.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(.3,0,0)).project(camera);
          const scaleEnd=lantern.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(.5,0,0)).project(camera);
          sceneMoveTool.axis='X'; sceneMoveTool.pointerDown({x:scaleStart.x,y:scaleStart.y,button:0});
          sceneMoveTool.pointerMove({x:scaleEnd.x,y:scaleEnd.y,button:-1});
          sceneMoveTool.pointerUp({x:scaleEnd.x,y:scaleEnd.y,button:0});
          const scaleToolPassed=Math.abs(lantern.scale.x-scaleOrigin)>1e-4 && lantern.scale.x===lantern.scale.y && lantern.scale.x===lantern.scale.z && controls.enabled && sceneAssets.undo() && Math.abs(lantern.scale.x-scaleOrigin)<1e-6;
          setSceneToolMode('rotate'); setSceneToolSnap(true); scene.updateMatrixWorld(true); camera.updateMatrixWorld(true);
          const rotateOrigin=lantern.rotation.y, rotateCenter=lantern.getWorldPosition(new THREE.Vector3());
          const rotateStart=rotateCenter.clone().add(new THREE.Vector3(.4,0,0)).project(camera);
          const rotateEnd=rotateCenter.clone().add(new THREE.Vector3(.4*Math.cos(Math.PI/7),0,.4*Math.sin(Math.PI/7))).project(camera);
          sceneMoveTool.axis='Y'; sceneMoveTool.pointerDown({x:rotateStart.x,y:rotateStart.y,button:0});
          sceneMoveTool.pointerMove({x:rotateEnd.x,y:rotateEnd.y,button:-1});
          sceneMoveTool.pointerUp({x:rotateEnd.x,y:rotateEnd.y,button:0});
          const rotateSteps=(lantern.rotation.y-rotateOrigin)/(Math.PI/12);
          const rotateToolPassed=Math.abs(rotateSteps)>1e-4 && Math.abs(rotateSteps-Math.round(rotateSteps))<1e-6 && controls.enabled && sceneAssets.undo() && Math.abs(lantern.rotation.y-rotateOrigin)<1e-6;
          setSceneToolSnap(false);
          setSceneToolMode('translate');
          document.getElementById('scene-move-tool').checked=false; syncSceneMoveTool(); document.getElementById('scene-assets').open=false;
          sceneAssets.clearAll();
          return {loaded,multiple,removedSelected,positioned,transformed,reset,persisted,portablePassed,libraryLoaded,propsLoaded,propHeights,moveToolPassed,snapToolPassed,scaleToolPassed,rotateToolPassed,saveDeleted,removed:!sceneAssets.model && scenePhysics.colliders.length===3,
            bodyPreserved:body===avatar.root.getObjectByName('aether-body'),canvasCount:document.querySelectorAll('canvas').length};
        })()''')
        report['physics'] = await evaluate('''(()=>{
          const body=avatar.root.getObjectByName('aether-body');
          body.geometry.computeBoundingBox(); avatar.root.updateMatrixWorld(true);
          const bounds=body.geometry.boundingBox.clone().applyMatrix4(avatar.root.matrixWorld);
          return {enabled:scenePhysics.stats.enabled,backend:scenePhysics.stats.backend,
            milliseconds:scenePhysics.stats.milliseconds,contacts:scenePhysics.stats.contacts,
            floorClear:bounds.min.y>=-.0076,obstacles:scenePhysics.colliders.length};
        })()''')
        report['opponentAnimated'] = await evaluate('scene.getObjectByName("aether-opponent-model").userData.animationTime>'+str(report['animationTime']))
        ok = (all(report['sceneImport'][key] for key in ('loaded','multiple','removedSelected','positioned','transformed','reset','persisted','portablePassed','libraryLoaded','propsLoaded','moveToolPassed','snapToolPassed','scaleToolPassed','rotateToolPassed','saveDeleted','removed','bodyPreserved')) and report['sceneImport']['canvasCount']==1 and report['physics']['enabled'] and report['physics']['floorClear'] and report['physics']['obstacles']==3 and report['opponentAnimated'] and report['onlineAssetLoaded'] and report['unifiedWorld'] and report['canvasCount']==1 and report['vertexCount']>1000 and report['jointCount']==24 and
              report['cameraRestored'] and report['bodyPreserved'] and report['backendConnected'] and
              report['roundStarted'] and after['fresh'] and after['bodyPreserved'] and
              after['poseVersion']>report['poseVersion'] and after['timeLeft']<90)
        if screenshot:
            if view == 'results':
                await evaluate("selectTab('combat'); finishCombatRound({mode:'combat',score:41,source:'demo:0',completed:false,reason:'Round ended',seconds:28,difficulty:'normal',combatStats:{attempts:10,hits:7,targets:5,blocked:1,defenses:3,received:4,counters:2,bestCombo:4},combatBreakdown:{received:{high:1,body:1,flank:2},defended:{high:2,body:1,flank:0}}})")
                await asyncio.sleep(.2)
            if view in ('control','library'):
                await evaluate("selectTab('cal')")
                await asyncio.sleep(.2)
            if view == 'library':
                await evaluate("sceneAssets.loadBuiltin('lantern')")
                await evaluate("sceneAssets.reshape(1.5,0);document.getElementById('scene-assets').open=true;document.getElementById('scene-move-tool').checked=true;syncSceneMoveTool()")
                await asyncio.sleep(.3)
            result = await call('Page.captureScreenshot',{'format':'png'})
            Path(screenshot).write_bytes(base64.b64decode(result['data']))
            if view == 'library':
                await evaluate('sceneAssets.clearAll()')
        await evaluate("document.getElementById('recenter-btn').click()")
        await asyncio.sleep(.5)
        fresh_deadline=time.monotonic()+10
        while not await evaluate('avatar.fresh()'):
            if time.monotonic()>=fresh_deadline: break
            await asyncio.sleep(.2)
        recentered = await evaluate('''(() => {
          const hip=avatar.root.localToWorld(new THREE.Vector3(...avatar.joints[0]));
          return {
            roundStopped:document.getElementById('start-btn').textContent==='開始回合',
            fresh:avatar.fresh(),
            hipAtSpawn:Math.abs(hip.x-avatar.combatX)<1e-6 && Math.abs(hip.z)<1e-6,
            bodyPreserved:liveSmokeBody===avatar.root.getObjectByName('aether-body')
          };
        })()''')
        # The screenshot may have selected the control view. The same origin
        # command works there, while spawn anchoring is a combat invariant.
        if view == 'control':
            await evaluate("selectTab('combat')")
            recentered['hipAtSpawn'] = await evaluate("Math.abs(avatar.root.localToWorld(new THREE.Vector3(...avatar.joints[0])).x-avatar.combatX)<1e-6")
        report['recentered'] = recentered
        ok = ok and all(recentered.values())
        await evaluate("document.getElementById('reset-btn').click()")
        report['poseGames'] = []
        await evaluate("selectTab('cal')")
        for mode in ('reach', 'squat', 'balance', 'dodge', 'sky', 'clap', 'march', 'star', 'cross', 'guard', 'shoulder', 'highfive'):
            started = await evaluate('''(() => {
              const select=document.getElementById('game-mode');
              select.value=%s; select.dispatchEvent(new Event('change'));
              document.getElementById('game-btn').click();
              return {playing:game.state==='playing',mode:game.mode,version:lastJointVersion,
                calibrating:game.calibrating,targets:targetMeshes.filter(m=>m.visible).length,
                cue:document.getElementById('pose-game-cue').textContent};
            })()''' % json.dumps(mode))
            # Observe an actual new pose, rather than assuming inference must
            # complete within 300 ms on the host running this check.
            pose_progress_deadline=time.monotonic()+5
            while not await evaluate('avatar.fresh() && lastJointVersion>'+str(started['version'])):
                if time.monotonic()>=pose_progress_deadline: break
                await asyncio.sleep(.1)
            stopped = await evaluate('''(() => {
              const result={fresh:avatar.fresh(),version:lastJointVersion,
                bodyPreserved:liveSmokeBody===avatar.root.getObjectByName('aether-body'),
                canvasCount:document.querySelectorAll('canvas').length};
              document.getElementById('game-stop').click();
              result.stopped=game.state==='over';
              result.controlsRestored=document.getElementById('game-btn').style.display==='inline-block' &&
                document.getElementById('game-stop').style.display==='none';
              result.unfinished=document.getElementById('game-result').textContent.includes('未完成的回合');
              return result;
            })()''')
            passed = (started['playing'] and started['mode']==mode and bool(started['cue']) and
                      started['targets']==(3 if mode=='reach' else 0) and
                      started['calibrating']==(mode!='reach') and stopped['fresh'] and
                      stopped['version']>started['version'] and stopped['bodyPreserved'] and
                      stopped['canvasCount']==1 and stopped['stopped'] and
                      stopped['controlsRestored'] and stopped['unfinished'])
            report['poseGames'].append({'mode':mode,'started':started,'stopped':stopped,'ok':passed})
            ok = ok and passed
        report['historyRecorded'] = await evaluate("['combat','reach','squat','balance','dodge','sky','clap','march','star','cross','guard','shoulder','highfive'].every(mode=>roundHistory.some(entry=>entry.mode===mode))")
        ok=ok and report['historyRecorded']
        report['circuits'] = await evaluate('''(()=>{
          const before=camera.position.clone(),body=avatar.root;
          const results=Object.keys(poseCircuits).map(name=>{
            document.getElementById('pose-circuit').value=name; startPoseCircuit();
            const started=game.state==='playing' && game.mode===poseCircuits[name][0] && poseCircuit.index===0;
            stopPoseCircuit();
            return {name,started,stopped:!poseCircuit && game.state==='over'};
          });
          return {results,sharedWorld:camera.position.equals(before) && avatar.root===body && document.querySelectorAll('canvas').length===1};
        })()''')
        ok=ok and report['circuits']['sharedWorld'] and all(item['started'] and item['stopped'] for item in report['circuits']['results'])
        report['animationContinuity'] = await evaluate('''(()=>{
          const model=scene.getObjectByName('aether-opponent-model');
          AetherCombat.cheer('end'); const starts=model.userData.animationStarts;
          AetherCombat.cheer('end');
          return {loaded:model.userData.assetLoaded===true,starts,continuous:model.userData.animation==='Dance' && model.userData.animationStarts===starts};
        })()''')
        ok=ok and report['animationContinuity']['loaded'] and report['animationContinuity']['starts']>0 and report['animationContinuity']['continuous']
        report['opponentFacing'] = await evaluate('''(()=>{
          const group=scene.getObjectByName('aether-opponent'),model=scene.getObjectByName('aether-opponent-model');
          const player=group.worldToLocal(avatar.root.localToWorld(new THREE.Vector3(...avatar.joints[0])));
          const direction=player.sub(model.position); direction.y=0; direction.normalize();
          const facing=new THREE.Vector3(0,0,1).applyEuler(model.rotation); facing.y=0; facing.normalize();
          return {alignment:facing.dot(direction),groupRotation:group.rotation.y,bodyPreserved:avatar.root.parent===scene && Boolean(avatar.root.getObjectByName('aether-body'))};
        })()''')
        ok=ok and report['opponentFacing']['alignment']>.98 and report['opponentFacing']['groupRotation']==0 and report['opponentFacing']['bodyPreserved']
        report['sceneImage'] = await evaluate('''(async()=>{
          const before=camera.position.clone(),loopCanvas=document.querySelectorAll('canvas').length;
          const blob=await captureSceneImage(),bitmap=await createImageBitmap(blob);
          const sample=new OffscreenCanvas(16,16),context=sample.getContext('2d'); context.drawImage(bitmap,0,0,16,16);
          const pixels=context.getImageData(0,0,16,16).data,colors=new Set();
          for(let index=0;index<pixels.length;index+=4) colors.add(`${pixels[index]},${pixels[index+1]},${pixels[index+2]}`);
          const result={png:blob.type==='image/png',width:bitmap.width,height:bitmap.height,nonblank:colors.size>1,preserved:camera.position.equals(before)&&document.querySelectorAll('canvas').length===loopCanvas};
          bitmap.close(); return result;
        })()''')
        ok=ok and report['sceneImage']['png'] and report['sceneImage']['nonblank'] and report['sceneImage']['preserved']
        # Live trackers end to end: simulated trackers squat (UDP -> backend -> TransPose) and
        # Squat Rhythm scores from that pose. The simulator forgets its trackers when it stops.
        run = threading.Thread(target=lambda: simulator.main(['--motion', 'squat', '--follow-calibration', '--seconds', '60']), daemon=True)
        with contextlib.redirect_stdout(io.StringIO()):
            run.start()
            deadline = time.monotonic() + 15
            while not await evaluate("meshWs?.readyState===1 && avatar.fresh() && aetherPoseSource(bridgeStatus).kind==='live'"):
                if time.monotonic() > deadline:
                    break
                await asyncio.sleep(0.3)
            await evaluate("selectTab('cal');startBodyCalibration()")
            calibration_phases = []
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                state = await evaluate("({phase:bodyCalibrationPhase,status:bridgeStatus,fresh:avatar.fresh()})")
                if not calibration_phases or calibration_phases[-1] != state['phase']:
                    calibration_phases.append(state['phase'])
                if ('bow' in calibration_phases and state['phase']=='done' and state['fresh']
                        and 'LIVE 6/6' in state['status'] and 'uncalibrated' not in state['status']):
                    break
                await asyncio.sleep(.2)
            report['liveBodyCalibration'] = {'phases':calibration_phases, 'final':state}
            if not (state['phase']=='done' and 'bow' in calibration_phases
                    and state['fresh'] and 'uncalibrated' not in state['status']):
                simulator.stop.set()
                run.join()
                raise RuntimeError('Body calibration did not complete before the live game: ' + json.dumps(report['liveBodyCalibration']))
            await evaluate("selectTab('games');dismissRoundResult();chooseGame('squat');startGame()")
            squat_observations = []
            squat_started = time.monotonic()
            for sample_index in range(1, 20):
                await asyncio.sleep(max(0, squat_started + sample_index - time.monotonic()))
                observation = await evaluate("({version:lastJointVersion,metrics:document.getElementById('pose-performance').textContent,state:game.state,calibrating:game.calibrating,score:game.score,phase:game.phase,hold:game.hold,standingHead:game.standingHeight,standingHip:game.standingHip,head:avatar.joints[15]?.[1],hip:avatar.joints[0]?.[1],feet:Math.abs(avatar.joints[10]?.[1]-avatar.joints[11]?.[1])})")
                observation['elapsed_s'] = time.monotonic() - squat_started
                squat_observations.append(observation)
            await asyncio.sleep(max(0, squat_started + 20 - time.monotonic()))
            report['liveSquatObservations'] = squat_observations
            report['liveSquats'] = await evaluate("({state:game.state,score:game.score,source:game.source&&game.source.kind})")
            await evaluate("endGame('Round ended');dismissRoundResult()")
            simulator.stop.set()
            run.join()
        ok=ok and report['liveSquats']['source']=='live' and report['liveSquats']['score']>=2
        # A measured input overflow replaces the rate line with its visible
        # warning; both are valid runtime states and have browser regressions.
        ok=ok and any(text in report['runtimeMetrics'] for text in ('個姿態', '部分動作更新已略過'))
        report['ok'] = ok
        report['runtimeErrors'] = errors
        report['warnings'] = warnings
        report['ok'] = ok and not errors
        print(json.dumps(report,indent=2))
        if not report['ok']: raise RuntimeError('Live smoke check failed')
        # Graceful browser shutdown also closes Chromium's utility children.
        await call('Browser.close')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url',default='http://127.0.0.1:18080/')
    parser.add_argument('--browser')
    parser.add_argument('--screenshot')
    parser.add_argument('--view',choices=['combat','control','library','results'],default='combat')
    args = parser.parse_args()
    candidates = [args.browser, shutil.which('chromium'), shutil.which('google-chrome'),
                  r'C:\Program Files\Google\Chrome\Application\chrome.exe',
                  r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe']
    browser = next((p for p in candidates if p and Path(p).is_file()),None)
    if not browser: raise SystemExit('Chromium missing; specify --browser PATH')
    with tempfile.TemporaryDirectory(prefix='aether-live-qa-') as tmp:
        profile = Path(tmp) / 'profile'
        process = subprocess.Popen([browser,'--headless=new','--no-sandbox','--enable-unsafe-swiftshader',
                                    '--no-first-run','--no-default-browser-check','--remote-debugging-port=0',
                                    '--window-size=1440,900','--user-data-dir='+str(profile),args.url],
                                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 15
            port_file = profile / 'DevToolsActivePort'
            port = None
            while port is None:
                if process.poll() is not None: raise RuntimeError('Chromium exited before debugger started')
                try:
                    port = int(port_file.read_text().splitlines()[0])
                    break
                except (OSError,ValueError,IndexError):
                    # Windows can expose the file before Chrome releases its
                    # write lock. Keep observing the same live browser process.
                    pass
                if time.monotonic()>deadline: raise RuntimeError('Chromium debugger startup timeout')
                time.sleep(.1)
            while True:
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list',timeout=2) as response:
                        targets = json.load(response)
                except (OSError,ValueError):
                    if process.poll() is not None: raise RuntimeError('Chromium exited during debugger startup')
                    if time.monotonic()>deadline: raise RuntimeError('Chromium debugger endpoint startup timeout')
                    time.sleep(.1)
                    continue
                target = next((t for t in targets if t['type']=='page' and t['url'].startswith(args.url)),None)
                if target: break
                if time.monotonic()>deadline: raise RuntimeError('Browser did not navigate to '+args.url)
                time.sleep(.1)
            asyncio.run(inspect_page(target['webSocketDebuggerUrl'],args.screenshot,args.view))
        finally:
            if process.poll() is None:
                try: process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    if os.name == 'nt':
                        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],
                                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    else:
                        process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
            # Windows may briefly retain profile locks after the process exits.
            # This path is the uniquely generated temporary browser profile.
            if profile.resolve().parent != Path(tmp).resolve():
                raise RuntimeError('Unexpected temporary profile path')
            cleanup_deadline=time.monotonic()+5
            while profile.exists():
                try: shutil.rmtree(profile)
                except OSError:
                    if time.monotonic()>=cleanup_deadline: raise
                    time.sleep(.1)


if __name__ == '__main__': main()
