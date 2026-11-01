// Causal display following: latest received rotations only, no future buffer.
// This replaces vertex blending, keeping the rig's bone lengths during motion.
window.createCausalPoseFollower = () => {
  let displayed=null,target=null,position=null,destination=null,dirty=false;
  const m=new THREE.Matrix4();
  function push(pose){
    if(!pose||!Array.isArray(pose.rotations)||pose.rotations.length!==216||!pose.rotations.every(Number.isFinite)||
       !Array.isArray(pose.translation)||pose.translation.length!==3||!pose.translation.every(Number.isFinite))return false;
    const next=[];
    for(let j=0;j<24;j++){
      const r=pose.rotations.slice(j*9,j*9+9);
      m.set(r[0],r[1],r[2],0,r[3],r[4],r[5],0,r[6],r[7],r[8],0,0,0,0,1);
      if(Math.abs(m.determinant()-1)>.01)return false;
      next.push(new THREE.Quaternion().setFromRotationMatrix(m).normalize());
    }
    target=next;destination=pose.translation.slice();dirty=true;
    if(!displayed){displayed=target.map(q=>q.clone());position=destination.slice();}
    return true;
  }
  function step(dt){
    if(!displayed)return null;
    const a=1-Math.exp(-Math.max(0,Number.isFinite(dt)?dt:0)*30);
    let moving=false;const R=[];
    for(let j=0;j<24;j++){
      if(1-Math.abs(displayed[j].dot(target[j]))>1e-12){moving=true;displayed[j].slerp(target[j],a);}
      else displayed[j].copy(target[j]);
      m.makeRotationFromQuaternion(displayed[j]);const e=m.elements;
      R.push(e[0],e[4],e[8],e[1],e[5],e[9],e[2],e[6],e[10]);
    }
    for(let k=0;k<3;k++){
      if(Math.abs(destination[k]-position[k])>1e-5){moving=true;position[k]+=(destination[k]-position[k])*a;}
      else position[k]=destination[k];
    }
    if(!moving&&!dirty)return null;dirty=moving;
    return{rotations:R,translation:position.slice()};
  }
  return{push,step};
};
