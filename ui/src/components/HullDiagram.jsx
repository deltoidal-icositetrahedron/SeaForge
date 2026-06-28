import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';

// Route in Three.js world space (Norfolk → Bermuda)
const NORFOLK = new THREE.Vector3(0, 0, 0);
const BERMUDA = new THREE.Vector3(48, 0, -62);
const ROUTE_DIR = BERMUDA.clone().sub(NORFOLK).normalize();
const HEADING = Math.atan2(ROUTE_DIR.x, ROUTE_DIR.z);

export default function HullDiagram({ simResult }) {
  const mountRef = useRef(null);
  const stateRef = useRef({});
  const [progress, setProgress] = useState(0);
  const rafRef = useRef(null);

  const targetPct = simResult
    ? Math.min((simResult.result?.distance_completed_pct ?? 0) / 100, 1)
    : 0;

  // Animate progress 0 → targetPct over 4s
  useEffect(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    setProgress(0);
    if (!simResult) return;
    const DUR = 4000;
    const t0  = Date.now();
    const tick = () => {
      const t    = Math.min((Date.now() - t0) / DUR, 1);
      const ease = t < .5 ? 2*t*t : -1+(4-2*t)*t;
      setProgress(ease * targetPct);
      if (t < 1) rafRef.current = requestAnimationFrame(tick);
    };
    const id = setTimeout(() => { rafRef.current = requestAnimationFrame(tick); }, 200);
    return () => { clearTimeout(id); if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [simResult, targetPct]);

  // Three.js scene setup
  useEffect(() => {
    const el = mountRef.current;
    if (!el) return;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.setSize(el.clientWidth, el.clientHeight);
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color('#eaecef');

    // Camera — positioned perpendicular-right of the Norfolk→Bermuda route
    // Route direction XZ: (0.612, -0.790). Perpendicular-right: (0.790, 0.612).
    // Camera = midpoint(24,0,-31) + perp*70 + up*65
    const cam = new THREE.PerspectiveCamera(32, el.clientWidth / el.clientHeight, 0.1, 1000);
    cam.position.set(24 + 55, 65, -31 + 43);  // (79, 65, 12)
    cam.lookAt(24, 0, -31);

    // Lights
    scene.add(new THREE.AmbientLight('#ffffff', 1.6));
    const sun = new THREE.DirectionalLight('#ffffff', 2.0);
    sun.position.set(40, 80, 40);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -120, right: 120, top: 120, bottom: -120, far: 300 });
    scene.add(sun);
    const fill = new THREE.DirectionalLight('#b0c8e8', 0.5);
    fill.position.set(-30, 20, -30);
    scene.add(fill);

    // Grid
    const grid = new THREE.GridHelper(180, 40, 0x000000, 0x000000);
    grid.material.opacity = 0.07;
    grid.material.transparent = true;
    grid.position.set(24, 0, -31);
    scene.add(grid);

    // Shadow ground
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(200, 200),
      new THREE.ShadowMaterial({ opacity: 0.08 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    scene.add(ground);

    // Route line
    const routeGeo = new THREE.BufferGeometry().setFromPoints([NORFOLK.clone(), BERMUDA.clone()]);
    const routeLine = new THREE.Line(routeGeo,
      new THREE.LineDashedMaterial({ color: 0x000000, opacity: 0.1, transparent: true, dashSize: 2, gapSize: 1.5 }),
    );
    routeLine.computeLineDistances();
    scene.add(routeLine);

    // Waypoint dots
    const dotGeo = new THREE.SphereGeometry(0.4, 12, 12);
    const dotA = new THREE.Mesh(dotGeo, new THREE.MeshBasicMaterial({ color: 0x000000, opacity: 0.25, transparent: true }));
    dotA.position.copy(NORFOLK);
    scene.add(dotA);
    const dotB = new THREE.Mesh(dotGeo, new THREE.MeshBasicMaterial({ color: 0x008844, opacity: 0.35, transparent: true }));
    dotB.position.copy(BERMUDA);
    scene.add(dotB);

    // Ship group (placeholder until STL loads)
    const shipGroup = new THREE.Group();
    shipGroup.position.copy(NORFOLK);
    shipGroup.rotation.y = HEADING;
    scene.add(shipGroup);

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
      renderer, scene, cam, shipGroup,
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
      renderer.render(scene, cam);
    };
    loop();

    return () => {
      cancelAnimationFrame(frameId);
      window.removeEventListener('resize', onResize);
      renderer.dispose();
      if (el.contains(renderer.domElement)) el.removeChild(renderer.domElement);
    };
  }, []);

  // Update ship position on progress change
  useEffect(() => {
    const { shipGroup } = stateRef.current;
    if (!shipGroup) return;

    const pos = NORFOLK.clone().lerp(BERMUDA, progress);
    shipGroup.position.set(pos.x, 0, pos.z);
  }, [progress]);

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden' }}>
      <div ref={mountRef} style={{ width: '100%', height: '100%' }} />
    </div>
  );
}
