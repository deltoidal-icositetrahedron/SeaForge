import React, { useState, useEffect, useCallback, useRef } from 'react';
import HullDiagram from './components/HullDiagram.jsx';
import { MISSIONS } from './missions.js';

const TICK_STEP_MS = 1000;
const MIN_STEP_SPEED = 1;
const MAX_STEP_SPEED = 64;

function fmtNumber(value, digits = 1, fallback = '—') {
  return Number.isFinite(value) ? value.toFixed(digits) : fallback;
}

function fmtRange(range, unit = '', digits = 1) {
  if (!range) return '—';
  const parts = [];
  if (Number.isFinite(range.avg)) parts.push(`avg ${fmtNumber(range.avg, digits)}${unit}`);
  if (Number.isFinite(range.min)) parts.push(`min ${fmtNumber(range.min, digits)}${unit}`);
  if (Number.isFinite(range.max)) parts.push(`max ${fmtNumber(range.max, digits)}${unit}`);
  return parts.length ? parts.join(' / ') : '—';
}

function formatFailureDetail(failure) {
  const detail = failure?.detail;
  if (!detail) return failure?.mode ?? '—';
  const zone = detail.failed_zone ?? 'Component';
  const metric = detail.failed_metric ?? failure?.mode ?? 'failure';
  const value = detail.failed_value ?? 'failed';
  return `${zone} ${metric} ${value}`;
}

export default function App() {
  const [simResult, setSimResult] = useState(null);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState(null);
  const [tickPosition, setTickPosition] = useState(0);
  const [stepSpeed, setStepSpeed] = useState(1);
  const [selectedMission, setSelectedMission] = useState(null);
  const tickPositionRef = useRef(0);
  const stepSpeedRef = useRef(1);
  const heldDirectionRef = useRef(0);
  const frameRef = useRef(null);
  const lastFrameTimeRef = useRef(null);

  const setDisplayedTickPosition = useCallback((nextPosition) => {
    tickPositionRef.current = nextPosition;
    setTickPosition(nextPosition);
  }, []);

  const setDisplayedStepSpeed = useCallback((nextSpeed) => {
    stepSpeedRef.current = nextSpeed;
    setStepSpeed(nextSpeed);
  }, []);

  useEffect(() => {
    if (!selectedMission) {
      setSimResult(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    setSimResult(null);
    fetch('/api/brief', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ brief: selectedMission, tier: 'lowest' }),
    })
      .then(r => {
        if (!r.ok) return r.json().then(d => Promise.reject(new Error(d.error || `HTTP ${r.status}`)));
        return r.json();
      })
      .then(data => {
        setSimResult(data);
        setLoading(false);
      })
      .catch(e => {
        setError(e.message);
        setLoading(false);
      });
  }, [selectedMission]);

  useEffect(() => {
    heldDirectionRef.current = 0;
    lastFrameTimeRef.current = null;
    if (frameRef.current) {
      window.cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
    }
    setDisplayedTickPosition(0);
  }, [setDisplayedTickPosition, simResult]);

  const ticks = Array.isArray(simResult?.ticks) ? simResult.ticks : [];
  const tickCount = ticks.length;
  const completedDistanceNm = simResult?.result?.distance_completed_nm;
  const completedPct = simResult?.result?.distance_completed_pct;
  const totalDistanceFromPct = completedDistanceNm > 0 && completedPct > 0
    ? completedDistanceNm / (completedPct / 100)
    : null;
  const totalDistanceNm = totalDistanceFromPct
    ?? completedDistanceNm
    ?? ticks[tickCount - 1]?.distance_completed_nm
    ?? 0;
  const finalTickDistanceNm = ticks[tickCount - 1]?.distance_completed_nm ?? 0;
  const simulationFailed = simResult?.status === 'failed' || Boolean(simResult?.failure);
  const needsSyntheticDestinationTicks = tickCount > 0
    && !simulationFailed
    && totalDistanceNm > 0
    && finalTickDistanceNm < totalDistanceNm * 0.995;
  const averageTickDistanceNm = tickCount > 1
    ? Math.max(finalTickDistanceNm / (tickCount - 1), totalDistanceNm / 120, 1)
    : Math.max(totalDistanceNm / 120, 1);
  const syntheticDestinationTickCount = needsSyntheticDestinationTicks
    ? Math.max(1, Math.ceil((totalDistanceNm - finalTickDistanceNm) / averageTickDistanceNm))
    : 0;
  const playbackTickCount = tickCount + syntheticDestinationTickCount;
  const playbackMaxPosition = Math.max(0, playbackTickCount - 1);
  const clampedTickPosition = tickCount > 0
    ? Math.max(0, Math.min(tickPosition, playbackMaxPosition))
    : 0;
  const activeTickIndex = tickCount > 0
    ? Math.max(0, Math.min(tickCount - 1, Math.round(clampedTickPosition)))
    : 0;
  const activeTick = tickCount > 0 ? ticks[activeTickIndex] : null;
  const activeRouteSegment = simResult?.voyage?.route_segments?.[activeTick?.segment_index ?? 0] ?? null;
  const activeConditions = activeRouteSegment?.conditions ?? null;
  const env = selectedMission?.environmental_profile ?? null;
  const config = simResult?.configuration ?? null;
  const displayedZones = config?.zones ?? [];
  const failureDetail = formatFailureDetail(simResult?.failure);
  const tickProgress = (() => {
    if (playbackTickCount <= 0 || totalDistanceNm <= 0) {
      return Math.min((simResult?.result?.distance_completed_pct ?? 0) / 100, 1);
    }

    const fromIndex = Math.floor(clampedTickPosition);
    const toIndex = Math.min(playbackTickCount - 1, fromIndex + 1);
    const t = clampedTickPosition - fromIndex;
    const distanceAt = (index) => (
      index >= tickCount
        ? finalTickDistanceNm
          + (totalDistanceNm - finalTickDistanceNm)
            * Math.min((index - tickCount + 1) / syntheticDestinationTickCount, 1)
        : (ticks[index]?.distance_completed_nm ?? 0)
    );
    const fromDistance = distanceAt(fromIndex);
    const toDistance = distanceAt(toIndex);
    return Math.min((fromDistance + (toDistance - fromDistance) * t) / totalDistanceNm, 1);
  })();

  useEffect(() => {
    const stopHeldStep = () => {
      heldDirectionRef.current = 0;
      lastFrameTimeRef.current = null;
      if (frameRef.current) {
        window.cancelAnimationFrame(frameRef.current);
        frameRef.current = null;
      }
    };

    const stepFrame = (now) => {
      const direction = heldDirectionRef.current;
      if (!direction || playbackTickCount <= 1) {
        stopHeldStep();
        return;
      }

      const previousTime = lastFrameTimeRef.current ?? now;
      lastFrameTimeRef.current = now;
      const deltaTicks = ((now - previousTime) / TICK_STEP_MS) * stepSpeedRef.current;
      const nextPosition = Math.max(
        0,
        Math.min(playbackMaxPosition, tickPositionRef.current + direction * deltaTicks),
      );
      setDisplayedTickPosition(nextPosition);

      if (
        (direction > 0 && nextPosition >= playbackMaxPosition)
        || (direction < 0 && nextPosition <= 0)
      ) {
        stopHeldStep();
        return;
      }

      frameRef.current = window.requestAnimationFrame(stepFrame);
    };

    const startHeldStep = (direction) => {
      if (playbackTickCount <= 1) return;
      if (heldDirectionRef.current === direction) return;
      stopHeldStep();
      heldDirectionRef.current = direction;
      lastFrameTimeRef.current = null;
      frameRef.current = window.requestAnimationFrame(stepFrame);
    };

    const onKeyDown = (event) => {
      const target = event.target;
      const isEditable = target instanceof HTMLElement && (
        target.isContentEditable
        || target.tagName === 'INPUT'
        || target.tagName === 'TEXTAREA'
        || target.tagName === 'SELECT'
      );
      if (isEditable) return;

      if (event.code === 'ArrowRight') {
        event.preventDefault();
        startHeldStep(1);
      } else if (event.code === 'ArrowLeft') {
        event.preventDefault();
        startHeldStep(-1);
      } else if (event.code === 'ArrowUp') {
        event.preventDefault();
        setDisplayedStepSpeed(Math.min(MAX_STEP_SPEED, stepSpeedRef.current * 2));
      } else if (event.code === 'ArrowDown') {
        event.preventDefault();
        setDisplayedStepSpeed(Math.max(MIN_STEP_SPEED, stepSpeedRef.current / 2));
      }
    };

    const onKeyUp = (event) => {
      if (
        (event.code === 'ArrowRight' && heldDirectionRef.current > 0)
        || (event.code === 'ArrowLeft' && heldDirectionRef.current < 0)
      ) {
        stopHeldStep();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    window.addEventListener('blur', stopHeldStep);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
      window.removeEventListener('blur', stopHeldStep);
      stopHeldStep();
    };
  }, [playbackMaxPosition, playbackTickCount, setDisplayedStepSpeed, setDisplayedTickPosition]);

  const canStepBack = playbackTickCount > 1 && clampedTickPosition > 0;
  const canStepForward = playbackTickCount > 1 && clampedTickPosition < playbackMaxPosition;

  const stepBack = useCallback(() => {
    if (!canStepBack) return;
    setDisplayedTickPosition(Math.max(0, Math.round(tickPositionRef.current) - 1));
  }, [canStepBack, setDisplayedTickPosition]);

  const stepForward = useCallback(() => {
    if (!canStepForward) return;
    setDisplayedTickPosition(Math.min(playbackMaxPosition, Math.round(tickPositionRef.current) + 1));
  }, [canStepForward, playbackMaxPosition, setDisplayedTickPosition]);

  const cell = {
    fontFamily: "'Courier New', monospace",
    background: '#C3C4CA',
    border: '1px solid rgba(0,0,0,0.13)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: 28,
    lineHeight: 1,
  };
  const panelSectionTitle = {
    padding: '10px 14px 6px',
    fontFamily: "'Courier New', monospace",
    fontSize: 8.5,
    fontWeight: 700,
    letterSpacing: '0.12em',
    textTransform: 'uppercase',
    color: 'rgba(0,0,0,0.36)',
    whiteSpace: 'nowrap',
  };
  const panelRow = {
    display: 'grid',
    gridTemplateColumns: '86px 1fr',
    gap: 8,
    padding: '3px 14px',
    fontFamily: "'Courier New', monospace",
    fontSize: 10,
    lineHeight: 1.25,
    color: 'rgba(0,0,0,0.70)',
  };
  const panelLabel = {
    color: 'rgba(0,0,0,0.38)',
    textTransform: 'uppercase',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  };
  const panelValue = {
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  };
  const renderPanelRow = (label, value) => (
    <div style={panelRow}>
      <span style={panelLabel}>{label}</span>
      <span style={panelValue}>{value ?? '—'}</span>
    </div>
  );

  return (
    <div style={{ width: '100vw', height: '100vh', overflow: 'hidden', background: '#C3C4CA', position: 'relative' }}>
      <HullDiagram
        simResult={simResult}
        loading={loading}
        progress={tickProgress}
        activeTick={activeTick}
        routeGeo={selectedMission ? { origin: selectedMission.origin, waypoints: selectedMission.waypoints ?? [], destination: selectedMission.destination } : null}
      />

      {/* Left side panel */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          height: '100%',
          width: 20,
          background: '#C3C4CA',
          borderRight: '1px solid rgba(0,0,0,0.13)',
          transition: 'width 200ms ease',
          overflow: 'hidden',
          zIndex: 10,
          display: 'flex',
          flexDirection: 'column',
        }}
        onMouseEnter={e => e.currentTarget.style.width = '280px'}
        onMouseLeave={e => e.currentTarget.style.width = '20px'}
      >
        {/* Mission brief section */}
        <div style={{ flexShrink: 0 }}>
          <div style={{
            padding: '10px 14px 8px',
            fontFamily: "'Courier New', monospace",
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'rgba(0,0,0,0.35)',
            whiteSpace: 'nowrap',
            borderBottom: '1px solid rgba(0,0,0,0.08)',
          }}>
            Mission Brief
          </div>
          {MISSIONS.map((m) => {
            const isSelected = selectedMission?.id === m.id;
            return (
              <div
                key={m.id}
                onClick={() => setSelectedMission(isSelected ? null : m)}
                style={{
                  padding: '7px 14px',
                  fontFamily: "'Courier New', monospace",
                  fontSize: 10,
                  letterSpacing: '0.02em',
                  whiteSpace: 'nowrap',
                  cursor: 'pointer',
                  color: isSelected ? 'rgba(0,0,0,0.82)' : 'rgba(0,0,0,0.55)',
                  background: isSelected ? 'rgba(0,0,0,0.06)' : 'transparent',
                  borderBottom: '1px solid rgba(0,0,0,0.06)',
                  display: 'flex',
                  alignItems: 'baseline',
                  gap: 8,
                }}
              >
                <span style={{ color: 'rgba(0,0,0,0.25)', fontSize: 9 }}>
                  {m.id.split('_')[0]}
                </span>
                {m.name}
              </div>
            );
          })}
        </div>

        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            minWidth: 280,
            borderTop: '1px solid rgba(0,0,0,0.08)',
          }}
        >
          <div style={panelSectionTitle}>Mission Environment</div>
          {selectedMission ? (
            <>
              {renderPanelRow('Mission', selectedMission.name)}
              {renderPanelRow('Physics', selectedMission.primary_stressor?.replaceAll('_', ' '))}
              {renderPanelRow('Failure', (selectedMission.failure_modes_under_test ?? []).join(', ') || '—')}
              {simResult?.failure ? renderPanelRow('Failed', failureDetail) : null}
              {renderPanelRow('Leg', activeRouteSegment?.label ?? '—')}
              {renderPanelRow('Waves', activeConditions
                ? `${fmtNumber(activeConditions.hs_m)}m Hs / ${fmtNumber(activeConditions.tp_s)}s Tp`
                : fmtRange(env?.wave_height_m, 'm'))}
              {renderPanelRow('Wind', activeConditions
                ? `${fmtNumber(activeConditions.wind_speed_ms)} m/s`
                : '—')}
              {renderPanelRow('Slamming', activeConditions
                ? `${fmtNumber((activeConditions.slam_probability ?? 0) * 100, 0)}%`
                : (env?.slamming_probability ?? '—'))}
              {renderPanelRow('Water', activeConditions
                ? `${fmtNumber(activeConditions.water_temp_c)}°C`
                : fmtRange(env?.water_temp_c, '°C'))}
              {renderPanelRow('Ice', env?.ice_accretion_risk ?? '—')}
              {renderPanelRow('Salinity', activeConditions
                ? `${fmtNumber(activeConditions.salinity_ppt)} ppt`
                : `${fmtNumber(env?.salinity_ppt)} ppt`)}
              {renderPanelRow('pH', activeConditions
                ? fmtNumber(activeConditions.ph, 2)
                : fmtNumber(env?.ph, 2))}
            </>
          ) : (
            <div style={{ ...panelRow, display: 'block', color: 'rgba(0,0,0,0.42)' }}>
              Select a mission brief.
            </div>
          )}

          <div style={{ ...panelSectionTitle, marginTop: 8 }}>Material Configuration</div>
          {config ? (
            <>
              {renderPanelRow('Shell mass', `${fmtNumber(config.shell_mass_kg, 0)} kg`)}
              {renderPanelRow('Cost', simResult?.result?.total_config_cost_usd
                ? `$${simResult.result.total_config_cost_usd.toLocaleString('en-US', { maximumFractionDigits: 0 })}`
                : '—')}
              {displayedZones.map((zone, index) => (
                <div
                  key={`${zone.zone_key ?? zone.zone}-${index}`}
                  style={{
                    padding: '6px 14px 7px',
                    borderTop: '1px solid rgba(0,0,0,0.07)',
                    fontFamily: "'Courier New', monospace",
                    fontSize: 10,
                    lineHeight: 1.25,
                    color: 'rgba(0,0,0,0.70)',
                  }}
                >
                  <div style={{
                    color: 'rgba(0,0,0,0.74)',
                    marginBottom: 3,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}>
                    {zone.zone ?? 'Component'}
                  </div>
                  <div style={{
                    display: 'grid',
                    gridTemplateColumns: '70px 1fr',
                    gap: 6,
                    color: 'rgba(0,0,0,0.48)',
                  }}>
                    <span>MAT</span>
                    <span style={panelValue}>{zone.material_label ?? zone.material ?? '—'}</span>
                    <span>THK</span>
                    <span style={panelValue}>{fmtNumber(zone.thickness_mm)} mm</span>
                    <span>WLD</span>
                    <span style={panelValue}>{zone.weld_label ?? zone.weld_quality ?? '—'}</span>
                    <span>SEL</span>
                    <span style={panelValue}>{zone.seal_label ?? zone.seal_quality ?? '—'}</span>
                  </div>
                </div>
              ))}
            </>
          ) : (
            <div style={{ ...panelRow, display: 'block', color: 'rgba(0,0,0,0.42)' }}>
              Run a mission to load configuration.
            </div>
          )}
        </div>
      </div>


      {/* Floating transport controls */}
      <div style={{
        position: 'absolute',
        bottom: 24,
        left: '50%',
        transform: 'translateX(-50%)',
        display: 'flex',
        userSelect: 'none',
      }}>
        <button
          onClick={stepBack}
          disabled={!canStepBack}
          aria-label="Step back"
          style={{
            ...cell,
            width: 36,
            marginRight: -1,
            fontSize: 13,
            fontWeight: 700,
            color: 'rgba(0,0,0,0.76)',
            cursor: canStepBack ? 'pointer' : 'default',
            opacity: canStepBack ? 1 : 0.22,
          }}
        >
          &#x276E;
        </button>

        <div style={{
          ...cell,
          width: 36,
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: '0.06em',
          color: 'rgba(0,0,0,0.38)',
          textTransform: 'uppercase',
        }}>
          ×{stepSpeed}
        </div>

        <button
          onClick={stepForward}
          disabled={!canStepForward}
          aria-label="Step forward"
          style={{
            ...cell,
            width: 36,
            marginLeft: -1,
            fontSize: 13,
            fontWeight: 700,
            color: 'rgba(0,0,0,0.76)',
            cursor: canStepForward ? 'pointer' : 'default',
            opacity: canStepForward ? 1 : 0.22,
          }}
        >
          &#x276F;
        </button>
      </div>
    </div>
  );
}
