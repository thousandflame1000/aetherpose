// Conservative mesh-derived collision constraints. CPU cost is O(vertices +
// colliders), rather than every body triangle against every scene triangle.
window.createAetherPhysics = scene => {
  const group=new THREE.Group(); group.name='aether-environment'; scene.add(group);
  const colliders=[];
  function obstacle(name,position,size) {
    const mesh=new THREE.Mesh(new THREE.BoxGeometry(...size),new THREE.MeshStandardMaterial({color:0x334557,roughness:.78}));
    mesh.material.color.convertSRGBToLinear();
    mesh.name=name; mesh.position.set(...position); mesh.castShadow=true; mesh.receiveShadow=true;
    group.add(mesh); colliders.push(mesh); return mesh;
  }
  obstacle('arena-back-wall',[0,1.1,-2.6],[5.8,2.2,.18]);
  obstacle('arena-left-column',[-2.45,.8,-1.5],[.32,1.6,.32]);
  obstacle('arena-right-column',[2.45,.8,-1.5],[.32,1.6,.32]);
  const worldBounds=new THREE.Box3(), obstacleBounds=new THREE.Box3();
  const correction=new THREE.Vector3();
  let history=new WeakMap();
  const debugGroup=new THREE.Group(); debugGroup.name='collision-overlays'; debugGroup.visible=false; scene.add(debugGroup);
  const bodyDebugBounds=new THREE.Box3();
  const bodyHelper=new THREE.Box3Helper(bodyDebugBounds,0x46d9ae); bodyHelper.name='collision-body-bounds'; debugGroup.add(bodyHelper);
  const opponentDebugBounds=new THREE.Box3();
  const opponentHelper=new THREE.Box3Helper(opponentDebugBounds,0xf5bd48); opponentHelper.name='collision-opponent-proxy'; debugGroup.add(opponentHelper);
  for (const object of colliders) {
    const helper=new THREE.BoxHelper(object,0x70aaff); helper.name='collision-'+object.name; helper.userData.sceneCollider=true; helper.userData.collider=object; debugGroup.add(helper);
  }
  debugGroup.traverse(object=>{
    if (object.material) { object.material.depthTest=false; object.material.transparent=true; object.material.opacity=.7; object.renderOrder=10; }
  });
  const stats={enabled:true,contacts:0,sweptContacts:0,milliseconds:0,backend:'CPU 網格範圍＋連續掃掠',unresolved:false};
  const floorY=-.0125, skin=.005;
  function meshBounds(object) {
    const boxes=[];
    object.updateWorldMatrix(true,true);
    object.traverseVisible(node=>{
      if (!node.isMesh || !node.geometry) return;
      if (!node.geometry.boundingBox) node.geometry.computeBoundingBox();
      const box=node.geometry.boundingBox.clone().applyMatrix4(node.matrixWorld);
      if (!box.isEmpty() && [box.min.x,box.min.y,box.min.z,box.max.x,box.max.y,box.max.z].every(Number.isFinite)) boxes.push(box);
    });
    return boxes;
  }
  function opponentBounds(object,box) {
    const p=object.getWorldPosition(new THREE.Vector3());
    box.min.set(p.x-.20,p.y+.2,p.z-.20);
    box.max.set(p.x+.20,p.y+1.65,p.z+.20);
    return box;
  }
  const closedMeshes=new WeakMap();
  const triangleTrees=new WeakMap(), queryStats={candidates:0,totalTriangles:0};
  function triangleCandidates(geometry,box,ray) {
    const positions=geometry.attributes.position, index=geometry.index;
    let tree=triangleTrees.get(geometry);
    if (!tree || tree.positions!==positions || tree.index!==index || tree.version!==positions.version || tree.indexVersion!==(index?index.version:0)) {
      const items=[], count=index?index.count:positions.count, vertex=new THREE.Vector3();
      for (let i=0;i+2<count;i+=3) {
        const bounds=new THREE.Box3();
        for (let corner=0;corner<3;corner++) bounds.expandByPoint(vertex.fromBufferAttribute(positions,index?index.getX(i+corner):i+corner));
        items.push({offset:i,bounds,center:bounds.getCenter(new THREE.Vector3())});
      }
      function build(entries) {
        const bounds=new THREE.Box3(); for (const entry of entries) bounds.union(entry.bounds);
        if (entries.length<=16) return {bounds,entries};
        const size=bounds.getSize(new THREE.Vector3()), axis=size.x>=size.y && size.x>=size.z?'x':size.y>=size.z?'y':'z';
        entries.sort((a,b)=>a.center[axis]-b.center[axis]); const middle=Math.floor(entries.length/2);
        return {bounds,left:build(entries.slice(0,middle)),right:build(entries.slice(middle))};
      }
      tree={positions,index,version:positions.version,indexVersion:index?index.version:0,total:items.length,root:build(items)};
      triangleTrees.set(geometry,tree);
    }
    const result=[];
    function matches(bounds) { return Boolean((box && bounds.intersectsBox(box)) || (ray && ray.intersectsBox(bounds))); }
    function visit(node) {
      if (!matches(node.bounds)) return;
      if (node.entries) { for (const entry of node.entries) if (matches(entry.bounds)) result.push(entry.offset); }
      else { visit(node.left); visit(node.right); }
    }
    visit(tree.root); queryStats.totalTriangles+=tree.total; queryStats.candidates+=result.length;
    return result;
  }
  function segmentDistanceSquared(a,b,c,d) {
    const u=b.clone().sub(a), v=d.clone().sub(c), w=a.clone().sub(c);
    const uu=u.lengthSq(), vv=v.lengthSq(), uv=u.dot(v), uw=u.dot(w), vw=v.dot(w);
    let s=0,t=0;
    if (uu<1e-12 && vv<1e-12) return w.lengthSq();
    if (uu<1e-12) t=THREE.MathUtils.clamp(vw/vv,0,1);
    else if (vv<1e-12) s=THREE.MathUtils.clamp(-uw/uu,0,1);
    else {
      const denominator=uu*vv-uv*uv;
      if (denominator>1e-12) s=THREE.MathUtils.clamp((uv*vw-uw*vv)/denominator,0,1);
      t=(uv*s+vw)/vv;
      if (t<0) { t=0; s=THREE.MathUtils.clamp(-uw/uu,0,1); }
      else if (t>1) { t=1; s=THREE.MathUtils.clamp((uv-uw)/uu,0,1); }
    }
    return w.addScaledVector(u,s).addScaledVector(v,-t).lengthSq();
  }
  function isClosedMesh(geometry) {
    const positions=geometry.attributes.position, index=geometry.index;
    const cached=closedMeshes.get(geometry);
    if (cached && cached.positions===positions && cached.index===index && cached.version===positions.version && cached.indexVersion===(index?index.version:0)) return cached.closed;
    const vertices=new Map(), ids=[];
    for (let i=0;i<positions.count;i++) {
      const key=[positions.getX(i),positions.getY(i),positions.getZ(i)].map(value=>Math.round(value*1e6)).join(',');
      if (!vertices.has(key)) vertices.set(key,vertices.size);
      ids.push(vertices.get(key));
    }
    const edges=new Map(), count=index?index.count:positions.count;
    let closed=count>=12 && count%3===0;
    for (let i=0;i+2<count;i+=3) {
      const triangle=[ids[index?index.getX(i):i],ids[index?index.getX(i+1):i+1],ids[index?index.getX(i+2):i+2]];
      if (new Set(triangle).size<3) { closed=false; break; }
      for (let edge=0;edge<3;edge++) {
        const a=triangle[edge], b=triangle[(edge+1)%3], key=a<b?`${a}:${b}`:`${b}:${a}`;
        edges.set(key,(edges.get(key)||0)+1);
      }
    }
    closed=closed && [...edges.values()].every(count=>count===2);
    closedMeshes.set(geometry,{positions,index,version:positions.version,indexVersion:index?index.version:0,closed});
    return closed;
  }
  function meshPointBlocked(object,point,radius) {
    let blocked=false;
    const clearance=radius+skin, ray=new THREE.Ray(point,new THREE.Vector3(.817,.391,.424).normalize());
    object.updateWorldMatrix(true,true);
    object.traverseVisible(mesh=>{
      if (blocked || !mesh.isMesh || !mesh.geometry) return;
      const geometry=mesh.geometry, positions=geometry.attributes.position;
      if (!positions) return;
      if (!geometry.boundingBox) geometry.computeBoundingBox();
      const bounds=geometry.boundingBox.clone().applyMatrix4(mesh.matrixWorld);
      if (bounds.distanceToPoint(point)>clearance) return;
      const index=geometry.index;
      const triangle=new THREE.Triangle(), closest=new THREE.Vector3(), hit=new THREE.Vector3(), crossings=[];
      const insideBounds=bounds.containsPoint(point);
      const inverse=new THREE.Matrix4().copy(mesh.matrixWorld).invert();
      const queryBox=new THREE.Box3(point.clone(),point.clone()).expandByScalar(clearance).applyMatrix4(inverse);
      const localRay=insideBounds?ray.clone().applyMatrix4(inverse):null;
      for (const i of triangleCandidates(geometry,queryBox,localRay)) {
        triangle.a.fromBufferAttribute(positions,index?index.getX(i):i).applyMatrix4(mesh.matrixWorld);
        triangle.b.fromBufferAttribute(positions,index?index.getX(i+1):i+1).applyMatrix4(mesh.matrixWorld);
        triangle.c.fromBufferAttribute(positions,index?index.getX(i+2):i+2).applyMatrix4(mesh.matrixWorld);
        triangle.closestPointToPoint(point,closest);
        if (closest.distanceToSquared(point)<=clearance*clearance) { blocked=true; return; }
        if (insideBounds && ray.intersectTriangle(triangle.a,triangle.b,triangle.c,false,hit)) crossings.push(hit.distanceTo(point));
      }
      // For closed meshes, an odd number of unique surface crossings means
      // the sphere center is inside. Deduplicate shared triangle edges.
      crossings.sort((a,b)=>a-b);
      let unique=0, previous=-Infinity;
      for (const distance of crossings) if (distance-previous>1e-6) { unique++; previous=distance; }
      if (unique%2 && isClosedMesh(geometry)) blocked=true;
    });
    return blocked;
  }
  // Slab intersection of a moving box center against a Minkowski-expanded
  // obstacle. Returns time of first contact within the frame, including
  // crossings whose end positions no longer overlap the thin obstacle.
  function sweepTime(start,end,box) {
    if (box.containsPoint(start)) return null; // depenetration handles this
    let enter=0,leave=1,normalAxis=null;
    for (const axis of ['x','y','z']) {
      const velocity=end[axis]-start[axis];
      if (Math.abs(velocity)<1e-10) {
        if (start[axis]<box.min[axis] || start[axis]>box.max[axis]) return null;
        continue;
      }
      let a=(box.min[axis]-start[axis])/velocity;
      let b=(box.max[axis]-start[axis])/velocity;
      if (a>b) [a,b]=[b,a];
      if (a>=enter) { enter=a; normalAxis=axis; }
      leave=Math.min(leave,b);
      if (enter>leave) return null;
    }
    return normalAxis && enter>=0 && enter<=1?{time:enter,axis:normalAxis}:null;
  }
  function constrain(root,geometry) {
    const started=performance.now(); stats.contacts=0; stats.sweptContacts=0; stats.unresolved=false;
    if (!stats.enabled || !geometry) { history.delete(root); stats.milliseconds=0; return; }
    geometry.computeBoundingBox(); root.updateMatrixWorld(true);
    worldBounds.copy(geometry.boundingBox).applyMatrix4(root.matrixWorld);
    if (worldBounds.min.y<floorY+skin) {
      correction.set(0,floorY+skin-worldBounds.min.y,0);
      root.position.add(correction); worldBounds.translate(correction); stats.contacts++;
    }
    const opponent=scene.getObjectByName('aether-opponent');
    const solids=colliders.filter(object=>object.visible && object.userData.collisionEnabled!==false);
    // Cache world bounds once per solve. Every sweep/slide/depenetration pass
    // uses the same collider snapshot, including the opponent body proxy.
    const solidBounds=solids.flatMap(object=>meshBounds(object).map(box=>box.expandByScalar(skin)));
    if (opponent) solidBounds.push(opponentBounds(opponent,new THREE.Box3()).expandByScalar(skin));
    const previous=history.get(root);
    let movingOpponent=false;
    const currentOpponentBounds=opponent?solidBounds[solidBounds.length-1]:null;
    if (previous && previous.geometry===geometry && opponent && previous.opponent===opponent && previous.opponentBounds) {
      const movement=currentOpponentBounds.getCenter(new THREE.Vector3()).sub(previous.opponentBounds.getCenter(new THREE.Vector3()));
      movingOpponent=movement.lengthSq()>1e-12;
      if (movingOpponent) {
        const start=previous.bounds.getCenter(new THREE.Vector3());
        const end=worldBounds.getCenter(new THREE.Vector3());
        const relativeEnd=end.clone().sub(movement);
        const extent=worldBounds.getSize(new THREE.Vector3()).max(previous.bounds.getSize(new THREE.Vector3())).multiplyScalar(.5);
        const hit=sweepTime(start,relativeEnd,previous.opponentBounds.clone().expandByVector(extent));
        if (hit && hit.time<1) {
          correction.set(0,0,0);
          correction[hit.axis]=start[hit.axis]+(relativeEnd[hit.axis]-start[hit.axis])*Math.max(0,hit.time-1e-5)+movement[hit.axis]-end[hit.axis];
          root.position.add(correction); worldBounds.translate(correction);
          stats.contacts++; stats.sweptContacts++;
        }
      }
    }
    if (previous && previous.geometry===geometry) {
      const start=previous.bounds.getCenter(new THREE.Vector3());
      const end=worldBounds.getCenter(new THREE.Vector3());
      const desired=end.clone();
      const extent=worldBounds.getSize(new THREE.Vector3()).max(previous.bounds.getSize(new THREE.Vector3())).multiplyScalar(.5);
      for (let slide=0;slide<4;slide++) {
        let first=null;
        for (const box of solidBounds) {
          // The moving proxy was solved in relative coordinates above;
          // treating its final box as static would select the wrong side.
          if (movingOpponent && box===currentOpponentBounds) continue;
          const expanded=box.clone().expandByVector(extent);
          const hit=sweepTime(start,end,expanded);
          if (hit && hit.time<1 && (!first || hit.time<first.time)) first=hit;
        }
        if (!first) break;
        // Move to contact, then remove only the blocked component of the
        // remaining displacement. Sweep again for corners and other solids.
        const contact=start.clone().lerp(end,Math.max(0,first.time-1e-5));
        const remaining=end.clone().sub(contact); remaining[first.axis]=0;
        start.copy(contact); end.copy(contact).add(remaining);
        stats.contacts++; stats.sweptContacts++;
        if (slide===3) { end.copy(start); stats.unresolved=true; }
      }
      correction.copy(end).sub(desired);
      root.position.add(correction); worldBounds.translate(correction);
    }
    // Resolve whole-body translations so the mesh and skeleton stay aligned.
    // Keep punches reachable: opponent uses the central body envelope, not
    // the animated hand/arm envelope. Static obstacles use separate mesh bounds.
    for (let pass=0;pass<8;pass++) {
      let hit=false;
      for (const box of solidBounds) {
        obstacleBounds.copy(box);
        if (!worldBounds.intersectsBox(obstacleBounds)) continue;
        const choices=[
          [obstacleBounds.min.x-worldBounds.max.x,0,0],
          [obstacleBounds.max.x-worldBounds.min.x,0,0],
          [0,0,obstacleBounds.min.z-worldBounds.max.z],
          [0,0,obstacleBounds.max.z-worldBounds.min.z]
        ];
        choices.sort((a,b)=>Math.hypot(...a)-Math.hypot(...b));
        correction.set(...choices[0]);
        if (correction.lengthSq()<1e-12) continue;
        root.position.add(correction); worldBounds.translate(correction);
        stats.contacts++; hit=true;
      }
      if (!hit) break;
      if (pass===7) stats.unresolved=true;
    }
    root.updateMatrixWorld(true); stats.milliseconds=performance.now()-started;
    history.set(root,{geometry,bounds:worldBounds.clone(),opponent,
      opponentBounds:currentOpponentBounds?currentOpponentBounds.clone():null});
    root.userData.collisionContacts=stats.contacts;
  }
  function updateDebug(root,geometry) {
    if (!debugGroup.visible) return;
    bodyHelper.visible=Boolean(root.visible && geometry);
    if (bodyHelper.visible) {
      geometry.computeBoundingBox(); root.updateMatrixWorld(true);
      bodyDebugBounds.copy(geometry.boundingBox).applyMatrix4(root.matrixWorld);
      bodyHelper.material.color.setHex(stats.contacts?0xf0576b:0x46d9ae);
    }
    const opponent=scene.getObjectByName('aether-opponent');
    opponentHelper.visible=Boolean(opponent);
    if (opponent) {
      opponentBounds(opponent,opponentDebugBounds);
    }
    for (const helper of debugGroup.children) if (helper.userData.sceneCollider) {
      const object=helper.userData.collider;
      helper.visible=object.visible && object.userData.collisionEnabled!==false;
      if (helper.userData.mesh) {
        const mesh=helper.userData.mesh;
        for (let node=mesh;node;node=node.parent) if (!node.visible) helper.visible=false;
        if (helper.visible) {
          mesh.updateWorldMatrix(true,false);
          if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
          helper.box.copy(mesh.geometry.boundingBox).applyMatrix4(mesh.matrixWorld);
        }
      } else if (helper.visible) helper.update();
    }
  }
  return {constrain,stats,queryStats,colliders,group,debugGroup,updateDebug,
    segmentBlocked(start,end,radius=0) {
      queryStats.candidates=0; queryStats.totalTriangles=0;
      if (![start.x,start.y,start.z,end.x,end.y,end.z,radius].every(Number.isFinite) || radius<0) return true;
      const direction=end.clone().sub(start), length=direction.length();
      if (length<1e-8) return radius>0 && colliders.some(object=>object.visible && object.userData.collisionEnabled!==false && meshPointBlocked(object,start,radius));
      const ray=new THREE.Ray(start,direction.multiplyScalar(1/length));
      for (const object of colliders) {
        if (!object.visible || object.userData.collisionEnabled===false) continue;
        if (radius===0) {
          let blocked=false;
          object.updateWorldMatrix(true,true);
          object.traverseVisible(mesh=>{
            if (blocked || !mesh.isMesh || !mesh.geometry) return;
            const geometry=mesh.geometry, positions=geometry.attributes.position;
            if (!positions) return;
            if (!geometry.boundingBox) geometry.computeBoundingBox();
            const localRay=ray.clone().applyMatrix4(new THREE.Matrix4().copy(mesh.matrixWorld).invert());
            if (!localRay.intersectsBox(geometry.boundingBox)) return;
            const index=geometry.index;
            const a=new THREE.Vector3(), b=new THREE.Vector3(), c=new THREE.Vector3(), contact=new THREE.Vector3();
            for (const i of triangleCandidates(geometry,null,localRay)) {
              a.fromBufferAttribute(positions,index?index.getX(i):i);
              b.fromBufferAttribute(positions,index?index.getX(i+1):i+1);
              c.fromBufferAttribute(positions,index?index.getX(i+2):i+2);
              if (localRay.intersectTriangle(a,b,c,false,contact) && contact.applyMatrix4(mesh.matrixWorld).distanceTo(start)<=length+1e-7) { blocked=true; break; }
            }
          });
          if (blocked) return true;
          continue;
        }
        if (meshPointBlocked(object,start,radius)) return true;
        let blocked=false; object.updateWorldMatrix(true,true);
        object.traverseVisible(mesh=>{
          if (blocked || !mesh.isMesh || !mesh.geometry) return;
          const geometry=mesh.geometry, positions=geometry.attributes.position;
          if (!positions) return;
          if (!geometry.boundingBox) geometry.computeBoundingBox();
          const clearance=radius+skin, bounds=geometry.boundingBox.clone().applyMatrix4(mesh.matrixWorld).expandByScalar(clearance);
          const contact=ray.intersectBox(bounds,new THREE.Vector3());
          if (!bounds.containsPoint(start) && (!contact || contact.distanceTo(start)>length)) return;
          const index=geometry.index;
          const triangle=new THREE.Triangle(), closest=new THREE.Vector3(), hit=new THREE.Vector3();
          const queryBox=new THREE.Box3().setFromPoints([start,end]).expandByScalar(clearance).applyMatrix4(new THREE.Matrix4().copy(mesh.matrixWorld).invert());
          for (const i of triangleCandidates(geometry,queryBox,null)) {
            triangle.a.fromBufferAttribute(positions,index?index.getX(i):i).applyMatrix4(mesh.matrixWorld);
            triangle.b.fromBufferAttribute(positions,index?index.getX(i+1):i+1).applyMatrix4(mesh.matrixWorld);
            triangle.c.fromBufferAttribute(positions,index?index.getX(i+2):i+2).applyMatrix4(mesh.matrixWorld);
            if (ray.intersectTriangle(triangle.a,triangle.b,triangle.c,false,hit) && hit.distanceTo(start)<=length+1e-7) { blocked=true; return; }
            triangle.closestPointToPoint(start,closest);
            let distance=closest.distanceToSquared(start);
            triangle.closestPointToPoint(end,closest); distance=Math.min(distance,closest.distanceToSquared(end),
              segmentDistanceSquared(start,end,triangle.a,triangle.b),segmentDistanceSquared(start,end,triangle.b,triangle.c),segmentDistanceSquared(start,end,triangle.c,triangle.a));
            if (distance<=clearance*clearance) { blocked=true; return; }
          }
        });
        if (blocked) return true;
      }
      return false;
    },
    pointBlocked(point,radius=0) {
      queryStats.candidates=0; queryStats.totalTriangles=0;
      if (![point.x,point.y,point.z,radius].every(Number.isFinite) || radius<0) return true;
      for (const object of colliders) if (object.visible && object.userData.collisionEnabled!==false && meshPointBlocked(object,point,radius)) return true;
      const opponent=scene.getObjectByName('aether-opponent');
      return Boolean(opponent && opponentBounds(opponent,new THREE.Box3()).distanceToPoint(point)<=radius+skin);
    },
    addCollider(object) {
      if (colliders.includes(object)) return;
      colliders.push(object); history=new WeakMap();
      object.traverse(mesh=>{
        if (!mesh.isMesh || !mesh.geometry) return;
        const helper=new THREE.Box3Helper(new THREE.Box3(),0x70aaff);
        helper.userData.sceneCollider=true; helper.userData.collider=object; helper.userData.mesh=mesh;
        helper.material.depthTest=false; helper.renderOrder=10; debugGroup.add(helper);
      });
    },
    removeCollider(object) {
      const index=colliders.indexOf(object); if (index<0) return;
      colliders.splice(index,1); history=new WeakMap();
      for (const helper of debugGroup.children.slice()) if (helper.userData.collider===object) {
        debugGroup.remove(helper); helper.geometry.dispose(); helper.material.dispose();
      }
    },
    resetAll() { history=new WeakMap(); },
    setDebug(on) { debugGroup.visible=Boolean(on); },
    reset(root) { history.delete(root); }};
};
