from pathlib import Path
import os
import json,numpy as np
base=Path(os.environ.get('AETHER_SIM_DATA_DIR',str(Path(__file__).parent/'data')));base.mkdir(parents=True,exist_ok=True);root=Path(__file__).resolve().parents[2]
data=json.loads((base/'truth.json').read_text(encoding='utf-8'))
truth=np.load(base/'truth.npz');data['mounts']=truth['mounts'].reshape(19,9).round(6).tolist()
html='''<!doctype html><meta charset="utf-8"><style>body{margin:0;background:#d4cfbf}canvas{display:block}</style><body>
<script>__THREE__</script><script>__SKIN__</script><script>
const data=__DATA__;const scene=new THREE.Scene();scene.background=new THREE.Color(0xd4cfbf);
const camera=new THREE.PerspectiveCamera(33,640/800,.05,30);camera.position.set(0,1.03,3.7);camera.lookAt(0,.85,0);
const renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});renderer.setSize(640,800);renderer.outputEncoding=THREE.sRGBEncoding;document.body.appendChild(renderer.domElement);
scene.add(new THREE.HemisphereLight(0xffffff,0x8b8274,.85));const light=new THREE.DirectionalLight(0xfff3df,.8);light.position.set(-2,4,3);scene.add(light);
const floor=new THREE.Mesh(new THREE.PlaneGeometry(8,8),new THREE.MeshStandardMaterial({color:0x9f998d,roughness:1}));floor.rotation.x=-Math.PI/2;scene.add(floor);
const wall=new THREE.Mesh(new THREE.PlaneGeometry(8,5),new THREE.MeshStandardMaterial({color:0xd4cfbf,roughness:1}));wall.position.set(0,2,-1.5);scene.add(wall);
for(let x=-3;x<=3;x+=.45){const p=new THREE.Mesh(new THREE.BoxGeometry(.012,.001,6),new THREE.MeshBasicMaterial({color:0x8c887e}));p.position.set(x,.001,0);scene.add(p);}
const skin=smplSkinning.load(data.skin),positions=new Float32Array(skin.count*3),colors=new Float32Array(positions.length);
for(let v=0;v<skin.count;v++){const bone=skin.bones[v*4];let color=0xb98d70;if([0,1,2,4,5].includes(bone))color=0x24334b;else if([3,6,9,12,13,14,16,17].includes(bone))color=0xa92c34;else if([7,8,10,11].includes(bone))color=0xbac0bf;const c=new THREE.Color(color);colors.set([c.r,c.g,c.b],v*3);}
const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.BufferAttribute(positions,3));geo.setAttribute('color',new THREE.BufferAttribute(colors,3));geo.setIndex(data.faces);
const body=new THREE.Mesh(geo,new THREE.MeshStandardMaterial({vertexColors:true,roughness:.85,side:THREE.DoubleSide}));body.position.y=.97;body.frustumCulled=false;scene.add(body);
const face=new THREE.Group();for(const x of [-.031,.031]){const eye=new THREE.Mesh(new THREE.SphereGeometry(.007,12,8),new THREE.MeshStandardMaterial({color:0x292421}));eye.position.set(x,.092,.085);face.add(eye);}
const mouth=new THREE.Mesh(new THREE.BoxGeometry(.033,.004,.004),new THREE.MeshStandardMaterial({color:0x75493e}));mouth.position.set(0,.047,.09);face.add(mouth);
const hair=new THREE.Mesh(new THREE.SphereGeometry(.097,20,12,0,Math.PI*2,0,Math.PI/2),new THREE.MeshStandardMaterial({color:0x30251f,roughness:1}));hair.scale.set(1,.8,1.03);hair.position.set(0,.122,-.018);face.add(hair);scene.add(face);
const sensors=data.sensor_joints.map(()=>{const g=new THREE.Group();g.add(new THREE.Mesh(new THREE.BoxGeometry(.028,.018,.04),new THREE.MeshStandardMaterial({color:0x303639,roughness:.6})));const led=new THREE.Mesh(new THREE.SphereGeometry(.003,6,4),new THREE.MeshBasicMaterial({color:0x5effbb}));led.position.z=.022;g.add(led);scene.add(g);return g;});
const occluder=new THREE.Mesh(new THREE.BoxGeometry(.92,1.15,.08),new THREE.MeshStandardMaterial({color:0x547568,roughness:1}));scene.add(occluder);
const fullBlocker=new THREE.Mesh(new THREE.BoxGeometry(2.1,2.1,.08),new THREE.MeshStandardMaterial({color:0x547568,roughness:1}));fullBlocker.position.set(0,1,1.1);scene.add(fullBlocker);
const mat=(r)=>new THREE.Matrix4().set(r[0],r[1],r[2],0,r[3],r[4],r[5],0,r[6],r[7],r[8],0,0,0,0,1);
function drawFrame(i,blocked=true){const f=data.frames[i];smplSkinning.pose(skin,f.rotations,f.translation,positions);geo.attributes.position.needsUpdate=true;geo.computeVertexNormals();
 const G=[];for(let j=0;j<24;j++){const local=mat(f.rotations.slice(j*9,j*9+9));G[j]=j===0?local:G[data.skin.parents[j]].clone().multiply(local);}
 const head=f.joints[15];face.position.set(head[0],head[1]+f.translation[1]+.97,head[2]);face.quaternion.setFromRotationMatrix(G[15]);
 for(let k=0;k<sensors.length;k++){const j=data.sensor_joints[k];const child=data.skin.parents.findIndex((p,c)=>c>0&&p===j);let offset=new THREE.Vector3(0,0,.052);if(child>=0){const a=data.skin.joints.slice(j*3,j*3+3),b=data.skin.joints.slice(child*3,child*3+3);offset.add(new THREE.Vector3(b[0]-a[0],b[1]-a[1],b[2]-a[2]).multiplyScalar(.45));}offset.applyMatrix4(G[j]);const p=f.joints[j];sensors[k].position.set(p[0]+offset.x,p[1]+f.translation[1]+.97+offset.y,p[2]+offset.z);sensors[k].quaternion.setFromRotationMatrix(G[j].clone().multiply(mat(data.mounts[k])));}
 const t=f.t;occluder.visible=blocked&&t>=5&&t<9;occluder.position.set(-.32+.15*Math.sin(t*1.2),.88,1.05);fullBlocker.visible=blocked&&t>=10&&t<12;
 renderer.render(scene,camera);return renderer.domElement.toDataURL('image/png').split(',')[1];}
window.drawFrame=drawFrame;window.sceneReady=true;drawFrame(0,false);
</script>'''
html=html.replace('__THREE__',(root/'webui/vendor/three/three.min.js').read_text(encoding='utf-8')).replace('__SKIN__',(root/'webui/skinning.js').read_text(encoding='utf-8')).replace('__DATA__',json.dumps(data,separators=(',',':')))
(base/'scene.html').write_text(html,encoding='utf-8')
print('Source camera scene prepared.')
