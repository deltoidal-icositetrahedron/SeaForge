import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

const LAND_GEOJSON_URL = '/ne_110m_admin_0_countries.geojson';
const RADIUS = 100;
const MARKER_RADIUS = 2.6;
const TEX_W = 2048;
const TEX_H = 1024;

const ORIGIN_COLOR = 0x1a7f37;
const DEST_COLOR = 0xb42318;
const WAYPOINT_COLOR = 0x1f4fd6;
const INVALID_COLOR = 0xd11616;

function geoToUnit(lonDeg, latDeg) {
  const lon = THREE.MathUtils.degToRad(lonDeg);
  const lat = THREE.MathUtils.degToRad(latDeg);
  const cosLat = Math.cos(lat);
  return new THREE.Vector3(cosLat * Math.sin(lon), Math.sin(lat), cosLat * Math.cos(lon)).normalize();
}

function unitToGeo(vec) {
  const v = vec.clone().normalize();
  return {
    lat: THREE.MathUtils.radToDeg(Math.asin(THREE.MathUtils.clamp(v.y, -1, 1))),
    lon: THREE.MathUtils.radToDeg(Math.atan2(v.x, v.z)),
  };
}

// Sphere geometry whose UVs follow the SAME lon/lat convention as geoToUnit, so the
// equirectangular land texture lines up exactly with marker placement. A raw
// THREE.SphereGeometry uses a different phi origin and would shift land ~90° in longitude
// relative to the markers (which is what made placed routes appear offset on the main globe).
function createGeoSphereGeometry(radius, lonSegments = 128, latSegments = 64) {
  const positions = [];
  const normals = [];
  const uvs = [];
  const indices = [];

  for (let latIndex = 0; latIndex <= latSegments; latIndex += 1) {
    const lat = 90 - (latIndex / latSegments) * 180;
    for (let lonIndex = 0; lonIndex <= lonSegments; lonIndex += 1) {
      const lon = -180 + (lonIndex / lonSegments) * 360;
      const u = geoToUnit(lon, lat);
      positions.push(u.x * radius, u.y * radius, u.z * radius);
      normals.push(u.x, u.y, u.z);
      uvs.push(lonIndex / lonSegments, 1 - latIndex / latSegments);
    }
  }

  for (let latIndex = 0; latIndex < latSegments; latIndex += 1) {
    for (let lonIndex = 0; lonIndex < lonSegments; lonIndex += 1) {
      const a = latIndex * (lonSegments + 1) + lonIndex;
      const b = a + lonSegments + 1;
      indices.push(a, b, a + 1, a + 1, b, b + 1);
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  geometry.setIndex(indices);
  geometry.computeBoundingSphere();
  return geometry;
}

function slerp(a, b, t) {
  const dot = THREE.MathUtils.clamp(a.dot(b), -1, 1);
  const omega = Math.acos(dot);
  if (omega < 1e-6) return a.clone().lerp(b, t).normalize();
  const sin = Math.sin(omega);
  return a.clone().multiplyScalar(Math.sin((1 - t) * omega) / sin)
    .add(b.clone().multiplyScalar(Math.sin(t * omega) / sin)).normalize();
}

// Compact equirectangular land fill, mapped onto the globe so users can place near real coasts.
function buildLandTexture(geoJson) {
  const canvas = document.createElement('canvas');
  canvas.width = TEX_W;
  canvas.height = TEX_H;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#aeb2b8';

  const drawRing = (ring, xOffset) => {
    let prevLon = null;
    let wrap = xOffset;
    let started = false;
    ring.forEach((coord) => {
      let lon = coord?.[0];
      const lat = coord?.[1];
      if (!Number.isFinite(lon) || !Number.isFinite(lat)) return;
      if (prevLon !== null) {
        while (lon - prevLon > 180) { lon -= 360; wrap += TEX_W; }
        while (lon - prevLon < -180) { lon += 360; wrap -= TEX_W; }
      }
      const x = ((lon + 180) / 360) * TEX_W + wrap;
      const y = ((90 - lat) / 180) * TEX_H;
      if (!started) { ctx.moveTo(x, y); started = true; } else { ctx.lineTo(x, y); }
      prevLon = lon;
    });
    if (started) ctx.closePath();
  };

  const polys = [];
  geoJson?.features?.forEach((f) => {
    const g = f.geometry;
    if (!g) return;
    if (g.type === 'Polygon') polys.push(g.coordinates);
    else if (g.type === 'MultiPolygon') g.coordinates.forEach((rings) => polys.push(rings));
  });

  polys.forEach((rings) => {
    [-TEX_W, 0, TEX_W].forEach((xOffset) => {
      ctx.beginPath();
      rings.forEach((ring) => drawRing(ring, xOffset));
      ctx.fill('evenodd');
    });
  });

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  return texture;
}

function markerColor(index, count) {
  if (index === 0) return ORIGIN_COLOR;
  if (index === count - 1 && count > 1) return DEST_COLOR;
  return WAYPOINT_COLOR;
}

export default function GlobePicker({ points, selectedIndex, onChange, onSelect, invalidPoints, invalidLegs }) {
  const emptySet = useRef(new Set()).current;
  const badPoints = invalidPoints ?? emptySet;
  const badLegs = invalidLegs ?? emptySet;
  const mountRef = useRef(null);
  // Refs keep the imperative Three.js event handlers reading current React state.
  const pointsRef = useRef(points);
  const selectedRef = useRef(selectedIndex);
  const onChangeRef = useRef(onChange);
  const onSelectRef = useRef(onSelect);
  const sceneRef = useRef(null);

  pointsRef.current = points;
  selectedRef.current = selectedIndex;
  onChangeRef.current = onChange;
  onSelectRef.current = onSelect;

  // One-time scene setup.
  useEffect(() => {
    const el = mountRef.current;
    if (!el) return undefined;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    const width = el.clientWidth || 460;
    const height = el.clientHeight || 320;
    renderer.setSize(width, height);
    renderer.domElement.style.touchAction = 'none';
    renderer.domElement.style.cursor = 'grab';
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(32, width / height, 0.1, 6000);
    camera.position.set(0, 60, RADIUS * 3.1);

    const globe = new THREE.Mesh(
      new THREE.SphereGeometry(RADIUS, 96, 48),
      new THREE.MeshBasicMaterial({ color: 0xbfc3c9, toneMapped: false }),
    );
    scene.add(globe);

    // Latitude/longitude graticule for orientation.
    const gridMat = new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.08, toneMapped: false });
    const grid = new THREE.Group();
    for (let lat = -60; lat <= 60; lat += 30) {
      const pts = [];
      for (let i = 0; i <= 128; i += 1) pts.push(geoToUnit(-180 + (i / 128) * 360, lat).multiplyScalar(RADIUS + 0.1));
      grid.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), gridMat));
    }
    for (let lon = -180; lon < 180; lon += 30) {
      const pts = [];
      for (let i = 0; i <= 128; i += 1) pts.push(geoToUnit(lon, -85 + (i / 128) * 170).multiplyScalar(RADIUS + 0.1));
      grid.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), gridMat));
    }
    scene.add(grid);

    const markerGroup = new THREE.Group();
    scene.add(markerGroup);
    const routeGroup = new THREE.Group();
    scene.add(routeGroup);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.1;
    controls.enablePan = false;
    controls.minDistance = RADIUS * 1.4;
    controls.maxDistance = RADIUS * 4.2;
    controls.rotateSpeed = 0.5;

    let landLayer = null;
    fetch(LAND_GEOJSON_URL)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('land geojson'))))
      .then((geoJson) => {
        const texture = buildLandTexture(geoJson);
        landLayer = new THREE.Mesh(
          createGeoSphereGeometry(RADIUS + 0.15),
          new THREE.MeshBasicMaterial({ map: texture, transparent: true, opacity: 0.55, depthWrite: false, side: THREE.DoubleSide, toneMapped: false }),
        );
        scene.add(landLayer);
      })
      .catch(() => {});

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let dragging = null;
    let hovering = null;

    const setPointer = (event) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.set(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1,
      );
    };

    const hitMarkerIndex = () => {
      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObjects(markerGroup.children, false);
      return hits.length ? hits[0].object.userData.index : null;
    };

    const onPointerMove = (event) => {
      setPointer(event);
      if (dragging !== null) {
        raycaster.setFromCamera(pointer, camera);
        const hit = raycaster.intersectObject(globe, false)[0];
        if (hit) {
          const geo = unitToGeo(hit.point);
          const next = pointsRef.current.map((p, i) => (
            i === dragging ? { ...p, lat: geo.lat, lon: geo.lon } : p
          ));
          onChangeRef.current(next);
        }
        return;
      }
      hovering = hitMarkerIndex();
      controls.enableRotate = hovering === null;
      renderer.domElement.style.cursor = hovering === null ? 'grab' : 'pointer';
    };

    const onPointerDown = (event) => {
      setPointer(event);
      const index = hitMarkerIndex();
      if (index !== null) {
        dragging = index;
        controls.enableRotate = false;
        renderer.domElement.style.cursor = 'grabbing';
        if (selectedRef.current !== index) onSelectRef.current(index);
      }
    };

    const endDrag = () => {
      if (dragging !== null) {
        dragging = null;
        controls.enableRotate = hovering === null;
        renderer.domElement.style.cursor = hovering === null ? 'grab' : 'pointer';
      }
    };

    renderer.domElement.addEventListener('pointermove', onPointerMove);
    renderer.domElement.addEventListener('pointerdown', onPointerDown);
    renderer.domElement.addEventListener('pointerup', endDrag);
    renderer.domElement.addEventListener('pointerleave', endDrag);

    let frameId;
    const loop = () => {
      frameId = requestAnimationFrame(loop);
      controls.update();
      renderer.render(scene, camera);
    };
    loop();

    const onResize = () => {
      const w = el.clientWidth || 460;
      const h = el.clientHeight || 320;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener('resize', onResize);

    sceneRef.current = { markerGroup, routeGroup, camera };

    return () => {
      cancelAnimationFrame(frameId);
      window.removeEventListener('resize', onResize);
      renderer.domElement.removeEventListener('pointermove', onPointerMove);
      renderer.domElement.removeEventListener('pointerdown', onPointerDown);
      renderer.domElement.removeEventListener('pointerup', endDrag);
      renderer.domElement.removeEventListener('pointerleave', endDrag);
      controls.dispose();
      scene.traverse((obj) => {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) {
          if (obj.material.map) obj.material.map.dispose();
          obj.material.dispose();
        }
      });
      renderer.dispose();
      if (el.contains(renderer.domElement)) el.removeChild(renderer.domElement);
      sceneRef.current = null;
    };
  }, []);

  // Sync markers + connecting route whenever the points or selection change.
  useEffect(() => {
    const ctx = sceneRef.current;
    if (!ctx) return;
    const { markerGroup, routeGroup } = ctx;

    while (markerGroup.children.length) {
      const child = markerGroup.children.pop();
      child.geometry.dispose();
      child.material.dispose();
    }
    while (routeGroup.children.length) {
      const child = routeGroup.children.pop();
      child.geometry.dispose();
      child.material.dispose();
    }

    points.forEach((p, index) => {
      const isSelected = index === selectedIndex;
      const onLand = badPoints.has(index);
      const color = onLand ? INVALID_COLOR : markerColor(index, points.length);
      const mesh = new THREE.Mesh(
        new THREE.SphereGeometry(MARKER_RADIUS * (isSelected || onLand ? 1.45 : 1), 20, 20),
        new THREE.MeshBasicMaterial({ color, toneMapped: false }),
      );
      mesh.position.copy(geoToUnit(p.lon, p.lat).multiplyScalar(RADIUS + 0.6));
      mesh.userData.index = index;
      markerGroup.add(mesh);
    });

    // One line per leg so legs that cross land can be drawn red.
    for (let i = 0; i < points.length - 1; i += 1) {
      const a = geoToUnit(points[i].lon, points[i].lat);
      const b = geoToUnit(points[i + 1].lon, points[i + 1].lat);
      const steps = 48;
      const arc = [];
      for (let s = 0; s <= steps; s += 1) {
        arc.push(slerp(a, b, s / steps).multiplyScalar(RADIUS + 0.4));
      }
      const bad = badLegs.has(i);
      routeGroup.add(new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(arc),
        new THREE.LineBasicMaterial({
          color: bad ? INVALID_COLOR : 0x1f4fd6,
          transparent: true,
          opacity: bad ? 0.95 : 0.7,
          toneMapped: false,
        }),
      ));
    }
  }, [points, selectedIndex, badPoints, badLegs]);

  return <div ref={mountRef} style={{ width: '100%', height: '100%' }} />;
}
