window.createAetherSceneAssets=(scene,physics,onChange=()=>{})=>{
  let model=null,request=0;
  const models=[]; let nextId=0;
  // Training props come from tools/make_scene_props.py (real-world size); the
  // lantern and robot are downloaded CC0 models (see assets/README.md).
  const props={training_cone:'訓練錐',plyo_box:'跳箱',dumbbell:'啞鈴',kettlebell:'壺鈴',standing_bag:'立式沙袋',
    hurdle:'訓練欄架',gym_ball:'健身球',bench:'訓練椅',potted_plant:'盆栽',balance_pad:'平衡墊'};
  const library={lantern:{name:'木燈籠',url:'assets/lantern/Lantern.glb'},robot:{name:'機器人',url:'assets/robot/RobotExpressive.glb'},
    ...Object.fromEntries(Object.entries(props).map(([id,name])=>[id,{name,url:`assets/props/${id}.glb`}]))};
  function loadBuiltin(id) {
    const asset=library[id];
    if (!asset || !Object.hasOwn(library,id)) { status.textContent='請選擇場景庫模型。'; return Promise.resolve(); }
    return load({name:asset.name,size:0,arrayBuffer:async()=>{
      const response=await fetch(asset.url);
      if (!response.ok) throw Error('無法載入場景庫模型。');
      return response.arrayBuffer();
    }});
  }
  function spatialState(object=model) {
    return JSON.stringify([object.position.toArray(),object.scale.toArray(),object.rotation.toArray(),object.visible,object.userData.collisionEnabled!==false]);
  }
  function changed(before) {
    if (before!==undefined && before===spatialState()) return;
    physics.resetAll(); onChange();
  }
  const editHistory=new WeakMap();
  let moving=null;
  function beginMove() {
    endMove();
    if (!model) return false;
    request++; moving={object:model,state:editState(),before:spatialState()}; return true;
  }
  function updateMove(scaleAxis=null) {
    if (!moving || moving.object!==model || !models.includes(model)) return false;
    model.position.x=THREE.MathUtils.clamp(model.position.x,-2,2);
    model.position.y=THREE.MathUtils.clamp(model.position.y,-.0125,2.4875);
    model.position.z=THREE.MathUtils.clamp(model.position.z,-2,2);
    if (scaleAxis) {
      const value=model.scale[['X','Y','Z'].includes(scaleAxis)?scaleAxis.toLowerCase():'x'];
      model.scale.setScalar(Number.isFinite(value)?THREE.MathUtils.clamp(value,.25,2):moving.state.scale);
    }
    const forward=new THREE.Vector3(0,0,1).applyQuaternion(model.quaternion);
    model.rotation.set(0,Math.atan2(forward.x,forward.z),0);
    model.updateMatrixWorld(true); changed(moving.before); syncSelection(); return true;
  }
  function endMove() {
    if (!moving) return false;
    const move=moving; moving=null;
    if (move.object!==model || !models.includes(model) || move.before===spatialState()) return false;
    const entry=history(); entry.undo.push(move.state); if(entry.undo.length>50)entry.undo.shift(); entry.redo.length=0;
    syncSelection(); return true;
  }
  function editState() {
    return {x:model.position.x,y:model.position.y,z:model.position.z,scale:model.scale.x,yaw:model.rotation.y,
      name:model.userData.assetName,visible:model.visible,solid:model.userData.collisionEnabled!==false};
  }
  function history() {
    if (!editHistory.has(model)) editHistory.set(model,{undo:[],redo:[]});
    return editHistory.get(model);
  }
  function rememberEdit() {
    const entry=history(); entry.undo.push(editState());
    if (entry.undo.length>50) entry.undo.shift();
    entry.redo.length=0;
  }
  function replayEdit(direction) {
    if (!model) return false;
    const entry=history(), source=entry[direction];
    if (!source.length) return false;
    entry[direction==='undo'?'redo':'undo'].push(editState());
    const before=spatialState(), state=source.pop(); request++;
    model.position.set(state.x,state.y,state.z); model.scale.setScalar(state.scale);
    model.rotation.y=state.yaw; model.userData.assetName=state.name;
    model.visible=state.visible; model.userData.collisionEnabled=state.solid;
    model.updateMatrixWorld(true); changed(before); syncSelection(); return true;
  }
  const status=document.getElementById('scene-asset-status');
  const controls=document.getElementById('scene-asset-controls');
  const selectionFrame=new THREE.BoxHelper(undefined,0x78b5ff);
  selectionFrame.name='scene-object-selection'; selectionFrame.visible=false;
  selectionFrame.material.depthTest=false; selectionFrame.renderOrder=11; scene.add(selectionFrame);
  function refreshSelectionFrame() {
    selectionFrame.visible=Boolean(model && model.visible && document.getElementById('scene-assets').open);
    if (selectionFrame.visible) selectionFrame.setFromObject(model);
  }
  document.getElementById('scene-assets').addEventListener('toggle',refreshSelectionFrame);
  function dispose(object) {
    const resources=new Set();
    object.traverse(node=>{
      if (node.geometry) resources.add(node.geometry);
      if (node.skeleton && node.skeleton.boneTexture) resources.add(node.skeleton.boneTexture);
      for (const material of (Array.isArray(node.material)?node.material:[node.material])) if (material) {
        for (const value of Object.values(material)) if (value && value.isTexture) resources.add(value);
        resources.add(material);
      }
    });
    for (const resource of resources) resource.dispose();
  }
  function validate(data) {
    if (!(data instanceof ArrayBuffer) || data.byteLength<20 || data.byteLength>20*1024*1024) throw Error('請選擇小於 20 MB 的 GLB 檔。');
    const view=new DataView(data);
    if (view.getUint32(0,true)!==0x46546c67 || view.getUint32(4,true)!==2 || view.getUint32(8,true)!==data.byteLength) throw Error('需要有效的 GLB 2.0 檔。');
    const size=view.getUint32(12,true);
    if (view.getUint32(16,true)!==0x4e4f534a || size>data.byteLength-20) throw Error('GLB 的 JSON 區段無效。');
    const json=JSON.parse(new TextDecoder().decode(new Uint8Array(data,20,size)));
    for (const item of [...(json.buffers||[]),...(json.images||[])]) {
      if (item.uri && !item.uri.startsWith('data:')) throw Error('請使用貼圖與資料都內嵌（self-contained）的 GLB。');
    }
    if ((json.extensionsRequired||[]).some(name=>['KHR_draco_mesh_compression','EXT_meshopt_compression','KHR_texture_basisu'].includes(name))) throw Error('請匯出未壓縮的 GLB。');
    return json;
  }
  function syncSelection() {
    const select=document.getElementById('scene-asset-selection'); select.replaceChildren();
    for (const object of models) {
      const option=document.createElement('option'); option.value=object.userData.assetId;
      option.textContent=object.userData.assetName; option.selected=object===model; select.add(option);
    }
    select.disabled=!models.length; controls.hidden=!model;
    document.getElementById('scene-asset-undo').disabled=!model || !history().undo.length;
    document.getElementById('scene-asset-redo').disabled=!model || !history().redo.length;
    if (model) {
      document.getElementById('scene-asset-name').value=model.userData.assetName;
      document.getElementById('scene-asset-visible').checked=model.visible;
      document.getElementById('scene-asset-solid').checked=model.userData.collisionEnabled!==false;
      document.getElementById('scene-asset-x').value=model.position.x;
      document.getElementById('scene-asset-z').value=model.position.z;
      document.getElementById('scene-asset-height').value=model.position.y+.0125;
      document.getElementById('scene-asset-height-value').textContent=`${(model.position.y+.0125).toFixed(2)} m`;
      document.getElementById('scene-asset-scale').value=model.scale.x;
      const yaw=THREE.MathUtils.radToDeg(model.rotation.y);
      document.getElementById('scene-asset-yaw').value=yaw;
      document.getElementById('scene-asset-transform').textContent=`縮放 ${model.scale.x.toFixed(2)} · 旋轉 ${yaw.toFixed(0)}°`;
      status.textContent=`${model.userData.assetName} · ${models.length}/8 個物件`;
    } else status.textContent='尚未匯入場景物件。';
    refreshSelectionFrame();
  }
  function select(id) {
    const selected=models.find(object=>String(object.userData.assetId)===String(id));
    if (!selected) return;
    endMove();
    request++;
    model=selected; syncSelection();
  }
  function pick(raycaster) {
    const hits=raycaster.intersectObjects(models.filter(object=>object.visible),true);
    for (const hit of hits) {
      let object=hit.object, hidden=false;
      while (object && !models.includes(object)) { hidden=hidden||!object.visible; object=object.parent; }
      if (object && !hidden) { select(object.userData.assetId); return true; }
    }
    return false;
  }
  function clear() {
    request++;
    if (model) {
      physics.removeCollider(model); scene.remove(model); dispose(model);
      models.splice(models.indexOf(model),1); model=models[models.length-1]||null;
      onChange();
    }
    syncSelection();
    document.getElementById('scene-asset-file').value='';
  }
  function clearAll() {
    request++;
    const hadObjects=models.length>0;
    for (const object of models) { physics.removeCollider(object); scene.remove(object); dispose(object); }
    models.length=0; model=null; syncSelection();
    if (hadObjects) onChange();
    document.getElementById('scene-asset-file').value='';
  }
  function place(x,z) {
    if (!model) return;
    x=Number(x); z=Number(z);
    if (!Number.isFinite(x)||!Number.isFinite(z)) return;
    const before=spatialState();
    rememberEdit();
    request++;
    model.position.x=THREE.MathUtils.clamp(x,-2,2); model.position.z=THREE.MathUtils.clamp(z,-2,2);
    document.getElementById('scene-asset-x').value=model.position.x;
    document.getElementById('scene-asset-z').value=model.position.z;
    model.updateMatrixWorld(true); changed(before);
    syncSelection();
  }
  function elevate(height) {
    if (!model) return;
    height=Number(height); if (!Number.isFinite(height)) return;
    const before=spatialState();
    rememberEdit(); request++;
    model.position.y=THREE.MathUtils.clamp(height,0,2.5)-.0125;
    model.updateMatrixWorld(true); changed(before); syncSelection();
  }
  function reshape(scale,yaw) {
    if (!model) return;
    scale=Number(scale); yaw=Number(yaw);
    if (!Number.isFinite(scale)||!Number.isFinite(yaw)) return;
    const before=spatialState();
    rememberEdit();
    request++;
    scale=THREE.MathUtils.clamp(scale,.25,2); yaw=THREE.MathUtils.clamp(yaw,-180,180);
    model.scale.setScalar(scale); model.rotation.y=THREE.MathUtils.degToRad(yaw);
    document.getElementById('scene-asset-scale').value=scale;
    document.getElementById('scene-asset-yaw').value=yaw;
    document.getElementById('scene-asset-transform').textContent=`縮放 ${scale.toFixed(2)} · 旋轉 ${yaw.toFixed(0)}°`;
    model.updateMatrixWorld(true); changed(before);
    syncSelection();
  }
  function resetPlacement() {
    if (!model) return;
    const before=spatialState();
    rememberEdit(); request++;
    model.position.set(1.6,-.0125,-1.3); model.scale.setScalar(1); model.rotation.y=0;
    model.updateMatrixWorld(true); changed(before); syncSelection();
  }
  function setFlags(visible,solid) {
    if (!model || typeof visible!=='boolean' || typeof solid!=='boolean') return;
    const before=spatialState();
    rememberEdit();
    request++; model.visible=visible; model.userData.collisionEnabled=solid;
    changed(before); syncSelection();
  }
  function rename(name) {
    if (!model || typeof name!=='string') return;
    const trimmed=name.trim().slice(0,80);
    if (!trimmed) { status.textContent='請替選取的物件輸入名稱。'; return; }
    rememberEdit();
    request++; model.userData.assetName=trimmed; syncSelection();
  }
  async function build(data,name) {
    validate(data);
    const gltf=await new Promise((resolve,reject)=>new THREE.GLTFLoader().parse(data,'',resolve,reject));
    const object=gltf.scene, bounds=new THREE.Box3().setFromObject(object);
    const dimensions=bounds.getSize(new THREE.Vector3());
    const largest=Math.max(dimensions.x,dimensions.y,dimensions.z);
    if (!Number.isFinite(largest)||largest<=0) { dispose(object); throw Error('這個模型沒有可用的網格範圍。'); }
    // Models marked as real size (the library's training props) keep it; anything else is fitted to 1.2 m.
    const realScale=gltf.asset?.extras?.aetherposeRealScale===true;
    const scale=realScale?1:1.2/largest, center=bounds.getCenter(new THREE.Vector3());
    const root=new THREE.Group(); root.name='imported-scene-object';
    const normalization=new THREE.Group(); normalization.scale.setScalar(scale);
    normalization.position.set(-center.x*scale,-bounds.min.y*scale,-center.z*scale);
    object.traverse(node=>{ if (node.isMesh) { node.castShadow=true; node.receiveShadow=true; } });
    normalization.add(object); root.add(normalization); root.position.set(1.6,-.0125,-1.3);
    root.userData.assetId=++nextId; root.userData.assetName=String(name).slice(0,240); root.userData.assetData=data;
    return root;
  }
  function snapshot() {
    return models.map(object=>({name:object.userData.assetName,data:object.userData.assetData,
      x:object.position.x,z:object.position.z,height:object.position.y+.0125,scale:object.scale.x,yaw:THREE.MathUtils.radToDeg(object.rotation.y),
      visible:object.visible,solid:object.userData.collisionEnabled!==false}));
  }
  async function restore(entries) {
    const token=++request, staged=[];
    try {
      if (!Array.isArray(entries)||entries.length>8) throw Error('儲存的場景無效。');
      for (const entry of entries) {
        if (!entry || typeof entry.name!=='string' || ![entry.x,entry.z,entry.scale,entry.yaw].every(Number.isFinite) ||
          Math.abs(entry.x)>2 || Math.abs(entry.z)>2 || entry.scale<.25 || entry.scale>2 || Math.abs(entry.yaw)>180.00001) throw Error('儲存的擺放位置無效。');
        const height=entry.height===undefined?0:entry.height;
        if (!Number.isFinite(height) || height<0 || height>2.5) throw Error('儲存的高度無效。');
        const root=await build(entry.data,entry.name); staged.push(root);
        if (token!==request) { for (const object of staged) dispose(object); return false; }
        root.position.set(entry.x,height-.0125,entry.z); root.scale.setScalar(entry.scale); root.rotation.y=THREE.MathUtils.degToRad(entry.yaw);
        if ((entry.visible!==undefined && typeof entry.visible!=='boolean') || (entry.solid!==undefined && typeof entry.solid!=='boolean')) throw Error('儲存的物件狀態無效。');
        root.visible=entry.visible!==false; root.userData.collisionEnabled=entry.solid!==false;
      }
      if (token!==request) return false;
      for (const object of models) { physics.removeCollider(object); scene.remove(object); dispose(object); }
      models.length=0;
      for (const object of staged) { models.push(object); scene.add(object); physics.addCollider(object); }
      model=models[models.length-1]||null; changed(); syncSelection(); return true;
    } catch (error) {
      for (const object of staged) dispose(object);
      if (token===request) status.textContent=`還原失敗：${error.message||'場景無效'}`;
      return false;
    }
  }
  async function duplicate() {
    if (!model) return false;
    const source=model, token=++request;
    status.textContent='正在複製場景物件…';
    try {
      if (models.length>=8) throw Error('請先移除場景物件再新增（最多 8 個）。');
      const root=await build(source.userData.assetData,`${source.userData.assetName.slice(0,75)} 複本`);
      if (token!==request) { dispose(root); return false; }
      root.position.copy(source.position);
      root.position.x+=source.position.x<=1.5?.5:-.5;
      root.scale.copy(source.scale); root.rotation.copy(source.rotation);
      root.visible=source.visible; root.userData.collisionEnabled=source.userData.collisionEnabled!==false;
      root.updateMatrixWorld(true);
      models.push(root); model=root; scene.add(root); physics.addCollider(root);
      changed(); syncSelection(); return true;
    } catch (error) {
      if (token===request) status.textContent=`複製失敗：${error.message||'不支援的模型'}`;
      return false;
    }
  }
  async function load(file) {
    if (!file) return;
    const token=++request; status.textContent='正在載入場景物件…';
    try {
      if (models.length>=8) throw Error('請先移除場景物件再新增（最多 8 個）。');
      if (file.size>20*1024*1024) throw Error('請選擇小於 20 MB 的 GLB 檔。');
      const data=await file.arrayBuffer();
      if (token!==request) return;
      const root=await build(data,file.name);
      if (token!==request) { dispose(root); return; }
      model=root; models.push(root); scene.add(root); physics.addCollider(root);
      root.updateMatrixWorld(true); changed();
      syncSelection();
    } catch (error) {
      if (token===request) status.textContent=`匯入失敗：${error.message||'不支援的模型'}`;
    }
  }
  return {undo:()=>replayEdit('undo'),redo:()=>replayEdit('redo'),load,loadBuiltin,beginMove,updateMove,endMove,duplicate,clear,clearAll,select,pick,place,elevate,reshape,setFlags,rename,resetPlacement,validate,snapshot,restore,refreshSelectionFrame,get revision(){return request;},get model(){return model;},get models(){return models.slice();}};
};
