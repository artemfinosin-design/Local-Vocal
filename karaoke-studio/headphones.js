import * as THREE from '/vendor/three.module.min.js';

const host = document.getElementById('headphoneViewport');
const surface = document.getElementById('earcupSurface');

try {
  let reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const renderer = new THREE.WebGLRenderer({alpha: true, antialias: true, powerPreference: 'low-power'});
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;
  renderer.setClearColor(0x000000, 0);
  renderer.domElement.setAttribute('aria-hidden', 'true');
  host.append(renderer.domElement);
  host.classList.add('three-ready');
  const scene = new THREE.Scene();
  // Local studio softboxes provide broad reflections without remote HDR textures.
  const environmentScene=new THREE.Scene();environmentScene.background=new THREE.Color(0x202a31);
  for(const [x,y,z,width,height,color] of [[-4,2,1,3,5,0xb9d9e3],[4,3,2,3,6,0xffefe0],[0,5,0,7,3,0xffffff],[0,1,-5,4,2,0x59777f]]){
    const panel=new THREE.Mesh(new THREE.PlaneGeometry(width,height),new THREE.MeshBasicMaterial({color,side:THREE.DoubleSide}));
    panel.position.set(x,y,z);panel.lookAt(0,0,0);environmentScene.add(panel);
  }
  const pmrem=new THREE.PMREMGenerator(renderer);scene.environment=pmrem.fromScene(environmentScene,.025).texture;pmrem.dispose();
  const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 30);
  camera.position.set(0, 0.05, 5.9);
  camera.lookAt(0, -0.05, 0);
  scene.add(new THREE.HemisphereLight(0xe8f3ee, 0x252d34, 2.3));
  const light = (color, power, x, y, z) => {
    const lamp = new THREE.DirectionalLight(color, power);
    lamp.position.set(x, y, z);
    scene.add(lamp);
  };
  light(0xffffff, 3.7, 4, 4, 5);
  light(0xafd9e0, 2.6, -4, 1, 2);
  light(0xff985a, 3, -2, 3, -4);
  const material = (color, roughness, metalness) => new THREE.MeshStandardMaterial({color, roughness, metalness});
  const shell = new THREE.MeshPhysicalMaterial({color:0x152630,roughness:.32,metalness:.55,clearcoat:.45,clearcoatRoughness:.28});
  const bandMaterial = material(0x59666e, 0.32, 0.6);
  const cushion = material(0x10171d, 0.88, 0.04);
  const grainCanvas=document.createElement('canvas');grainCanvas.width=grainCanvas.height=128;
  const grain=grainCanvas.getContext('2d'),pixels=grain.createImageData(128,128);let seed=27;
  for(let i=0;i<pixels.data.length;i+=4){seed=(seed*1664525+1013904223)>>>0;const shade=95+(seed>>>26);pixels.data[i]=pixels.data[i+1]=pixels.data[i+2]=shade;pixels.data[i+3]=255;}
  grain.putImageData(pixels,0,0);const leather=new THREE.CanvasTexture(grainCanvas);leather.wrapS=leather.wrapT=THREE.RepeatWrapping;leather.repeat.set(5,5);cushion.bumpMap=leather;cushion.bumpScale=.004;
  const trim = material(0xff985a, 0.3, 0.45);
  const metal = material(0xa4b1b9, 0.22, 0.75);
  const group = new THREE.Group();
  scene.add(group);
  const mesh = (geometry, surface, parent = group) => {
    const object = new THREE.Mesh(geometry, surface);
    parent.add(object);
    return object;
  };
  const roundedShape=(width,height,radius)=>{
    const shape=new THREE.Shape(),x=-width/2,y=-height/2,r=radius;
    shape.moveTo(x+r,y);shape.lineTo(x+width-r,y);shape.quadraticCurveTo(x+width,y,x+width,y+r);
    shape.lineTo(x+width,y+height-r);shape.quadraticCurveTo(x+width,y+height,x+width-r,y+height);
    shape.lineTo(x+r,y+height);shape.quadraticCurveTo(x,y+height,x,y+height-r);
    shape.lineTo(x,y+r);shape.quadraticCurveTo(x,y,x+r,y);return shape;
  };
  const sculpted=(width,height,depth,radius,surface,parent)=>{
    const bevel=Math.min(.025,width*.15,height*.15,depth*.3);
    const geometry=new THREE.ExtrudeGeometry(roundedShape(width,height,radius),{depth,bevelEnabled:true,bevelSegments:5,steps:1,bevelSize:bevel,bevelThickness:bevel,curveSegments:16});
    geometry.translate(0,0,-depth/2);return mesh(geometry,surface,parent);
  };
  const arch = mesh(new THREE.TorusGeometry(1.06, 0.11, 18, 80, Math.PI), bandMaterial);
  arch.position.y = 0.15;
  const padding = mesh(new THREE.TorusGeometry(1.00, 0.085, 16, 80, Math.PI), cushion);
  padding.position.y = 0.13;
  arch.scale.z=.8;padding.scale.z=1.6;
  for (const z of [-0.085, 0.085]) {
    const edge = mesh(new THREE.TorusGeometry(1.065, 0.013, 8, 80, Math.PI), trim);
    edge.position.set(0, 0.15, z);
  }
  const badgeCanvas = document.createElement('canvas');
  badgeCanvas.width = badgeCanvas.height = 256;
  const context = badgeCanvas.getContext('2d');
  context.fillStyle = '#35434b'; context.fillRect(0, 0, 256, 256);
  context.fillStyle = '#dce4e7'; context.font = 'bold 72px Arial'; context.textAlign = 'center';
  context.fillText('SV', 128, 145);
  context.fillStyle = '#ff985a'; context.fillRect(93, 168, 70, 6);
  const badgeTexture = new THREE.CanvasTexture(badgeCanvas);
  badgeTexture.colorSpace = THREE.SRGBColorSpace;
  const badge = new THREE.MeshStandardMaterial({map: badgeTexture, roughness: 0.5, metalness: 0.2});
  const cups={};
  for (const side of [-1, 1]) {
    const stem = mesh(new THREE.CylinderGeometry(0.035, 0.035, 0.43, 16), metal);
    stem.position.set(side * 1.045, -0.06, 0);
    const cup = new THREE.Group();
    cup.position.set(side * 1.055, -0.39, 0);
    cups[side]=cup;
    group.add(cup);
    const cylinder = (radius, depth, surface, x) => {
      const geometry = new THREE.CylinderGeometry(radius, radius, depth, 64);
      geometry.scale(1.35, 1, 1);
      const object = mesh(geometry, surface, cup);
      object.rotation.z = Math.PI / 2;
      object.position.x = x;
      return object;
    };
    const body=sculpted(.64,.87,.28,.23,shell,cup);body.rotation.y=Math.PI/2;
    const backplate=sculpted(.60,.82,.014,.21,bandMaterial,cup);backplate.rotation.y=Math.PI/2;backplate.position.x=side*.15;
    const face=sculpted(.56,.78,.008,.19,shell,cup);face.rotation.y=Math.PI/2;face.position.x=side*.168;
    cylinder(0.30, 0.13, cushion, side * -0.19);
    const outline=roundedShape(.60,.82,.21).getPoints(80).map(p=>new THREE.Vector3(side*.176,p.y,p.x));
    const rim = mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(outline,true),120,.005,8,true),trim,cup);
    const pad = mesh(new THREE.TorusGeometry(0.245, 0.065, 18, 64), cushion, cup);
    pad.rotation.y = Math.PI / 2; pad.scale.y = 1.4; pad.position.x = side * -0.28;
    const logo = mesh(new THREE.CircleGeometry(0.25, 64), badge, cup);
    cup.userData.logo=logo;
    logo.rotation.y = side * Math.PI / 2; logo.scale.y = 1.35; logo.position.x = side * 0.162;
    const led = mesh(new THREE.SphereGeometry(0.025, 12, 12), trim, cup);
    led.position.set(side * 0.18, -0.29, 0.18);
    led.material=new THREE.MeshStandardMaterial({color:0xffa567,emissive:0xff7c31,emissiveIntensity:1.8});
    // Forged fork and hinge give the cups a physical attachment to the headband.
    const fork=new THREE.CatmullRomCurve3([new THREE.Vector3(0,.47,0),new THREE.Vector3(0,.40,.28),new THREE.Vector3(0,.06,.35),new THREE.Vector3(0,-.13,.32)]);
    mesh(new THREE.TubeGeometry(fork,28,.023,10,false),metal,cup);
    for(const z of [-.31,.31]){
      const hinge=mesh(new THREE.CylinderGeometry(.045,.045,.055,24),bandMaterial,cup);
      hinge.rotation.x=Math.PI/2;hinge.position.set(0,-.03,z);
      const screw=mesh(new THREE.CylinderGeometry(.019,.019,.058,16),metal,cup);
      screw.rotation.x=Math.PI/2;screw.position.copy(hinge.position);
    }
    for(let i=0;i<7;i++){
      const vent=sculpted(.009,.09,.002,.004,cushion,cup);
      vent.rotation.y=Math.PI/2;vent.position.set(side*.179,-.24,(i-3)*.025);
    }
    const socket=mesh(new THREE.CylinderGeometry(.022,.022,.028,20),metal,cup);
    socket.position.set(0,-.46,.02);
    for (let i = 0; i < 32; i++) {
      const angle = i / 32 * Math.PI * 2;
      const stitch = mesh(new THREE.SphereGeometry(0.004, 6, 4), bandMaterial, cup);
      stitch.position.set(side * -0.329, Math.sin(angle) * 0.34, Math.cos(angle) * 0.245);
    }
  }
  const cable = new THREE.CatmullRomCurve3([
    new THREE.Vector3(-1.05, -0.85, 0), new THREE.Vector3(-1.10, -1.10, 0.08),
    new THREE.Vector3(-0.9, -1.35, 0.1), new THREE.Vector3(-0.45, -1.39, 0.15),
    new THREE.Vector3(-0.05, -1.30, 0.17), new THREE.Vector3(0.03, -1.45, 0.19)
  ]);
  mesh(new THREE.TubeGeometry(cable, 48, 0.019, 8, false), cushion);
  const floor = mesh(new THREE.TorusGeometry(1.48, 0.008, 6, 100), new THREE.MeshBasicMaterial({color: 0x87996b, transparent: true, opacity: 0.25}), scene);
  floor.rotation.x = Math.PI / 2; floor.position.y = -1.48;
  group.rotation.set(0,0,0);
  const cameraGoal=new THREE.Vector3(),lookGoal=new THREE.Vector3(),looking=new THREE.Vector3();
  let stage='upload',side=-1,visible=true,last=0,cameraAngle=0,cameraRadius=5.9;
  let screenWidth=700,screenHeight=650,planeWidth=.64,planeHeight=.64;
  function targets() {
    if(stage==='listen'){cameraGoal.set(0,.05,Math.max(4.8,1.7/(Math.tan(Math.PI/10)*camera.aspect)));lookGoal.set(0,-.05,0);return;}
    const distance=planeHeight*host.clientHeight/(2*Math.tan(THREE.MathUtils.degToRad(camera.fov/2))*screenHeight);
    cameraGoal.set(side*(1.24+distance),-.39,.001);lookGoal.set(side*1.24,-.39,0);
  }
  function resize() {
    const width=host.clientWidth,height=host.clientHeight;if(!width||!height)return;
    renderer.setSize(width,height,false);camera.aspect=width/height;camera.updateProjectionMatrix();
    screenWidth=Math.min(740,width-60);screenHeight=height-72;planeWidth=planeHeight*screenWidth/screenHeight;
    for(const cup of Object.values(cups)){cup.scale.z=stage==='listen'?1:Math.max(1,planeWidth/.5*1.1);cup.userData.logo.visible=stage==='listen';}
    targets();
    if(stage!=='listen'){surface.style.width=screenWidth+'px';surface.style.height=screenHeight+'px';}
  }
  function setStage(detail,initial=false) {
    stage=detail.stage;side=stage==='upload'?-1:detail.side?1:-1;
    const bounds=host.getBoundingClientRect();visible=bounds.bottom>0&&bounds.top<innerHeight;
    resize();targets();
    if(stage==='listen'){surface.style.transform='';surface.style.width='';surface.style.height='';surface.style.opacity='1';surface.style.pointerEvents='';surface.inert=false;}
    if(initial||reduced){cameraAngle=Math.atan2(cameraGoal.x,cameraGoal.z);cameraRadius=Math.hypot(cameraGoal.x,cameraGoal.z);camera.position.copy(cameraGoal);looking.copy(lookGoal);}
  }
  reduced=reduced||!!window.studioAppearance?.calm;
  addEventListener('studio-appearance',()=>{reduced=matchMedia('(prefers-reduced-motion: reduce)').matches||!!window.studioAppearance?.calm;});
  addEventListener('studio-stage',event=>setStage(event.detail));
  function projectSurface() {
    if(stage==='listen')return;
    scene.updateMatrixWorld(true);camera.updateMatrixWorld(true);
    const cup=cups[side];
    const point=(u,v)=>new THREE.Vector4(side*.18,(.5-v)*planeHeight,-side*(u-.5)*planeWidth/cup.scale.z,1).applyMatrix4(cup.matrixWorld).applyMatrix4(camera.matrixWorldInverse).applyMatrix4(camera.projectionMatrix);
    const a=point(0,0),b=point(1,0).sub(a).multiplyScalar(1/screenWidth),c=point(0,1).sub(a).multiplyScalar(1/screenHeight);
    const center=cup.getWorldPosition(new THREE.Vector3()),normal=new THREE.Vector3(side,0,0).transformDirection(cup.matrixWorld);
    const facing=normal.dot(camera.position.clone().sub(center).normalize());
    if(a.w<=0||facing<.15){surface.style.opacity='0';surface.inert=true;return;}
    const w=host.clientWidth/2,h=host.clientHeight/2,d=a.w;
    // Clip coordinates form a homography: the DOM plane shares the model's perspective.
    const matrix=[w*(b.x+b.w)/d,h*(-b.y+b.w)/d,0,b.w/d,w*(c.x+c.w)/d,h*(-c.y+c.w)/d,0,c.w/d,0,0,1,0,w*(a.x+a.w)/d,h*(-a.y+a.w)/d,0,1];
    surface.style.transform='matrix3d('+matrix.join(',')+')';surface.style.opacity=String(Math.min(1,(facing-.15)/.45));
    const moving=Math.abs(cameraAngle-Math.atan2(cameraGoal.x,cameraGoal.z))>.04;
    surface.inert=moving;surface.style.pointerEvents=moving?'none':'auto';
  }
  function render(time) {
    requestAnimationFrame(render);
    if(!visible){last=0;return;}
    const dt=last?Math.min((time-last)/1000,.1):1/60;last=time;
    const speed=reduced?1:1-Math.exp(-dt*9);
    cameraAngle+=(Math.atan2(cameraGoal.x,cameraGoal.z)-cameraAngle)*speed;
    cameraRadius+=(Math.hypot(cameraGoal.x,cameraGoal.z)-cameraRadius)*speed;
    camera.position.set(Math.sin(cameraAngle)*cameraRadius,camera.position.y+(cameraGoal.y-camera.position.y)*speed,Math.cos(cameraAngle)*cameraRadius);
    looking.lerp(lookGoal,speed);camera.lookAt(looking);renderer.render(scene,camera);projectSurface();
  }
  new ResizeObserver(resize).observe(host);
  new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;}).observe(host);
  addEventListener('studio-accent',event=>trim.color.set(event.detail));
  trim.color.set(getComputedStyle(document.documentElement).getPropertyValue('--accent').trim());
  setStage(window.studioStage||{stage:'upload',side:0},true);requestAnimationFrame(render);
} catch(error) {
  host.classList.remove('three-ready');document.getElementById('sessionStage').classList.add('model-fallback');
  surface.style.cssText='';surface.inert=false;
  console.warn('3D недоступно; используется обычный рабочий экран.',error.message);
}
