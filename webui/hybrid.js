// Local capture is owned by the pose service; no competing browser camera.
let hybridRuntime=null;
function configureHybridTracking(){
  const stabilize=document.getElementById('hybrid-stabilize'),constraints=document.getElementById('hybrid-constraints');
  const sent=sendToBridge({cmd:'configure_tracking',stabilize:stabilize.checked,constraints:constraints.checked});
  if(!sent){
    stabilize.checked=hybridRuntime?.rotation_filter??true;constraints.checked=hybridRuntime?.joint_constraints??true;
    document.getElementById('hybrid-status').textContent='姿態服務未連線，設定尚未變更。';
  }
  return sent;
}
function hybridCamera(action) {
  const index=Number(document.getElementById('hybrid-camera-index').value);
  if(!Number.isInteger(index)||index<0||index>9){document.getElementById('hybrid-status').textContent='相機編號需為 0–9。';return false;}
  const sent=sendToBridge({cmd:'camera_anchor',action,index,marker_m:.12,purpose:'hybrid',vision_model:document.getElementById('hybrid-vision-model').value});
  if(!sent)document.getElementById('hybrid-status').textContent='姿態服務未連線，請啟動專案。';
  else document.getElementById('hybrid-status').textContent=action==='start'?'正在開啟影像骨架…':'正在停止影像…';
  return sent;
}
function alignHybridCamera(){
  if(!sendToBridge({cmd:'align_camera_pose'}))document.getElementById('hybrid-status').textContent='姿態服務未連線。';
}
function renderHybridCameraControls(state){
  const active=Boolean(state?.enabled);
  document.getElementById('hybrid-start').disabled=active;
  document.getElementById('hybrid-stop').disabled=!active;
  document.getElementById('hybrid-camera-index').disabled=active;
  document.getElementById('hybrid-vision-model').disabled=active;
}
function renderHybridRuntime(state){
  hybridRuntime=state;
  document.getElementById('hybrid-stabilize').checked=state.rotation_filter??true;
  document.getElementById('hybrid-constraints').checked=state.joint_constraints??true;
  document.getElementById('hybrid-protection').textContent=
    `姿態降抖${state.rotation_filter===false?'關閉':'開啟'} · 關節保護${state.joint_constraints===false?'關閉':'開啟'}`+
    (Number.isFinite(state.heading_feedback_deg)?` · 朝向補償 ${state.heading_feedback_deg.toFixed(1)}°`:'')+
    (state.camera_rejected_bones?` · 排除 ${state.camera_rejected_bones} 段不一致骨架`:'');
  document.getElementById('hybrid-model').textContent=
    `${state.globalpose?'GlobalPose 已參與融合':'影像／IMU 融合'} · 已校正 IMU ${state.imu_count??0} 顆`+
    (state.avatar_model==='generic'?' · 通用人體（可選用 SMPL）':'')+
    (state.globalpose?'':` · ${state.globalpose_message||''}`)+
    (state.waiting_alignment?' · 請對齊相機與 IMU':'')+
    (state.uncalibrated?` · ${state.uncalibrated} 顆待校正`:'');
  renderSetupSteps();
}
