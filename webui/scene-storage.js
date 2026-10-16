window.createAetherSceneStorage=assets=>{
  const status=document.getElementById('scene-storage-status');
  const maxSceneBytes=8*20*1024*1024+65548;
  function packageScene() {
    const objects=assets.snapshot();
    const metadata=new TextEncoder().encode(JSON.stringify(objects.map(({data,...placement})=>({...placement,bytes:data.byteLength}))));
    if (metadata.byteLength>65536) throw Error('場景資料太大。');
    const header=new ArrayBuffer(12), view=new DataView(header);
    view.setUint32(0,0x4e435341,true); view.setUint32(4,1,true); view.setUint32(8,metadata.byteLength,true);
    return new Blob([header,metadata,...objects.map(object=>object.data)],{type:'application/octet-stream'});
  }
  function unpackScene(data) {
    if (!(data instanceof ArrayBuffer) || data.byteLength<12 || data.byteLength>maxSceneBytes) throw Error('場景檔大小無效。');
    const view=new DataView(data), size=view.getUint32(8,true);
    if (view.getUint32(0,true)!==0x4e435341 || view.getUint32(4,true)!==1) throw Error('不支援的 Aether 場景檔。');
    if (size>65536 || size>data.byteLength-12) throw Error('場景資料大小無效。');
    const metadata=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(new Uint8Array(data,12,size)));
    if (!Array.isArray(metadata) || metadata.length>8) throw Error('場景物件無效。');
    let offset=12+size;
    const objects=metadata.map(entry=>{
      if (!entry || !Number.isInteger(entry.bytes) || entry.bytes<20 || entry.bytes>20*1024*1024 || entry.bytes>data.byteLength-offset) throw Error('模型資料大小無效。');
      const buffer=data.slice(offset,offset+entry.bytes); offset+=entry.bytes;
      assets.validate(buffer);
      const {bytes,...placement}=entry;
      return {...placement,data:buffer};
    });
    if (offset!==data.byteLength) throw Error('場景檔含有無法辨識的資料。');
    return objects;
  }
  function exportFile() {
    try {
      const blob=packageScene(), url=URL.createObjectURL(blob), link=document.createElement('a');
      link.href=url; link.download='aetherpose.aetherscene'; link.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
      status.textContent='已匯出場景檔（內含模型）。'; return true;
    } catch(error) { status.textContent=`匯出失敗：${error.message}`; return false; }
  }
  async function importFile(file) {
    if (!file) return false;
    const revision=assets.revision;
    try {
      if (file.size>maxSceneBytes) throw Error('場景檔太大。');
      const data=await file.arrayBuffer();
      if (revision!==assets.revision) { status.textContent='場景有變動，已取消匯入。'; return false; }
      const objects=unpackScene(data), restored=await assets.restore(objects);
      status.textContent=restored?`已匯入 ${objects.length} 個場景物件。`:'匯入沒有取代目前的場景。';
      return restored;
    } catch(error) { status.textContent=`匯入失敗：${error.message}`; return false; }
  }
  async function transaction(mode,operation) {
    const db=await new Promise((resolve,reject)=>{
      let rejected=false;
      const request=indexedDB.open('aetherpose-scenes',1);
      request.onupgradeneeded=()=>request.result.createObjectStore('scenes');
      request.onerror=()=>{rejected=true;reject(request.error);};
      request.onblocked=()=>{rejected=true;reject(Error('場景儲存正在其他分頁使用中。'));};
      request.onsuccess=()=>{if(rejected)request.result.close();else resolve(request.result);};
    });
    return new Promise((resolve,reject)=>{
      const tx=db.transaction('scenes',mode); let result;
      tx.oncomplete=()=>{db.close();resolve(result);};
      tx.onerror=tx.onabort=()=>{db.close();reject(tx.error||Error('場景儲存失敗。'));};
      try { const request=operation(tx.objectStore('scenes')); request.onsuccess=()=>result=request.result; }
      catch(error) { tx.abort(); reject(error); }
    });
  }
  async function save() {
    try {
      const objects=assets.snapshot();
      await transaction('readwrite',store=>store.put({version:1,objects},'current'));
      status.textContent=`已在這個瀏覽器儲存 ${objects.length} 個物件。`; return true;
    } catch(error) { status.textContent=`儲存失敗：${error.message}`; return false; }
  }
  async function restore() {
    const revision=assets.revision;
    try {
      const saved=await transaction('readonly',store=>store.get('current'));
      if (revision!==assets.revision) { status.textContent='場景有變動，已取消還原。'; return false; }
      if (!saved) { status.textContent='這個瀏覽器沒有儲存的場景。'; return false; }
      if (saved.version!==1) throw Error('不支援的場景存檔版本。');
      const restored=await assets.restore(saved.objects);
      status.textContent=restored?'已還原儲存的場景。':'還原沒有取代目前的場景。'; return restored;
    } catch(error) { status.textContent=`還原失敗：${error.message}`; return false; }
  }
  async function forget() {
    try { await transaction('readwrite',store=>store.delete('current')); status.textContent='已刪除儲存的場景，目前的物件保留。'; return true; }
    catch(error) { status.textContent=`刪除失敗：${error.message}`; return false; }
  }
  return {save,restore,forget,packageScene,unpackScene,exportFile,importFile};
};
