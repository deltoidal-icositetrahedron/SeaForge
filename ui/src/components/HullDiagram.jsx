import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

// Route in Three.js world space (point A -> point B)
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
const LAND_Y = 0.004;
const LAND_GEOJSON_URL = '/ne_110m_admin_0_countries.geojson';
const ZONE_LABEL_WIDTH = 166;
const ZONE_LABEL_HEIGHT = 52;
const ZONE_LABEL_GAP = 8;
const ZONE_LABEL_CLEARANCE_PX = 68;
const ZONE_LABEL_BEND_PX = 44;
const ZONE_LABEL_MIN_BEND_PX = 18;
const ZONE_LABEL_MIN_HORIZONTAL_RUN_PX = 58;
const ZONE_LABEL_MIN_DIAGONAL_Y_PX = 6;
const ZONE_LABEL_VIEWPORT_MARGIN = 12;
const ZONE_LABEL_BORDER_COLOR = 'rgba(0,0,0,0.13)';
const ZONE_OVERLAY_ANIMATION_MS = 140;
const ZONE_OVERLAY_HIDDEN_OFFSET_PX = 3;
const CAMERA_MIN_DISTANCE = 24;

const SHIP_SCREEN_BOUNDS_POINTS = [
  [-1.08, 0.08, -2.9],
  [1.08, 0.08, -2.9],
  [-1.08, 0.55, 0],
  [1.08, 0.55, 0],
  [-0.82, 0.38, 2.9],
  [0.82, 0.38, 2.9],
  [0, 1.18, -1.1],
  [0, 1.02, 1.5],
];

const ZONE_ANCHORS = {
  Keel: { anchor: [0, 0.10, 0], fallbackSide: 'bottom' },
  'Bilge Strake': { anchor: [-0.86, 0.34, -0.05], fallbackSide: 'bottom' },
  'Bottom Plating': { anchor: [0.05, 0.13, -0.72], fallbackSide: 'left' },
  'Side Plating': { anchor: [0.88, 0.42, 0.04], fallbackSide: 'top' },
  'Bow Flare': { anchor: [0.20, 0.58, 2.18], fallbackSide: 'right' },
  'Stern Plate': { anchor: [-0.10, 0.42, -2.34], fallbackSide: 'left' },
  'Transom Frame': { anchor: [-0.32, 0.60, -2.55], fallbackSide: 'left' },
  'Weather Deck': { anchor: [0, 0.86, 0.36], fallbackSide: 'top' },
  'Bulkhead Frame': { anchor: [0.36, 0.68, -1.10], fallbackSide: 'top' },
};

const DEFAULT_ROUTE_GEO = {
  origin: { lat_deg: 35.0, lon_deg: -74.5 },
  destination: { lat_deg: 32.3, lon_deg: -64.78 },
};

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function projectWorldToScreen(point, camera, element) {
  const projected = point.clone().project(camera);
  return {
    x: (projected.x * 0.5 + 0.5) * element.clientWidth,
    y: (-projected.y * 0.5 + 0.5) * element.clientHeight,
    visible: projected.z >= -1 && projected.z <= 1,
  };
}

function getProjectedShipBounds(shipGroup, camera, element) {
  const bounds = SHIP_SCREEN_BOUNDS_POINTS.reduce((acc, localPoint) => {
    const screenPoint = projectWorldToScreen(
      shipGroup.localToWorld(new THREE.Vector3(...localPoint)),
      camera,
      element,
    );
    if (!screenPoint.visible) return acc;

    return {
      minX: Math.min(acc.minX, screenPoint.x),
      maxX: Math.max(acc.maxX, screenPoint.x),
      minY: Math.min(acc.minY, screenPoint.y),
      maxY: Math.max(acc.maxY, screenPoint.y),
      visiblePoints: acc.visiblePoints + 1,
    };
  }, {
    minX: Infinity,
    maxX: -Infinity,
    minY: Infinity,
    maxY: -Infinity,
    visiblePoints: 0,
  });

  if (bounds.visiblePoints === 0) return null;

  return {
    ...bounds,
    centerX: (bounds.minX + bounds.maxX) / 2,
    centerY: (bounds.minY + bounds.maxY) / 2,
  };
}

function emptyZoneOverlay() {
  return {
    visible: false,
    labels: [],
  };
}

function formatZoneMetric(value, digits) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(digits) : '--';
}

function formatSmallMillimeters(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '--';
  if (numeric === 0) return '0';
  if (Math.abs(numeric) < 0.001) return numeric.toFixed(5);
  if (Math.abs(numeric) < 0.01) return numeric.toFixed(4);
  return numeric.toFixed(3);
}

function getZoneStats(zone) {
  const fatigue = Number(zone?.fatigue_consumed);
  const stats = [
    {
      label: 'FAT',
      value: Number.isFinite(fatigue) ? `${(fatigue * 100).toFixed(1)}%` : '--',
    },
    {
      label: 'COR',
      value: formatSmallMillimeters(zone?.corrosion_depth_mm),
    },
    {
      label: 'CRK',
      value: formatSmallMillimeters(zone?.crack_half_length_mm),
    },
    {
      label: 'STR',
      value: formatZoneMetric(zone?.peak_stress_mpa, 1),
    },
  ];

  return {
    stats,
    statsKey: stats.map((stat) => `${stat.label}:${stat.value}`).join('|'),
  };
}

function getFallbackZoneAnchor(index, count) {
  const t = count > 1 ? index / (count - 1) : 0.5;
  return {
    anchor: [
      index % 2 === 0 ? -0.62 : 0.62,
      0.28 + (index % 3) * 0.18,
      -2.2 + t * 4.4,
    ],
    fallbackSide: index % 4 === 0
      ? 'top'
      : index % 4 === 1
        ? 'right'
        : index % 4 === 2
          ? 'bottom'
          : 'left',
  };
}

function getZoneAnchor(zoneName, index, count) {
  return ZONE_ANCHORS[zoneName] || getFallbackZoneAnchor(index, count);
}

function spreadLabelYs(labels, elementHeight, centerY) {
  if (labels.length === 0) return [];

  const minY = ZONE_LABEL_VIEWPORT_MARGIN;
  const maxY = Math.max(minY, elementHeight - ZONE_LABEL_VIEWPORT_MARGIN - ZONE_LABEL_HEIGHT);
  const sorted = [...labels].sort((a, b) => a.anchorY - b.anchorY);

  if (sorted.length === 1) {
    return [{
      ...sorted[0],
      y: clamp(centerY - ZONE_LABEL_HEIGHT / 2, minY, maxY),
    }];
  }

  const spacing = ZONE_LABEL_HEIGHT + ZONE_LABEL_GAP;
  const requiredSpan = (sorted.length - 1) * spacing;
  const availableSpan = maxY - minY;

  if (requiredSpan > availableSpan) {
    const step = availableSpan / (sorted.length - 1);
    return sorted.map((label, index) => ({
      ...label,
      y: minY + step * index,
    }));
  }

  const stackHeight = ZONE_LABEL_HEIGHT + requiredSpan;
  const stackTop = clamp(
    centerY - stackHeight / 2,
    minY,
    Math.max(minY, maxY - requiredSpan),
  );

  return sorted.map((label, index) => ({
    ...label,
    y: stackTop + index * spacing,
  }));
}

function spreadLabelXs(labels, elementWidth, centerX) {
  if (labels.length === 0) return [];

  const labelWidth = labels[0].width;
  const minX = ZONE_LABEL_VIEWPORT_MARGIN;
  const maxX = Math.max(minX, elementWidth - ZONE_LABEL_VIEWPORT_MARGIN - labelWidth);
  const sorted = [...labels].sort((a, b) => a.anchorX - b.anchorX);

  if (sorted.length === 1) {
    return [{
      ...sorted[0],
      x: clamp(centerX - sorted[0].width / 2, minX, maxX),
    }];
  }

  const spacing = labelWidth + ZONE_LABEL_GAP;
  const requiredSpan = (sorted.length - 1) * spacing;
  const availableSpan = maxX - minX;

  if (requiredSpan > availableSpan) {
    const step = availableSpan / (sorted.length - 1);
    return sorted.map((label, index) => ({
      ...label,
      x: minX + step * index,
    }));
  }

  const rowWidth = labelWidth + requiredSpan;
  const rowLeft = clamp(
    centerX - rowWidth / 2,
    minX,
    Math.max(minX, maxX - requiredSpan),
  );

  return sorted.map((label, index) => ({
    ...label,
    x: rowLeft + index * spacing,
  }));
}

function spreadHorizontalLaneLabels(labels, elementWidth, elementHeight, centerX, laneY, direction) {
  if (labels.length === 0) return [];

  const positionedX = spreadLabelXs(labels, elementWidth, centerX);
  const minY = ZONE_LABEL_VIEWPORT_MARGIN;
  const maxY = Math.max(minY, elementHeight - ZONE_LABEL_VIEWPORT_MARGIN - ZONE_LABEL_HEIGHT);

  if (positionedX.length === 1) {
    return [{
      ...positionedX[0],
      y: clamp(laneY, minY, maxY),
    }];
  }

  const spacing = ZONE_LABEL_HEIGHT + ZONE_LABEL_GAP;
  const requiredSpan = (positionedX.length - 1) * spacing;
  const firstY = direction === 'top'
    ? clamp(laneY - requiredSpan, minY, Math.max(minY, maxY - requiredSpan))
    : clamp(laneY, minY, Math.max(minY, maxY - requiredSpan));

  return positionedX.map((label, index) => ({
    ...label,
    y: firstY + index * spacing,
  }));
}

function spreadAllLabelYs(labels, elementHeight) {
  if (labels.length <= 1) return labels;

  const minY = ZONE_LABEL_VIEWPORT_MARGIN;
  const maxY = Math.max(minY, elementHeight - ZONE_LABEL_VIEWPORT_MARGIN - ZONE_LABEL_HEIGHT);
  const spacing = ZONE_LABEL_HEIGHT + ZONE_LABEL_GAP;
  const requiredSpan = (labels.length - 1) * spacing;
  const sorted = [...labels]
    .sort((a, b) => (a.y - b.y) || (a.x - b.x) || (a.anchorY - b.anchorY))
    .map((label) => ({
      ...label,
      y: clamp(label.y, minY, maxY),
    }));

  if (requiredSpan > maxY - minY) {
    const step = (maxY - minY) / (sorted.length - 1);
    return sorted.map((label, index) => ({
      ...label,
      y: minY + step * index,
    }));
  }

  for (let i = 1; i < sorted.length; i += 1) {
    sorted[i].y = Math.max(sorted[i].y, sorted[i - 1].y + spacing);
  }

  const overflow = sorted[sorted.length - 1].y - maxY;
  if (overflow > 0) {
    sorted.forEach((label) => {
      label.y -= overflow;
    });
  }

  for (let i = sorted.length - 2; i >= 0; i -= 1) {
    sorted[i].y = Math.min(sorted[i].y, sorted[i + 1].y - spacing);
  }

  const underflow = minY - sorted[0].y;
  if (underflow > 0) {
    sorted.forEach((label) => {
      label.y += underflow;
    });
  }

  return sorted;
}

function sideHasRoom(side, spaces, labelWidth) {
  if (side === 'left') return spaces.left >= labelWidth * 0.55;
  if (side === 'right') return spaces.right >= labelWidth * 0.55;
  if (side === 'top') return spaces.top >= ZONE_LABEL_HEIGHT + 6;
  return spaces.bottom >= ZONE_LABEL_HEIGHT + 6;
}

function chooseLabelSide(anchorScreen, shipBounds, anchorConfig, spaces, labelWidth) {
  const preferredSide = anchorConfig.fallbackSide;

  const candidates = [
    preferredSide,
    anchorScreen.x < shipBounds.centerX ? 'left' : 'right',
    anchorScreen.y < shipBounds.centerY ? 'top' : 'bottom',
    'left',
    'right',
    'top',
    'bottom',
  ].filter((side, index, all) => all.indexOf(side) === index);

  return candidates.find((side) => sideHasRoom(side, spaces, labelWidth)) || preferredSide;
}

function labelLineEntryY(label) {
  const centerY = label.y + label.height / 2;
  if (Math.abs(label.anchorY - centerY) >= ZONE_LABEL_MIN_DIAGONAL_Y_PX) {
    return centerY;
  }

  const upperSideY = label.y + 3;
  const lowerSideY = label.y + label.height - 3;
  return label.anchorY <= centerY ? lowerSideY : upperSideY;
}

function chooseHorizontalLabelSide(label, elementWidth) {
  const margin = ZONE_LABEL_VIEWPORT_MARGIN;
  const rightFits = label.anchorX + ZONE_LABEL_MIN_HORIZONTAL_RUN_PX + label.width <= elementWidth - margin;
  const leftFits = label.anchorX - ZONE_LABEL_MIN_HORIZONTAL_RUN_PX - label.width >= margin;

  if (label.side === 'left' && leftFits) return 'left';
  if (label.side === 'right' && rightFits) return 'right';
  if (label.side === 'top' || label.side === 'bottom') {
    const currentCenterX = label.x + label.width / 2;
    if (currentCenterX >= label.anchorX && rightFits) return 'right';
    if (currentCenterX < label.anchorX && leftFits) return 'left';
  }
  if (rightFits) return 'right';
  if (leftFits) return 'left';
  return label.anchorX < elementWidth / 2 ? 'right' : 'left';
}

function enforceHorizontalLabelRun(label, elementWidth) {
  const margin = ZONE_LABEL_VIEWPORT_MARGIN;
  const maxX = Math.max(margin, elementWidth - label.width - margin);
  const horizontalSide = chooseHorizontalLabelSide(label, elementWidth);

  if (horizontalSide === 'right') {
    const x = clamp(label.anchorX + ZONE_LABEL_MIN_HORIZONTAL_RUN_PX, margin, maxX);
    return {
      ...label,
      x,
      horizontalSide,
      lineStartX: x,
    };
  }

  const x = clamp(label.anchorX - ZONE_LABEL_MIN_HORIZONTAL_RUN_PX - label.width, margin, maxX);
  return {
    ...label,
    x,
    horizontalSide,
    lineStartX: x + label.width,
  };
}

function addLeaderGeometry(labels, elementWidth) {
  return labels.map((label) => {
    const positionedLabel = enforceHorizontalLabelRun(label, elementWidth);
    const lineStartX = positionedLabel.lineStartX;
    const lineStartY = labelLineEntryY(positionedLabel);
    const dx = lineStartX - label.anchorX;
    const bendX = label.anchorX + dx * 0.58;

    return {
      ...positionedLabel,
      lineStartX,
      lineStartY,
      bendX,
      bendY: lineStartY,
      leaderPoints: [
        [label.anchorX, label.anchorY],
        [bendX, lineStartY],
        [lineStartX, lineStartY],
      ],
    };
  });
}

function buildZoneOverlay(tick, shipGroup, camera, element) {
  const zones = Array.isArray(tick?.zones) ? tick.zones : [];
  if (!zones.length || !shipGroup || !camera || !element) {
    return emptyZoneOverlay();
  }

  shipGroup.updateWorldMatrix(true, false);
  camera.updateMatrixWorld();

  const shipBounds = getProjectedShipBounds(shipGroup, camera, element);
  if (!shipBounds) {
    return emptyZoneOverlay();
  }

  const margin = ZONE_LABEL_VIEWPORT_MARGIN;
  const labelWidth = Math.min(
    ZONE_LABEL_WIDTH,
    Math.max(82, element.clientWidth - margin * 2),
  );
  const spaces = {
    left: shipBounds.minX - margin - ZONE_LABEL_CLEARANCE_PX,
    right: element.clientWidth - margin - shipBounds.maxX - ZONE_LABEL_CLEARANCE_PX,
    top: shipBounds.minY - margin - ZONE_LABEL_CLEARANCE_PX,
    bottom: element.clientHeight - margin - shipBounds.maxY - ZONE_LABEL_CLEARANCE_PX,
  };
  const leftX = clamp(
    shipBounds.minX - ZONE_LABEL_CLEARANCE_PX - labelWidth,
    margin,
    Math.max(margin, element.clientWidth - labelWidth - margin),
  );
  const rightX = clamp(
    shipBounds.maxX + ZONE_LABEL_CLEARANCE_PX,
    margin,
    Math.max(margin, element.clientWidth - labelWidth - margin),
  );
  const topY = clamp(
    shipBounds.minY - ZONE_LABEL_CLEARANCE_PX - ZONE_LABEL_HEIGHT,
    margin,
    Math.max(margin, element.clientHeight - ZONE_LABEL_HEIGHT - margin),
  );
  const bottomY = clamp(
    shipBounds.maxY + ZONE_LABEL_CLEARANCE_PX,
    margin,
    Math.max(margin, element.clientHeight - ZONE_LABEL_HEIGHT - margin),
  );

  const labelsBySide = { left: [], right: [], top: [], bottom: [] };
  zones.forEach((zone, index) => {
    const name = zone.zone || `Zone ${index + 1}`;
    const { stats, statsKey } = getZoneStats(zone);
    const anchorConfig = getZoneAnchor(name, index, zones.length);
    const anchor = shipGroup.localToWorld(new THREE.Vector3(...anchorConfig.anchor));
    const anchorScreen = projectWorldToScreen(anchor, camera, element);
    if (!anchorScreen.visible) return;

    const side = chooseLabelSide(anchorScreen, shipBounds, anchorConfig, spaces, labelWidth);

    labelsBySide[side].push({
      id: `${name}-${index}`,
      name,
      side,
      width: labelWidth,
      height: ZONE_LABEL_HEIGHT,
      x: side === 'left' ? leftX : rightX,
      y: side === 'top' ? topY : bottomY,
      anchorX: anchorScreen.x,
      anchorY: anchorScreen.y,
      stats,
      statsKey,
    });
  });

  const halfTrackOffset = (ZONE_LABEL_HEIGHT + ZONE_LABEL_GAP) / 2;
  const labels = addLeaderGeometry([
    ...spreadLabelYs(labelsBySide.left, element.clientHeight, shipBounds.centerY - halfTrackOffset / 2),
    ...spreadLabelYs(labelsBySide.right, element.clientHeight, shipBounds.centerY + halfTrackOffset / 2),
    ...spreadHorizontalLaneLabels(
      labelsBySide.top,
      element.clientWidth,
      element.clientHeight,
      shipBounds.centerX,
      topY,
      'top',
    ),
    ...spreadHorizontalLaneLabels(
      labelsBySide.bottom,
      element.clientWidth,
      element.clientHeight,
      shipBounds.centerX,
      bottomY,
      'bottom',
    ),
  ], element.clientWidth);

  return labels.length > 0
    ? { visible: true, labels }
    : emptyZoneOverlay();
}

function overlayStateMatches(current, next) {
  if (current.visible !== next.visible || current.labels.length !== next.labels.length) {
    return false;
  }

  return current.labels.every((label, index) => {
    const other = next.labels[index];
    return label.name === other.name
      && label.side === other.side
      && Math.abs(label.x - other.x) < 0.5
      && Math.abs(label.y - other.y) < 0.5
      && Math.abs(label.lineStartX - other.lineStartX) < 0.5
      && Math.abs(label.lineStartY - other.lineStartY) < 0.5
      && Math.abs(label.bendX - other.bendX) < 0.5
      && Math.abs(label.bendY - other.bendY) < 0.5
      && Math.abs(label.anchorX - other.anchorX) < 0.5
      && Math.abs(label.anchorY - other.anchorY) < 0.5
      && label.statsKey === other.statsKey;
  });
}

function validGeoPoint(point) {
  return Number.isFinite(point?.lat_deg) && Number.isFinite(point?.lon_deg);
}

function getRouteGeo(simResult) {
  const origin = simResult?.voyage?.origin;
  const destination = simResult?.voyage?.destination;
  if (validGeoPoint(origin) && validGeoPoint(destination)) {
    return { origin, destination };
  }
  return DEFAULT_ROUTE_GEO;
}

function geoToLocalNm(point, origin, refLatRad) {
  const nmPerDegLon = 60 * Math.cos(refLatRad);
  return {
    east: (point.lon_deg - origin.lon_deg) * nmPerDegLon,
    north: (point.lat_deg - origin.lat_deg) * 60,
  };
}

function createGeoProjector(origin, destination) {
  const refLatRad = THREE.MathUtils.degToRad((origin.lat_deg + destination.lat_deg) * 0.5);
  const destinationLocal = geoToLocalNm(destination, origin, refLatRad);
  const geoLength = Math.hypot(destinationLocal.east, destinationLocal.north);
  const worldVector = BERMUDA.clone().sub(NORFOLK);
  const worldLength = Math.hypot(worldVector.x, worldVector.z);

  if (geoLength <= 0.001 || worldLength <= 0.001) {
    return () => NORFOLK.clone();
  }

  const geoDir = new THREE.Vector2(
    destinationLocal.east / geoLength,
    destinationLocal.north / geoLength,
  );
  const geoPerp = new THREE.Vector2(-geoDir.y, geoDir.x);
  const worldDir = new THREE.Vector2(worldVector.x / worldLength, worldVector.z / worldLength);
  const worldPerp = new THREE.Vector2(-worldDir.y, worldDir.x);
  const scale = worldLength / geoLength;

  return (lonLat) => {
    const local = geoToLocalNm(
      { lon_deg: lonLat[0], lat_deg: lonLat[1] },
      origin,
      refLatRad,
    );
    const along = local.east * geoDir.x + local.north * geoDir.y;
    const across = local.east * geoPerp.x + local.north * geoPerp.y;
    return new THREE.Vector3(
      NORFOLK.x + (worldDir.x * along + worldPerp.x * across) * scale,
      LAND_Y,
      NORFOLK.z + (worldDir.y * along + worldPerp.y * across) * scale,
    );
  };
}

function geoJsonPolygons(geoJson) {
  const polygons = [];

  geoJson?.features?.forEach((feature) => {
    const geometry = feature.geometry;
    if (!geometry) return;

    if (geometry.type === 'Polygon') {
      polygons.push({
        name: feature.properties?.NAME || feature.properties?.ADMIN || 'land',
        rings: geometry.coordinates,
      });
    } else if (geometry.type === 'MultiPolygon') {
      geometry.coordinates.forEach((rings) => {
        polygons.push({
          name: feature.properties?.NAME || feature.properties?.ADMIN || 'land',
          rings,
        });
      });
    }
  });

  return polygons;
}

function ringToShapePoints(ring, projectGeoPoint) {
  return ring
    .filter((coord) => Number.isFinite(coord?.[0]) && Number.isFinite(coord?.[1]))
    .map(projectGeoPoint)
    .map((point) => new THREE.Vector2(point.x, -point.z));
}

function ringToLinePoints(ring, projectGeoPoint) {
  return ring
    .filter((coord) => Number.isFinite(coord?.[0]) && Number.isFinite(coord?.[1]))
    .map(projectGeoPoint)
    .map((point) => new THREE.Vector3(point.x, LAND_Y + 0.004, point.z));
}

function createLandLayer(geoJson, projectGeoPoint) {
  const group = new THREE.Group();
  group.name = 'land-layer';

  const fillMaterial = new THREE.MeshBasicMaterial({
    color: 0xaeb2b8,
    transparent: true,
    opacity: 0.34,
    depthWrite: false,
    side: THREE.DoubleSide,
    toneMapped: false,
  });
  const coastMaterial = new THREE.LineBasicMaterial({
    color: 0x59616a,
    transparent: true,
    opacity: 0.26,
    depthWrite: false,
    toneMapped: false,
  });

  let meshCount = 0;
  let coastlineCount = 0;

  geoJsonPolygons(geoJson).forEach((polygon) => {
    const outer = ringToShapePoints(polygon.rings[0] || [], projectGeoPoint);
    if (outer.length < 3) return;

    const shape = new THREE.Shape(outer);
    polygon.rings.slice(1).forEach((holeRing) => {
      const hole = ringToShapePoints(holeRing, projectGeoPoint);
      if (hole.length >= 3) {
        shape.holes.push(new THREE.Path(hole));
      }
    });

    const geometry = new THREE.ShapeGeometry(shape);
    const mesh = new THREE.Mesh(geometry, fillMaterial);
    mesh.name = `${polygon.name} fill`;
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.y = LAND_Y;
    mesh.renderOrder = 0;
    group.add(mesh);
    meshCount += 1;

    const linePoints = ringToLinePoints(polygon.rings[0] || [], projectGeoPoint);
    if (linePoints.length < 2) return;
    linePoints.push(linePoints[0].clone());
    const line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(linePoints),
      coastMaterial,
    );
    line.name = `${polygon.name} coastline`;
    line.frustumCulled = false;
    line.renderOrder = 1;
    group.add(line);
    coastlineCount += 1;
  });

  group.userData.stats = {
    features: geoJson?.features?.length || 0,
    meshes: meshCount,
    coastlines: coastlineCount,
  };

  return group;
}

function disposeObject3D(object) {
  object.traverse((child) => {
    if (child.geometry) child.geometry.dispose();
    if (Array.isArray(child.material)) {
      child.material.forEach((material) => material.dispose());
    } else if (child.material) {
      child.material.dispose();
    }
  });
}

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

export default function HullDiagram({ simResult, progress: tickProgress = null, activeTick = null, gridRotationDeg = DEFAULT_GRID_ROTATION_DEG }) {
  const mountRef = useRef(null);
  const stateRef = useRef({});
  const [zoneOverlay, setZoneOverlay] = useState(emptyZoneOverlay());
  const [zoneOverlayActive, setZoneOverlayActive] = useState(false);
  const routeGeo = getRouteGeo(simResult);
  const routeGeoKey = [
    routeGeo.origin.lat_deg,
    routeGeo.origin.lon_deg,
    routeGeo.destination.lat_deg,
    routeGeo.destination.lon_deg,
  ].join(',');
  const progress = Number.isFinite(tickProgress)
    ? Math.max(0, Math.min(tickProgress, 1))
    : Math.min((simResult?.result?.distance_completed_pct ?? 0) / 100, 1);

  useEffect(() => {
    stateRef.current.activeTick = activeTick;
  }, [activeTick]);

  useEffect(() => {
    if (!zoneOverlay.visible || zoneOverlay.labels.length === 0) {
      setZoneOverlayActive(false);
      return undefined;
    }

    const frameId = window.requestAnimationFrame(() => {
      setZoneOverlayActive(true);
    });

    return () => window.cancelAnimationFrame(frameId);
  }, [zoneOverlay.visible, zoneOverlay.labels.length]);

  useEffect(() => {
    if (zoneOverlay.visible || zoneOverlay.labels.length === 0) return undefined;

    const timeoutId = window.setTimeout(() => {
      setZoneOverlay((current) => (current.visible ? current : emptyZoneOverlay()));
    }, ZONE_OVERLAY_ANIMATION_MS);

    return () => window.clearTimeout(timeoutId);
  }, [zoneOverlay.visible, zoneOverlay.labels.length]);

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
    let disposed = false;
    fetch(LAND_GEOJSON_URL)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Failed to load land GeoJSON: ${response.status}`);
        }
        return response.json();
      })
      .then((geoJson) => {
        if (disposed) return;
        const landLayer = createLandLayer(
          geoJson,
          createGeoProjector(routeGeo.origin, routeGeo.destination),
        );
        scene.add(landLayer);
        stateRef.current.landLayer = landLayer;
        window.__seaforgeLandLayerStats = landLayer.userData.stats;
      })
      .catch((error) => {
        console.warn(error);
      });

    // Camera — positioned perpendicular-right of the route, orbiting around the ship.
    const cameraOffset = new THREE.Vector3(55, 65, 43);
    const shipFocus = NORFOLK.clone();
    const cam = new THREE.PerspectiveCamera(32, el.clientWidth / el.clientHeight, 0.1, 200000);
    cam.position.copy(shipFocus).add(cameraOffset);
    cam.lookAt(shipFocus);

    const controls = new OrbitControls(cam, renderer.domElement);
    controls.target.copy(shipFocus);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.enablePan = false;
    controls.minDistance = CAMERA_MIN_DISTANCE;
    controls.maxDistance = Infinity;
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

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let isDragging = false;
    let isHoveringShip = false;

    const syncZoneOverlay = (next) => {
      if (disposed) return;
      setZoneOverlay((current) => {
        const resolvedNext = next.visible ? next : { ...next, labels: current.labels };
        return overlayStateMatches(current, resolvedNext) ? current : resolvedNext;
      });
    };

    const updateZoneOverlay = () => {
      if (!isHoveringShip) {
        syncZoneOverlay(emptyZoneOverlay());
        return;
      }

      const overlay = buildZoneOverlay(
        stateRef.current.activeTick,
        shipGroup,
        cam,
        el,
      );
      syncZoneOverlay(overlay);
    };

    const testShipHover = (event) => {
      const targets = stateRef.current.shipHitTargets || [];
      if (!targets.length || isDragging) return false;

      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -(((event.clientY - rect.top) / rect.height) * 2 - 1);
      raycaster.setFromCamera(pointer, cam);
      return raycaster.intersectObjects(targets, true).length > 0;
    };

    renderer.domElement.style.cursor = 'grab';
    renderer.domElement.style.touchAction = 'none';
    const onPointerDown = () => {
      isDragging = true;
      renderer.domElement.style.cursor = 'grabbing';
      syncZoneOverlay(emptyZoneOverlay());
    };
    const onPointerUp = () => {
      isDragging = false;
      renderer.domElement.style.cursor = isHoveringShip ? 'pointer' : 'grab';
    };
    const onPointerMove = (event) => {
      const nextHover = testShipHover(event);
      if (nextHover !== isHoveringShip) {
        isHoveringShip = nextHover;
      }
      renderer.domElement.style.cursor = isDragging
        ? 'grabbing'
        : (isHoveringShip ? 'pointer' : 'grab');
      updateZoneOverlay();
    };
    const onPointerLeave = () => {
      isDragging = false;
      isHoveringShip = false;
      renderer.domElement.style.cursor = 'grab';
      syncZoneOverlay(emptyZoneOverlay());
    };
    const blockContextMenu = (event) => event.preventDefault();
    renderer.domElement.addEventListener('pointerdown', onPointerDown);
    renderer.domElement.addEventListener('pointerup', onPointerUp);
    renderer.domElement.addEventListener('pointermove', onPointerMove);
    renderer.domElement.addEventListener('pointerleave', onPointerLeave);
    renderer.domElement.addEventListener('contextmenu', blockContextMenu);

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
      stateRef.current.shipHitTargets = [mesh];
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
      if (isHoveringShip) updateZoneOverlay();
      renderer.render(scene, cam);
    };
    loop();

    return () => {
      disposed = true;
      cancelAnimationFrame(frameId);
      window.removeEventListener('resize', onResize);
      renderer.domElement.removeEventListener('pointerdown', onPointerDown);
      renderer.domElement.removeEventListener('pointerup', onPointerUp);
      renderer.domElement.removeEventListener('pointermove', onPointerMove);
      renderer.domElement.removeEventListener('pointerleave', onPointerLeave);
      renderer.domElement.removeEventListener('contextmenu', blockContextMenu);
      controls.dispose();
      if (stateRef.current.landLayer) {
        disposeObject3D(stateRef.current.landLayer);
        stateRef.current.landLayer = null;
      }
      renderer.dispose();
      if (el.contains(renderer.domElement)) el.removeChild(renderer.domElement);
    };
  }, [routeGeoKey]);

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
      {zoneOverlay.labels.length > 0 && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            pointerEvents: 'none',
            zIndex: 3,
            opacity: zoneOverlayActive ? 1 : 0,
            transform: zoneOverlayActive
              ? 'translate3d(0, 0, 0)'
              : `translate3d(0, ${ZONE_OVERLAY_HIDDEN_OFFSET_PX}px, 0)`,
            transition: `opacity ${ZONE_OVERLAY_ANIMATION_MS}ms ease, transform ${ZONE_OVERLAY_ANIMATION_MS}ms ease`,
            willChange: 'opacity, transform',
          }}
        >
          <svg
            aria-hidden="true"
            style={{
              position: 'absolute',
              inset: 0,
              width: '100%',
              height: '100%',
              pointerEvents: 'none',
              zIndex: 0,
            }}
          >
            {zoneOverlay.labels.map((label) => (
              <polyline
                key={`${label.id}-line`}
                points={label.leaderPoints.map(([x, y]) => `${x},${y}`).join(' ')}
                fill="none"
                stroke={ZONE_LABEL_BORDER_COLOR}
                strokeWidth="1.15"
                strokeLinecap="square"
                strokeLinejoin="miter"
              />
            ))}
            {zoneOverlay.labels.map((label) => (
              <rect
                key={`${label.id}-line-mask`}
                x={label.x}
                y={label.y}
                width={label.width}
                height={label.height}
                fill="#C3C4CA"
                fillOpacity="1"
              />
            ))}
          </svg>
          {zoneOverlay.labels.map((label) => (
            <div
              key={label.id}
              style={{
                position: 'absolute',
                left: label.x,
                top: label.y,
                width: label.width,
                height: label.height,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 4,
                padding: '5px 8px 6px',
                boxSizing: 'border-box',
                pointerEvents: 'none',
                zIndex: 1,
                color: 'rgba(0,0,0,0.76)',
                background: '#C3C4CA',
                border: `1px solid ${ZONE_LABEL_BORDER_COLOR}`,
                fontFamily: "'Courier New', monospace",
                fontSize: 10,
                lineHeight: 1,
                letterSpacing: 0,
                overflow: 'hidden',
                textTransform: 'uppercase',
              }}
            >
              <div
                style={{
                  width: '100%',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  textAlign: 'center',
                  fontSize: 10.5,
                }}
              >
                {label.name}
              </div>
              <div
                style={{
                  width: '100%',
                  display: 'grid',
                  gridTemplateColumns: '1fr 1fr',
                  columnGap: 8,
                  rowGap: 3,
                  fontSize: 8.5,
                  color: 'rgba(0,0,0,0.62)',
                }}
              >
                {label.stats.map((stat) => (
                  <div
                    key={`${label.id}-${stat.label}`}
                    style={{
                      minWidth: 0,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: 4,
                    }}
                  >
                    <span style={{ color: 'rgba(0,0,0,0.42)' }}>{stat.label}</span>
                    <span
                      style={{
                        color: 'rgba(0,0,0,0.72)',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {stat.value}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
