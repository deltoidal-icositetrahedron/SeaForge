import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

const GLOBE_CENTER = new THREE.Vector3(0, 0, 0);
const GLOBE_RADIUS = 160;
const GLOBE_LAND_RADIUS = GLOBE_RADIUS + 0.1;
const GLOBE_COAST_RADIUS = GLOBE_RADIUS + 0.22;
const GLOBE_GRID_RADIUS = GLOBE_RADIUS + 0.38;
const GLOBE_GRID_SHADOW_RADIUS = GLOBE_RADIUS + 0.28;
const GLOBE_ROUTE_RADIUS = GLOBE_RADIUS + 0.75;
const GLOBE_SHIP_RADIUS = GLOBE_RADIUS + 1.05;
const GLOBE_ROUTE_SEGMENTS = 96;
const GLOBE_GRID_SEGMENTS = 144;
const LAND_TRIANGLE_MAX_ANGLE_DEG = 4.5;
const LAND_TRIANGLE_MAX_SUBDIVISIONS = 8;
const SHIP_MODEL_LENGTH = 4.2;
const GRID_LINE_OPACITY = 0.105;
const GRID_SHADOW_OPACITY = 0.025;
const LOCAL_GRID_SIZE = 180;
const LOCAL_GRID_DIVISIONS = 40;
const LOCAL_GRID_LINE_WIDTH = 0.04;
const LOCAL_GRID_SHADOW_LINE_WIDTH = 0.13;
const LOCAL_GRID_LINE_OPACITY = 0.095;
const LOCAL_GRID_SHADOW_OPACITY = 0.015;
const LOCAL_GRID_SHADOW_OFFSET = -0.6;
const LOCAL_GRID_SURFACE_OFFSET = 0.82;
const LOCAL_GRID_SHADOW_Y = 0.008;
const LOCAL_GRID_LINE_Y = 0.01;
const LOCAL_GRID_ROTATION_DEG = 105;
const LOCAL_GRID_CURVE_SEGMENTS = 96;
const GLOBE_GRID_LEVELS = [
  { key: 'coarse', name: 'globe-grid-coarse', latStep: 30, lonStep: 30, lineOpacity: 0.07, shadowOpacity: 0.014 },
  { key: 'medium', name: 'globe-grid-medium', latStep: 15, lonStep: 15, lineOpacity: GRID_LINE_OPACITY, shadowOpacity: GRID_SHADOW_OPACITY },
  { key: 'fine', name: 'globe-grid-fine', latStep: 5, lonStep: 5, lineOpacity: 0.055, shadowOpacity: 0.01 },
];
const ROUTE_TRAVERSED_COLOR = 0x000000;
const ROUTE_REMAINING_COLOR = 0x0000FF;
const ROUTE_LINE_OPACITY = 0.68;
const SHIP_SHADOW_Y = 0.022;
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
const CAMERA_NEAR = 1;
const CAMERA_FAR = 6000;
const CAMERA_MIN_DISTANCE = 24;
const CAMERA_MAX_DISTANCE = GLOBE_RADIUS * 5.2;
const SHIP_CAMERA_LOCAL_OFFSET = new THREE.Vector3(-55, 65, -43);

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

function smoothstep(edge0, edge1, value) {
  const t = clamp((value - edge0) / (edge1 - edge0), 0, 1);
  return t * t * (3 - 2 * t);
}

function rangeFade(value, fadeInStart, fadeInEnd, fadeOutStart, fadeOutEnd) {
  return smoothstep(fadeInStart, fadeInEnd, value) * (1 - smoothstep(fadeOutStart, fadeOutEnd, value));
}

function geoToUnitVector(lonDeg, latDeg) {
  const lon = THREE.MathUtils.degToRad(lonDeg);
  const lat = THREE.MathUtils.degToRad(latDeg);
  const cosLat = Math.cos(lat);
  return new THREE.Vector3(
    cosLat * Math.sin(lon),
    Math.sin(lat),
    cosLat * Math.cos(lon),
  ).normalize();
}

function globePoint(lonDeg, latDeg, radius = GLOBE_RADIUS) {
  return geoToUnitVector(lonDeg, latDeg).multiplyScalar(radius).add(GLOBE_CENTER);
}

function slerpUnitVectors(a, b, t) {
  const dot = clamp(a.dot(b), -1, 1);
  const omega = Math.acos(dot);
  if (omega < 1e-6) {
    return a.clone().lerp(b, t).normalize();
  }

  const sinOmega = Math.sin(omega);
  return a.clone().multiplyScalar(Math.sin((1 - t) * omega) / sinOmega)
    .add(b.clone().multiplyScalar(Math.sin(t * omega) / sinOmega))
    .normalize();
}

function buildRouteFrame(routeGeo) {
  const originUnit = geoToUnitVector(routeGeo.origin.lon_deg, routeGeo.origin.lat_deg);
  const destinationUnit = geoToUnitVector(routeGeo.destination.lon_deg, routeGeo.destination.lat_deg);
  const routeAxis = originUnit.clone().cross(destinationUnit);
  if (routeAxis.lengthSq() < 1e-8) routeAxis.set(0, 1, 0);
  routeAxis.normalize();
  const midpointUnit = slerpUnitVectors(originUnit, destinationUnit, 0.5);

  return {
    originUnit,
    destinationUnit,
    routeAxis,
    midpointUnit,
    midpoint: midpointUnit.clone().multiplyScalar(GLOBE_RADIUS),
  };
}

function routeUnitAt(routeFrame, progress) {
  return slerpUnitVectors(
    routeFrame.originUnit,
    routeFrame.destinationUnit,
    clamp(progress, 0, 1),
  );
}

function routePointAt(routeFrame, progress, radius = GLOBE_ROUTE_RADIUS) {
  return routeUnitAt(routeFrame, progress).multiplyScalar(radius);
}

function routeTangentAt(routeFrame, unit) {
  return routeFrame.routeAxis.clone().cross(unit).normalize();
}

function buildRouteArcPoints(routeFrame, start, end, radius = GLOBE_ROUTE_RADIUS) {
  const from = clamp(start, 0, 1);
  const to = clamp(end, 0, 1);
  const span = Math.abs(to - from);
  const steps = Math.max(1, Math.ceil(GLOBE_ROUTE_SEGMENTS * span));
  const points = [];

  for (let i = 0; i <= steps; i += 1) {
    const t = from + (to - from) * (i / steps);
    points.push(routePointAt(routeFrame, t, radius));
  }

  return points;
}

function orientObjectOnGlobe(object, unit, forward) {
  const up = unit.clone().normalize();
  const zAxis = forward.clone().projectOnPlane(up).normalize();
  const xAxis = up.clone().cross(zAxis).normalize();
  const matrix = new THREE.Matrix4().makeBasis(xAxis, up, zAxis);
  object.quaternion.setFromRotationMatrix(matrix);
}

function placeShipOnRoute(shipGroup, routeFrame, progress) {
  const unit = routeUnitAt(routeFrame, progress);
  const position = unit.clone().multiplyScalar(GLOBE_SHIP_RADIUS);
  const tangent = routeTangentAt(routeFrame, unit);
  shipGroup.position.copy(position);
  orientObjectOnGlobe(shipGroup, unit, tangent);
}

function placeLocalGridOnRoute(gridGroup, routeFrame, progress) {
  const unit = routeUnitAt(routeFrame, progress);
  const tangent = routeTangentAt(routeFrame, unit);
  gridGroup.position.copy(unit).multiplyScalar(GLOBE_RADIUS + LOCAL_GRID_SURFACE_OFFSET);
  orientObjectOnGlobe(gridGroup, unit, tangent);
}

function shipCameraPositionFor(routeFrame, progress, target) {
  const up = routeUnitAt(routeFrame, progress);
  const forward = routeTangentAt(routeFrame, up);
  const right = up.clone().cross(forward).normalize();

  return target.clone()
    .addScaledVector(right, SHIP_CAMERA_LOCAL_OFFSET.x)
    .addScaledVector(up, SHIP_CAMERA_LOCAL_OFFSET.y)
    .addScaledVector(forward, SHIP_CAMERA_LOCAL_OFFSET.z);
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
    const minRunX = label.anchorX + ZONE_LABEL_MIN_HORIZONTAL_RUN_PX;
    const x = clamp(Math.max(label.x, minRunX), margin, maxX);
    return {
      ...label,
      x,
      horizontalSide,
      lineStartX: x,
    };
  }

  const maxRunX = label.anchorX - ZONE_LABEL_MIN_HORIZONTAL_RUN_PX - label.width;
  const x = clamp(Math.min(label.x, maxRunX), margin, maxX);
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

function ringToShapePoints(ring) {
  return ring
    .filter((coord) => Number.isFinite(coord?.[0]) && Number.isFinite(coord?.[1]))
    .map((coord) => new THREE.Vector2(coord[0], coord[1]));
}

function ringToLinePoints(ring) {
  return ring
    .filter((coord) => Number.isFinite(coord?.[0]) && Number.isFinite(coord?.[1]))
    .map((coord) => globePoint(coord[0], coord[1], GLOBE_COAST_RADIUS));
}

function angularDistanceDeg(a, b) {
  return THREE.MathUtils.radToDeg(Math.acos(clamp(a.dot(b), -1, 1)));
}

function getTriangleSubdivisions(a, b, c) {
  const maxAngle = Math.max(
    angularDistanceDeg(a, b),
    angularDistanceDeg(b, c),
    angularDistanceDeg(c, a),
  );

  return clamp(
    Math.ceil(maxAngle / LAND_TRIANGLE_MAX_ANGLE_DEG),
    1,
    LAND_TRIANGLE_MAX_SUBDIVISIONS,
  );
}

function interpolateSphericalTriangle(a, b, c, i, j, subdivisions) {
  const bWeight = i / subdivisions;
  const cWeight = j / subdivisions;
  const aWeight = 1 - bWeight - cWeight;
  return a.clone().multiplyScalar(aWeight)
    .addScaledVector(b, bWeight)
    .addScaledVector(c, cWeight)
    .normalize();
}

function pushSphericalVertex(positions, normals, unit, radius) {
  positions.push(unit.x * radius, unit.y * radius, unit.z * radius);
  normals.push(unit.x, unit.y, unit.z);
}

function pushSphericalTriangle(positions, normals, a, b, c, radius) {
  const subdivisions = getTriangleSubdivisions(a, b, c);

  for (let i = 0; i < subdivisions; i += 1) {
    for (let j = 0; j < subdivisions - i; j += 1) {
      pushSphericalVertex(
        positions,
        normals,
        interpolateSphericalTriangle(a, b, c, i, j, subdivisions),
        radius,
      );
      pushSphericalVertex(
        positions,
        normals,
        interpolateSphericalTriangle(a, b, c, i + 1, j, subdivisions),
        radius,
      );
      pushSphericalVertex(
        positions,
        normals,
        interpolateSphericalTriangle(a, b, c, i, j + 1, subdivisions),
        radius,
      );

      if (j < subdivisions - i - 1) {
        pushSphericalVertex(
          positions,
          normals,
          interpolateSphericalTriangle(a, b, c, i + 1, j, subdivisions),
          radius,
        );
        pushSphericalVertex(
          positions,
          normals,
          interpolateSphericalTriangle(a, b, c, i + 1, j + 1, subdivisions),
          radius,
        );
        pushSphericalVertex(
          positions,
          normals,
          interpolateSphericalTriangle(a, b, c, i, j + 1, subdivisions),
          radius,
        );
      }
    }
  }
}

function sphereShapeGeometry(planarGeometry, radius) {
  const sourcePosition = planarGeometry.getAttribute('position');
  const sourceIndex = planarGeometry.index;
  const positions = [];
  const normals = [];
  const getUnitAt = (vertexIndex) => (
    geoToUnitVector(sourcePosition.getX(vertexIndex), sourcePosition.getY(vertexIndex))
  );
  const getVertexIndex = (index) => (sourceIndex ? sourceIndex.getX(index) : index);
  const triangleCount = sourceIndex ? sourceIndex.count : sourcePosition.count;

  for (let i = 0; i < triangleCount; i += 3) {
    pushSphericalTriangle(
      positions,
      normals,
      getUnitAt(getVertexIndex(i)),
      getUnitAt(getVertexIndex(i + 1)),
      getUnitAt(getVertexIndex(i + 2)),
      radius,
    );
  }

  planarGeometry.dispose();

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
  geometry.computeBoundingSphere();
  return geometry;
}

function createLandLayer(geoJson) {
  const group = new THREE.Group();
  group.name = 'land-layer';

  const fillMaterial = new THREE.MeshBasicMaterial({
    color: 0xaeb2b8,
    transparent: true,
    opacity: 0.46,
    depthTest: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    toneMapped: false,
  });
  const coastMaterial = new THREE.LineBasicMaterial({
    color: 0x59616a,
    transparent: true,
    opacity: 0.32,
    depthTest: true,
    depthWrite: false,
    toneMapped: false,
  });

  let meshCount = 0;
  let coastlineCount = 0;

  geoJsonPolygons(geoJson).forEach((polygon) => {
    const outer = ringToShapePoints(polygon.rings[0] || []);
    if (outer.length < 3) return;

    const shape = new THREE.Shape(outer);
    polygon.rings.slice(1).forEach((holeRing) => {
      const hole = ringToShapePoints(holeRing);
      if (hole.length >= 3) {
        shape.holes.push(new THREE.Path(hole));
      }
    });

    const geometry = sphereShapeGeometry(new THREE.ShapeGeometry(shape), GLOBE_LAND_RADIUS);
    const mesh = new THREE.Mesh(geometry, fillMaterial);
    mesh.name = `${polygon.name} fill`;
    mesh.renderOrder = -20;
    group.add(mesh);
    meshCount += 1;

    const linePoints = ringToLinePoints(polygon.rings[0] || []);
    if (linePoints.length < 2) return;
    linePoints.push(linePoints[0].clone());
    const line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(linePoints),
      coastMaterial,
    );
    line.name = `${polygon.name} coastline`;
    line.frustumCulled = false;
    line.renderOrder = -19;
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
  const geometries = new Set();
  const materials = new Set();
  object.traverse((child) => {
    if (child.geometry) geometries.add(child.geometry);
    if (Array.isArray(child.material)) {
      child.material.forEach((material) => materials.add(material));
    } else if (child.material) {
      materials.add(child.material);
    }
  });
  geometries.forEach((geometry) => geometry.dispose());
  materials.forEach((material) => material.dispose());
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

function createGlobeBase() {
  const globe = new THREE.Mesh(
    new THREE.SphereGeometry(GLOBE_RADIUS, 96, 48),
    new THREE.MeshBasicMaterial({
      color: 0xbfc3c9,
      depthWrite: true,
      toneMapped: false,
    }),
  );
  globe.name = 'globe-ocean';
  globe.renderOrder = -40;
  return globe;
}

function createGlobeLinePoints({ latDeg = null, lonDeg = null, radius = GLOBE_GRID_RADIUS }) {
  const points = [];
  for (let i = 0; i <= GLOBE_GRID_SEGMENTS; i += 1) {
    const t = i / GLOBE_GRID_SEGMENTS;
    const lon = lonDeg ?? -180 + t * 360;
    const lat = latDeg ?? -85 + t * 170;
    points.push(globePoint(lon, lat, radius));
  }
  return points;
}

function createGlobeGrid(color, opacity, radius, options = {}) {
  const {
    latStep = 15,
    lonStep = 15,
    includeLatitudes = true,
    includeLongitudes = true,
  } = options;
  const group = new THREE.Group();
  const material = new THREE.LineBasicMaterial({
    color,
    transparent: true,
    opacity,
    depthTest: true,
    depthWrite: false,
    toneMapped: false,
  });
  material.userData.baseOpacity = opacity;

  if (includeLatitudes) {
    for (let lat = -75; lat <= 75; lat += latStep) {
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(createGlobeLinePoints({ latDeg: lat, radius })),
        material,
      );
      line.frustumCulled = false;
      group.add(line);
    }
  }

  if (includeLongitudes) {
    for (let lon = -180; lon < 180; lon += lonStep) {
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(createGlobeLinePoints({ lonDeg: lon, radius })),
        material,
      );
      line.frustumCulled = false;
      group.add(line);
    }
  }

  return group;
}

function createGlobeGridLevel({ name, latStep, lonStep, lineOpacity, shadowOpacity }) {
  const group = new THREE.Group();
  group.name = name;

  group.add(createGlobeGrid(
    0x000000,
    shadowOpacity,
    GLOBE_GRID_SHADOW_RADIUS,
    { latStep, lonStep },
  ));
  group.add(createGlobeGrid(
    0x000000,
    lineOpacity,
    GLOBE_GRID_RADIUS,
    { latStep, lonStep },
  ));

  return group;
}

function pushCurvedLocalGridVertex(positions, normals, x, z) {
  const surfaceRadius = GLOBE_RADIUS + LOCAL_GRID_SURFACE_OFFSET;
  const y = Math.sqrt(Math.max(surfaceRadius * surfaceRadius - x * x - z * z, 0)) - surfaceRadius;
  const normalY = y + surfaceRadius;
  const normalLength = Math.hypot(x, normalY, z) || 1;
  positions.push(x, y, z);
  normals.push(x / normalLength, normalY / normalLength, z / normalLength);
}

function pushCurvedLocalGridQuad(positions, normals, a, b, c, d) {
  pushCurvedLocalGridVertex(positions, normals, a.x, a.z);
  pushCurvedLocalGridVertex(positions, normals, b.x, b.z);
  pushCurvedLocalGridVertex(positions, normals, c.x, c.z);
  pushCurvedLocalGridVertex(positions, normals, c.x, c.z);
  pushCurvedLocalGridVertex(positions, normals, b.x, b.z);
  pushCurvedLocalGridVertex(positions, normals, d.x, d.z);
}

function createLocalGridMesh(size, divisions, lineWidth, color, opacity, options = {}) {
  const { includeXLines = true, includeZLines = true, renderOrder = 0 } = options;
  const positions = [];
  const normals = [];
  const material = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity,
    depthTest: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    toneMapped: false,
  });
  material.userData.baseOpacity = opacity;

  const step = size / divisions;
  const half = size / 2;

  for (let i = 0; i <= divisions; i += 1) {
    const p = -half + i * step;

    if (includeXLines) {
      for (let segment = 0; segment < LOCAL_GRID_CURVE_SEGMENTS; segment += 1) {
        const x0 = -half + (size * segment) / LOCAL_GRID_CURVE_SEGMENTS;
        const x1 = -half + (size * (segment + 1)) / LOCAL_GRID_CURVE_SEGMENTS;
        pushCurvedLocalGridQuad(
          positions,
          normals,
          { x: x0, z: p - lineWidth / 2 },
          { x: x1, z: p - lineWidth / 2 },
          { x: x0, z: p + lineWidth / 2 },
          { x: x1, z: p + lineWidth / 2 },
        );
      }
    }

    if (includeZLines) {
      for (let segment = 0; segment < LOCAL_GRID_CURVE_SEGMENTS; segment += 1) {
        const z0 = -half + (size * segment) / LOCAL_GRID_CURVE_SEGMENTS;
        const z1 = -half + (size * (segment + 1)) / LOCAL_GRID_CURVE_SEGMENTS;
        pushCurvedLocalGridQuad(
          positions,
          normals,
          { x: p - lineWidth / 2, z: z0 },
          { x: p + lineWidth / 2, z: z0 },
          { x: p - lineWidth / 2, z: z1 },
          { x: p + lineWidth / 2, z: z1 },
        );
      }
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3));
  geometry.computeBoundingSphere();

  const mesh = new THREE.Mesh(geometry, material);
  mesh.frustumCulled = false;
  mesh.renderOrder = renderOrder;
  return mesh;
}

function createLocalGrid() {
  const root = new THREE.Group();
  root.name = 'ship-local-grid';
  const gridSurface = new THREE.Group();
  gridSurface.rotation.y = THREE.MathUtils.degToRad(LOCAL_GRID_ROTATION_DEG);
  root.add(gridSurface);

  // Matches the committed flat-grid shadow layout, mapped onto the curved ship-local patch.
  const horizontalGridShadow = createLocalGridMesh(
    LOCAL_GRID_SIZE,
    LOCAL_GRID_DIVISIONS,
    LOCAL_GRID_SHADOW_LINE_WIDTH,
    0x000000,
    LOCAL_GRID_SHADOW_OPACITY,
    { includeZLines: false, renderOrder: -3 },
  );
  horizontalGridShadow.position.set(0, LOCAL_GRID_SHADOW_Y, LOCAL_GRID_SHADOW_OFFSET);
  gridSurface.add(horizontalGridShadow);

  const verticalGridShadow = createLocalGridMesh(
    LOCAL_GRID_SIZE,
    LOCAL_GRID_DIVISIONS,
    LOCAL_GRID_LINE_WIDTH,
    0x000000,
    LOCAL_GRID_SHADOW_OPACITY,
    { includeXLines: false, renderOrder: -3 },
  );
  verticalGridShadow.position.set(LOCAL_GRID_SHADOW_OFFSET, LOCAL_GRID_SHADOW_Y, 0);
  gridSurface.add(verticalGridShadow);

  const grid = createLocalGridMesh(
    LOCAL_GRID_SIZE,
    LOCAL_GRID_DIVISIONS,
    LOCAL_GRID_LINE_WIDTH,
    0x000000,
    LOCAL_GRID_LINE_OPACITY,
    { renderOrder: -2 },
  );
  grid.position.set(0, LOCAL_GRID_LINE_Y, 0);
  gridSurface.add(grid);

  return root;
}

function collectOpacityMaterials(object) {
  const materials = [];
  object.traverse((child) => {
    if (!child.material) return;
    const childMaterials = Array.isArray(child.material) ? child.material : [child.material];
    childMaterials.forEach((material) => {
      if (materials.includes(material)) return;
      if (!Number.isFinite(material.userData.baseOpacity)) {
        material.userData.baseOpacity = material.opacity;
      }
      materials.push(material);
    });
  });
  object.userData.opacityMaterials = materials;
  return materials;
}

function setOpacityScale(object, opacityScale) {
  const materials = object.userData.opacityMaterials || collectOpacityMaterials(object);
  object.visible = opacityScale > 0.01;
  materials.forEach((material) => {
    material.opacity = material.userData.baseOpacity * opacityScale;
  });
}

function getGridOpacityScales(distance) {
  return {
    coarse: smoothstep(260, 520, distance),
    medium: rangeFade(distance, 100, 155, 310, 500),
    fine: rangeFade(distance, 58, 82, 135, 215),
    local: 1 - smoothstep(50, 82, distance),
  };
}

function updateGridDetail({ cam, controls, globeGridLevels, localGridGroup }) {
  if (!cam || !controls || !globeGridLevels || !localGridGroup) return;

  const distance = cam.position.distanceTo(controls.target);
  const opacityScales = getGridOpacityScales(distance);

  globeGridLevels.forEach((level) => {
    setOpacityScale(level.group, opacityScales[level.key] ?? 0);
  });
  setOpacityScale(localGridGroup, opacityScales.local);
}

export default function HullDiagram({ simResult, progress: tickProgress = null, activeTick = null }) {
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
  const routeFrame = buildRouteFrame(routeGeo);
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
    const globe = createGlobeBase();
    scene.add(globe);
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
        const landLayer = createLandLayer(geoJson);
        scene.add(landLayer);
        stateRef.current.landLayer = landLayer;
        window.__seaforgeLandLayerStats = landLayer.userData.stats;
      })
      .catch((error) => {
        console.warn(error);
      });

    const shipFocus = routePointAt(routeFrame, progress, GLOBE_SHIP_RADIUS);
    const cam = new THREE.PerspectiveCamera(32, el.clientWidth / el.clientHeight, CAMERA_NEAR, CAMERA_FAR);
    cam.up.copy(routeUnitAt(routeFrame, progress));
    cam.position.copy(shipCameraPositionFor(routeFrame, progress, shipFocus));
    cam.lookAt(shipFocus);

    const controls = new OrbitControls(cam, renderer.domElement);
    controls.target.copy(shipFocus);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.enablePan = false;
    controls.minDistance = CAMERA_MIN_DISTANCE;
    controls.maxDistance = CAMERA_MAX_DISTANCE;
    controls.maxPolarAngle = Math.PI;
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
    sun.position.copy(routeFrame.midpointUnit).multiplyScalar(GLOBE_RADIUS * 2.2);
    sun.position.y += GLOBE_RADIUS * 0.9;
    sun.target.position.copy(GLOBE_CENTER);
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

    const gridGroup = new THREE.Group();
    scene.add(gridGroup);

    const globeGridLevels = GLOBE_GRID_LEVELS.map((level) => {
      const group = createGlobeGridLevel(level);
      collectOpacityMaterials(group);
      gridGroup.add(group);
      return { key: level.key, group };
    });

    const localGridGroup = createLocalGrid();
    collectOpacityMaterials(localGridGroup);
    placeLocalGridOnRoute(localGridGroup, routeFrame, progress);
    scene.add(localGridGroup);
    updateGridDetail({ cam, controls, globeGridLevels, localGridGroup });

    // Route line: traversed portion is black; remaining route is yellow.
    const remainingRouteLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(buildRouteArcPoints(routeFrame, 0, 1)),
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
      new THREE.BufferGeometry().setFromPoints(buildRouteArcPoints(routeFrame, 0, 0)),
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
    dotA.position.copy(routePointAt(routeFrame, 0, GLOBE_ROUTE_RADIUS + 0.25));
    scene.add(dotA);
    const dotB = new THREE.Mesh(dotGeo, new THREE.MeshBasicMaterial({ color: ROUTE_REMAINING_COLOR, opacity: 0.4, transparent: true }));
    dotB.position.copy(routePointAt(routeFrame, 1, GLOBE_ROUTE_RADIUS + 0.25));
    scene.add(dotB);

    // Ship group (placeholder until STL loads)
    const shipGroup = new THREE.Group();
    placeShipOnRoute(shipGroup, routeFrame, progress);
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
    shipShadow.position.set(0.85, SHIP_SHADOW_Y, 0.2);
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

      // Scale: X is the longest axis (ship length ≈ 7779 mm)
      const scale = SHIP_MODEL_LENGTH / size.x;

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

      // Align STL axes to the ship group: local +Z follows the route tangent.
      mesh.rotation.set(-Math.PI / 2, 0, -Math.PI / 2);

      shipGroup.add(mesh);
      stateRef.current.shipMesh = mesh;
      stateRef.current.shipHitTargets = [mesh];
    });

    stateRef.current = {
      ...stateRef.current,
      renderer,
      scene,
      cam,
      controls,
      shipGroup,
      shipFocus,
      gridGroup,
      globeGridLevels,
      localGridGroup,
      traversedRouteLine,
      remainingRouteLine,
      routeFrame,
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
      updateGridDetail({ cam, controls, globeGridLevels, localGridGroup });
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
      disposeObject3D(scene);
      stateRef.current.landLayer = null;
      renderer.dispose();
      if (el.contains(renderer.domElement)) el.removeChild(renderer.domElement);
    };
  }, [routeGeoKey]);

  // Update ship position on progress change
  useEffect(() => {
    const {
      shipGroup,
      controls,
      cam,
      shipFocus,
      globeGridLevels,
      localGridGroup,
      traversedRouteLine,
      remainingRouteLine,
      routeFrame: currentRouteFrame,
    } = stateRef.current;
    if (!shipGroup || !currentRouteFrame) return;

    const routeProgress = Math.max(0, Math.min(progress, 1));
    placeShipOnRoute(shipGroup, currentRouteFrame, routeProgress);
    if (localGridGroup) {
      placeLocalGridOnRoute(localGridGroup, currentRouteFrame, routeProgress);
    }
    const nextShipFocus = routePointAt(currentRouteFrame, routeProgress, GLOBE_SHIP_RADIUS);

    if (traversedRouteLine && remainingRouteLine) {
      traversedRouteLine.geometry.setFromPoints(buildRouteArcPoints(currentRouteFrame, 0, routeProgress));
      remainingRouteLine.geometry.setFromPoints(buildRouteArcPoints(currentRouteFrame, routeProgress, 1));
      traversedRouteLine.visible = routeProgress > 0.001;
      remainingRouteLine.visible = routeProgress < 0.999;
      traversedRouteLine.geometry.computeBoundingSphere();
      remainingRouteLine.geometry.computeBoundingSphere();
    }
    if (controls && cam && shipFocus) {
      const delta = nextShipFocus.clone().sub(shipFocus);
      cam.position.add(delta);
      controls.target.copy(nextShipFocus);
      shipFocus.copy(nextShipFocus);
      controls.update();
      updateGridDetail({ cam, controls, globeGridLevels, localGridGroup });
    }
  }, [progress, routeGeoKey]);

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
