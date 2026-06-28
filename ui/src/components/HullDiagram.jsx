import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

// Route in Three.js world space (Norfolk → Bermuda)
const NORFOLK = new THREE.Vector3(0, 0, 0);
const BERMUDA = new THREE.Vector3(48, 0, -62);
const ROUTE_DIR = BERMUDA.clone().sub(NORFOLK).normalize();
const HEADING = Math.atan2(ROUTE_DIR.x, ROUTE_DIR.z);
const ROUTE_MIDPOINT = NORFOLK.clone().lerp(BERMUDA, 0.5);
const ROUTE_RIGHT = new THREE.Vector3(1, 0, 0).applyAxisAngle(new THREE.Vector3(0, 1, 0), HEADING);

const GRID_SIZE = 180;
const GRID_DIVISIONS = 40;
const GRID_LINE_WIDTH = 0.04;
const GRID_SHADOW_LINE_WIDTH = 0.13;
const GRID_LINE_OPACITY = 0.095;
// const GRID_SHADOW_OPACITY = 0.045;
const GRID_SHADOW_OPACITY = 0.015;
export const DEFAULT_GRID_ROTATION_DEG = 67;
const ROUTE_LINE_Y = 0.035;
const ROUTE_TRAVERSED_COLOR = 0x000000;
const ROUTE_REMAINING_COLOR = 0x0000FF;
const ROUTE_LINE_OPACITY = 0.68;

function createShipShadowTexture() {
  const size = 512;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');

  const gradient = ctx.createRadialGradient(
    size * 0.5,
    size * 0.5,
    size * 0.08,
    size * 0.5,
    size * 0.5,
    size * 0.48,
  );
  gradient.addColorStop(0, 'rgba(30, 38, 46, 0.52)');
  gradient.addColorStop(0.38, 'rgba(30, 38, 46, 0.30)');
  gradient.addColorStop(0.72, 'rgba(30, 38, 46, 0.10)');
  gradient.addColorStop(1, 'rgba(30, 38, 46, 0)');

  ctx.fillStyle = gradient;
  ctx.beginPath();
  ctx.ellipse(size * 0.5, size * 0.5, size * 0.44, size * 0.30, 0, 0, Math.PI * 2);
  ctx.fill();

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function createGridMesh(size, divisions, lineWidth, color, opacity, options = {}) {
  const { includeXLines = true, includeZLines = true } = options;
  const group = new THREE.Group();
  const material = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity,
    depthWrite: false,
    toneMapped: false,
  });
  const step = size / divisions;
  const half = size / 2;
  const xLineGeo = new THREE.PlaneGeometry(size, lineWidth);
  const zLineGeo = new THREE.PlaneGeometry(lineWidth, size);

  for (let i = 0; i <= divisions; i += 1) {
    const p = -half + i * step;

    if (includeXLines) {
      const xLine = new THREE.Mesh(xLineGeo, material);
      xLine.rotation.x = -Math.PI / 2;
      xLine.position.z = p;
      group.add(xLine);
    }

    if (includeZLines) {
      const zLine = new THREE.Mesh(zLineGeo, material);
      zLine.rotation.x = -Math.PI / 2;
      zLine.position.x = p;
      group.add(zLine);
    }
  }

  return group;
}

export default function HullDiagram({ simResult, progress: tickProgress = null, gridRotationDeg = DEFAULT_GRID_ROTATION_DEG }) {
  const mountRef = useRef(null);
  const stateRef = useRef({});
  const progress = Number.isFinite(tickProgress)
    ? Math.max(0, Math.min(tickProgress, 1))
    : Math.min((simResult?.result?.distance_completed_pct ?? 0) / 100, 1);

  // Three.js scene setup
  useEffect(() => {
    const el = mountRef.current;
    if (!el) return;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.03;
    renderer.setSize(el.clientWidth, el.clientHeight);
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color('#C3C4CA');

    // Camera — positioned perpendicular-right of the route, orbiting around the ship.
    const cameraOffset = new THREE.Vector3(55, 65, 43);
    const shipFocus = NORFOLK.clone();
    const cam = new THREE.PerspectiveCamera(32, el.clientWidth / el.clientHeight, 0.1, 1000);
    cam.position.copy(shipFocus).add(cameraOffset);
    cam.lookAt(shipFocus);

    const controls = new OrbitControls(cam, renderer.domElement);
    controls.target.copy(shipFocus);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.enablePan = false;
    controls.minDistance = 12;
    controls.maxDistance = 180;
    controls.maxPolarAngle = Math.PI * 0.48;
    controls.rotateSpeed = 0.65;
    controls.zoomSpeed = 0.85;
    controls.panSpeed = 0.75;
    controls.mouseButtons = {
      LEFT: THREE.MOUSE.ROTATE,
      MIDDLE: THREE.MOUSE.DOLLY,
      RIGHT: THREE.MOUSE.ROTATE,
    };
    controls.update();

    renderer.domElement.style.cursor = 'grab';
    renderer.domElement.style.touchAction = 'none';
    const setGrabbing = () => { renderer.domElement.style.cursor = 'grabbing'; };
    const setGrab = () => { renderer.domElement.style.cursor = 'grab'; };
    const blockContextMenu = (event) => event.preventDefault();
    renderer.domElement.addEventListener('pointerdown', setGrabbing);
    renderer.domElement.addEventListener('pointerup', setGrab);
    renderer.domElement.addEventListener('pointerleave', setGrab);
    renderer.domElement.addEventListener('contextmenu', blockContextMenu);

    // Lights
    scene.add(new THREE.AmbientLight('#ffffff', 0.95));
    scene.add(new THREE.HemisphereLight('#f5f8fb', '#b8c0c8', 0.42));
    const sun = new THREE.DirectionalLight('#ffffff', 2.8);
    sun.position.copy(ROUTE_MIDPOINT).add(ROUTE_RIGHT.clone().multiplyScalar(30));
    sun.position.y = 72;
    sun.target.position.copy(ROUTE_MIDPOINT);
    scene.add(sun.target);
    sun.castShadow = true;
    sun.shadow.mapSize.set(4096, 4096);
    sun.shadow.radius = 10;
    sun.shadow.bias = -0.00012;
    sun.shadow.normalBias = 0.02;
    Object.assign(sun.shadow.camera, { left: -120, right: 120, top: 120, bottom: -120, far: 300 });
    scene.add(sun);
    const fill = new THREE.DirectionalLight('#b0c8e8', 0.18);
    fill.position.set(-30, 20, -30);
    scene.add(fill);

    // Grid
    const gridGroup = new THREE.Group();
    gridGroup.position.set(24, 0, -31);
    gridGroup.rotation.y = THREE.MathUtils.degToRad(gridRotationDeg);
    scene.add(gridGroup);

    const gridShadowOffset = ROUTE_RIGHT.clone().multiplyScalar(-0.6);
    const horizontalGridShadow = createGridMesh(
      GRID_SIZE,
      GRID_DIVISIONS,
      GRID_SHADOW_LINE_WIDTH,
      0x000000,
      GRID_SHADOW_OPACITY,
      { includeZLines: false },
    );
    horizontalGridShadow.position.set(gridShadowOffset.x, 0.008, gridShadowOffset.z);
    gridGroup.add(horizontalGridShadow);

    const verticalGridShadow = createGridMesh(
      GRID_SIZE,
      GRID_DIVISIONS,
      GRID_LINE_WIDTH,
      0x000000,
      GRID_SHADOW_OPACITY,
      { includeXLines: false },
    );
    verticalGridShadow.position.set(0, 0.008, 0);
    gridGroup.add(verticalGridShadow);

    const grid = createGridMesh(GRID_SIZE, GRID_DIVISIONS, GRID_LINE_WIDTH, 0x000000, GRID_LINE_OPACITY);
    grid.position.set(0, 0.01, 0);
    gridGroup.add(grid);

    // Shadow ground
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(200, 200),
      new THREE.ShadowMaterial({ color: 0x26313c, opacity: 0.08 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.01;
    ground.receiveShadow = true;
    scene.add(ground);

    // Route line: traversed portion is black; remaining route is yellow.
    const routeStart = NORFOLK.clone();
    routeStart.y = ROUTE_LINE_Y;
    const routeEnd = BERMUDA.clone();
    routeEnd.y = ROUTE_LINE_Y;
    const remainingRouteLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([routeStart.clone(), routeEnd.clone()]),
      new THREE.LineBasicMaterial({
        color: ROUTE_REMAINING_COLOR,
        opacity: ROUTE_LINE_OPACITY,
        transparent: true,
        linewidth: 1,
      }),
    );
    remainingRouteLine.frustumCulled = false;
    scene.add(remainingRouteLine);
    const traversedRouteLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([routeStart.clone(), routeStart.clone()]),
      new THREE.LineBasicMaterial({
        color: ROUTE_TRAVERSED_COLOR,
        opacity: ROUTE_LINE_OPACITY,
        transparent: true,
        linewidth: 1,
      }),
    );
    traversedRouteLine.frustumCulled = false;
    traversedRouteLine.visible = false;
    scene.add(traversedRouteLine);

    // Waypoint dots
    const dotGeo = new THREE.SphereGeometry(0.4, 12, 12);
    const dotA = new THREE.Mesh(dotGeo, new THREE.MeshBasicMaterial({ color: ROUTE_TRAVERSED_COLOR, opacity: 0.4, transparent: true }));
    dotA.position.copy(NORFOLK);
    scene.add(dotA);
    const dotB = new THREE.Mesh(dotGeo, new THREE.MeshBasicMaterial({ color: ROUTE_REMAINING_COLOR, opacity: 0.4, transparent: true }));
    dotB.position.copy(BERMUDA);
    scene.add(dotB);

    // Ship group (placeholder until STL loads)
    const shipGroup = new THREE.Group();
    shipGroup.position.copy(NORFOLK);
    shipGroup.rotation.y = HEADING;
    scene.add(shipGroup);

    const shipShadow = new THREE.Mesh(
      new THREE.PlaneGeometry(1, 1),
      new THREE.MeshBasicMaterial({
        map: createShipShadowTexture(),
        transparent: true,
        opacity: 0.48,
        depthWrite: false,
        toneMapped: false,
      }),
    );
    shipShadow.rotation.x = -Math.PI / 2;
    shipShadow.position.set(-0.85, 0.018, -0.2);
    shipShadow.scale.set(3.2, 8.4, 1);
    shipShadow.renderOrder = 1;
    shipGroup.add(shipShadow);

    // Load STL model
    const loader = new STLLoader();
    loader.load('/CorsairModelv2.stl', (geo) => {
      geo.computeVertexNormals();
      geo.computeBoundingBox();
      const box = geo.boundingBox;
      const size = new THREE.Vector3();
      box.getSize(size);
      const center = new THREE.Vector3();
      box.getCenter(center);

      // STL axes: X = length (bow→stern), Y = beam, Z = height (Z-up, min=0 at keel)
      // Center X and Y; leave Z min at 0 so keel sits on ground after rotation
      geo.translate(-center.x, -center.y, -box.min.z);

      // Scale: X is the longest axis (ship length ≈ 7779 mm) → 6 world units
      const scale = 6 / size.x;

      const mat = new THREE.MeshStandardMaterial({
        color: '#6f7d89',
        emissive: '#1d252c',
        emissiveIntensity: 0.08,
        metalness: 0.12,
        roughness: 0.72,
      });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.scale.setScalar(scale);
      mesh.castShadow = true;
      mesh.receiveShadow = true;

      // Align STL axes to the ship group:
      // STL +X is the bow, STL +Z is up. The group uses +Z as forward so
      // HEADING can rotate the vessel down the route.
      mesh.rotation.set(-Math.PI / 2, 0, -Math.PI / 2);

      shipGroup.add(mesh);
      stateRef.current.shipMesh = mesh;
    });

    stateRef.current = {
      ...stateRef.current,
      renderer, scene, cam, controls, shipGroup, shipFocus, gridGroup, traversedRouteLine, remainingRouteLine,
    };

    // Resize
    const onResize = () => {
      renderer.setSize(el.clientWidth, el.clientHeight);
      cam.aspect = el.clientWidth / el.clientHeight;
      cam.updateProjectionMatrix();
    };
    window.addEventListener('resize', onResize);

    // Render loop
    let frameId;
    const loop = () => {
      frameId = requestAnimationFrame(loop);
      controls.update();
      renderer.render(scene, cam);
    };
    loop();

    return () => {
      cancelAnimationFrame(frameId);
      window.removeEventListener('resize', onResize);
      renderer.domElement.removeEventListener('pointerdown', setGrabbing);
      renderer.domElement.removeEventListener('pointerup', setGrab);
      renderer.domElement.removeEventListener('pointerleave', setGrab);
      renderer.domElement.removeEventListener('contextmenu', blockContextMenu);
      controls.dispose();
      renderer.dispose();
      if (el.contains(renderer.domElement)) el.removeChild(renderer.domElement);
    };
  }, []);

  useEffect(() => {
    const { gridGroup } = stateRef.current;
    if (!gridGroup) return;
    gridGroup.rotation.y = THREE.MathUtils.degToRad(gridRotationDeg);
  }, [gridRotationDeg]);

  // Update ship position on progress change
  useEffect(() => {
    const { shipGroup, controls, cam, shipFocus, traversedRouteLine, remainingRouteLine } = stateRef.current;
    if (!shipGroup) return;

    const routeProgress = Math.max(0, Math.min(progress, 1));
    const pos = NORFOLK.clone().lerp(BERMUDA, routeProgress);
    shipGroup.position.set(pos.x, 0, pos.z);
    const routePos = pos.clone();
    routePos.y = ROUTE_LINE_Y;
    const routeStart = NORFOLK.clone();
    routeStart.y = ROUTE_LINE_Y;
    const routeEnd = BERMUDA.clone();
    routeEnd.y = ROUTE_LINE_Y;
    if (traversedRouteLine && remainingRouteLine) {
      traversedRouteLine.geometry.setFromPoints([routeStart, routePos]);
      remainingRouteLine.geometry.setFromPoints([routePos, routeEnd]);
      traversedRouteLine.visible = routeProgress > 0.001;
      remainingRouteLine.visible = routeProgress < 0.999;
      traversedRouteLine.geometry.computeBoundingSphere();
      remainingRouteLine.geometry.computeBoundingSphere();
    }
    if (controls && cam && shipFocus) {
      const delta = pos.clone().sub(shipFocus);
      cam.position.add(delta);
      controls.target.copy(pos);
      shipFocus.copy(pos);
      controls.update();
    }
  }, [progress]);

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden' }}>
      <div ref={mountRef} style={{ width: '100%', height: '100%' }} />
    </div>
  );
}
