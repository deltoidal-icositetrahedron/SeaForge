import React, { useState, useEffect, useCallback } from 'react';
import HullDiagram from './components/HullDiagram.jsx';

const panelFont = "'Courier New', monospace";

function formatTickValue(value, precision = 2) {
  if (value === null || value === undefined) return 'null';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return String(value);
    if (Math.abs(value) > 0 && Math.abs(value) < 0.001) return value.toExponential(2);
    return value.toLocaleString(undefined, {
      maximumFractionDigits: precision,
      minimumFractionDigits: 0,
    });
  }
  return String(value);
}

function TickStatePanel({ tick, loading, error }) {
  const zones = Array.isArray(tick?.zones) ? tick.zones : [];

  return (
    <aside style={{
      position: 'absolute',
      top: 16,
      right: 16,
      width: 'min(430px, calc(100vw - 32px))',
      maxHeight: 'calc(100vh - 96px)',
      overflowY: 'auto',
      padding: '12px 14px 14px',
      border: '1px solid rgba(0,0,0,0.16)',
      background: 'rgba(195,196,202,0.76)',
      backdropFilter: 'blur(7px)',
      fontFamily: panelFont,
      fontSize: 11,
      lineHeight: 1.35,
      color: 'rgba(0,0,0,0.64)',
      zIndex: 2,
    }}>
      {loading && <div style={{ color: 'rgba(0,0,0,0.48)' }}>LOADING</div>}
      {!loading && error && <div style={{ color: 'rgba(132,0,0,0.66)' }}>{error}</div>}
      {!loading && !error && !tick && <div style={{ color: 'rgba(0,0,0,0.48)' }}>NO TICK DATA</div>}

      {tick && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{
            width: '100%',
            minWidth: 390,
            borderCollapse: 'collapse',
            tableLayout: 'fixed',
          }}>
            <thead>
              <tr style={{ color: 'rgba(0,0,0,0.38)' }}>
                <th style={{ width: '34%', textAlign: 'left', fontWeight: 400, padding: '0 8px 5px 0', border: 'none' }}>zone</th>
                <th style={{ textAlign: 'right', fontWeight: 400, padding: '0 8px 5px 0', border: 'none' }}>stress</th>
                <th style={{ textAlign: 'right', fontWeight: 400, padding: '0 8px 5px 0', border: 'none' }}>fatigue</th>
                <th style={{ textAlign: 'right', fontWeight: 400, padding: '0 8px 5px 0', border: 'none' }}>crack</th>
                <th style={{ textAlign: 'right', fontWeight: 400, padding: '0 0 5px 0', border: 'none' }}>corr</th>
              </tr>
            </thead>
            <tbody>
              {zones.map((zone) => (
                <tr key={zone.zone}>
                  <td style={{ padding: '4px 8px 4px 0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', border: 'none' }}>
                    {zone.zone}
                  </td>
                  <td style={{ padding: '4px 8px 4px 0', textAlign: 'right', border: 'none' }}>
                    {formatTickValue(zone.peak_stress_mpa, 1)}
                  </td>
                  <td style={{ padding: '4px 8px 4px 0', textAlign: 'right', border: 'none' }}>
                    {formatTickValue(zone.fatigue_consumed, 4)}
                  </td>
                  <td style={{ padding: '4px 8px 4px 0', textAlign: 'right', border: 'none' }}>
                    {formatTickValue(zone.crack_half_length_mm, 2)}
                  </td>
                  <td style={{ padding: '4px 0', textAlign: 'right', border: 'none' }}>
                    {formatTickValue(zone.corrosion_depth_mm, 2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </aside>
  );
}

export default function App() {
  const [simResult, setSimResult] = useState(null);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState(null);
  const [tickIndex, setTickIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);

  const loadResult = useCallback(async () => {
    setLoading(true);
    setError(null);
    setIsPlaying(false);
    try {
      const res  = await fetch('/api/result');
      if (res.status === 404) {
        setError('no result — run: npm run sim');
        setSimResult(null);
      } else if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        setError(d.error || `HTTP ${res.status}`);
        setSimResult(null);
      } else {
        setSimResult(await res.json());
      }
    } catch (e) {
      setError(e.message);
      setSimResult(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadResult(); }, [loadResult]);

  useEffect(() => {
    setTickIndex(0);
    setIsPlaying(false);
  }, [simResult]);

  const ticks = Array.isArray(simResult?.ticks) ? simResult.ticks : [];
  const tickCount = ticks.length;
  const activeTickIndex = tickCount > 0 ? Math.min(tickIndex, tickCount - 1) : 0;
  const activeTick = tickCount > 0 ? ticks[activeTickIndex] : null;
  const completedDistanceNm = simResult?.result?.distance_completed_nm;
  const completedPct = simResult?.result?.distance_completed_pct;
  const totalDistanceFromPct = completedDistanceNm > 0 && completedPct > 0
    ? completedDistanceNm / (completedPct / 100)
    : null;
  const totalDistanceNm = totalDistanceFromPct
    ?? completedDistanceNm
    ?? ticks[tickCount - 1]?.distance_completed_nm
    ?? 0;
  const tickProgress = activeTick && totalDistanceNm > 0
    ? Math.min(activeTick.distance_completed_nm / totalDistanceNm, 1)
    : Math.min((simResult?.result?.distance_completed_pct ?? 0) / 100, 1);

  useEffect(() => {
    if (tickCount > 0 && tickIndex > tickCount - 1) {
      setTickIndex(tickCount - 1);
    }
  }, [tickCount, tickIndex]);

  useEffect(() => {
    if (!isPlaying || tickCount <= 1) return undefined;

    const id = window.setInterval(() => {
      setTickIndex((current) => {
        if (current >= tickCount - 1) {
          setIsPlaying(false);
          return current;
        }
        return current + 1;
      });
    }, 750);

    return () => window.clearInterval(id);
  }, [isPlaying, tickCount]);

  const canStepBack = tickCount > 0 && activeTickIndex > 0;
  const canStepForward = tickCount > 0 && activeTickIndex < tickCount - 1;
  const stepBack = useCallback(() => {
    setIsPlaying(false);
    setTickIndex((current) => Math.max(0, current - 1));
  }, []);
  const stepForward = useCallback(() => {
    setIsPlaying(false);
    setTickIndex((current) => Math.min(Math.max(tickCount - 1, 0), current + 1));
  }, [tickCount]);
  const togglePlayback = useCallback(() => {
    if (tickCount <= 1) return;
    setIsPlaying((current) => {
      if (current) return false;
      if (activeTickIndex >= tickCount - 1) {
        setTickIndex(0);
      }
      return true;
    });
  }, [activeTickIndex, tickCount]);

  useEffect(() => {
    const onKeyDown = (event) => {
      const target = event.target;
      const isEditable = target instanceof HTMLElement && (
        target.isContentEditable
        || target.tagName === 'INPUT'
        || target.tagName === 'TEXTAREA'
        || target.tagName === 'SELECT'
      );
      if (isEditable) return;

      if (event.code === 'Space') {
        event.preventDefault();
        togglePlayback();
      } else if (event.code === 'ArrowLeft') {
        event.preventDefault();
        stepBack();
      } else if (event.code === 'ArrowRight') {
        event.preventDefault();
        stepForward();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [stepBack, stepForward, togglePlayback]);

  const controlButtonStyle = {
    width: 26,
    height: 22,
    border: '1px solid rgba(0,0,0,0.22)',
    background: 'transparent',
    color: 'rgba(0,0,0,0.48)',
    fontFamily: "'Courier New', monospace",
    fontSize: 11,
    lineHeight: 1,
    cursor: 'pointer',
  };
  const disabledControlButtonStyle = {
    ...controlButtonStyle,
    opacity: 0.35,
    cursor: 'not-allowed',
  };

  return (
    <div style={{ width: '100vw', height: '100vh', overflow: 'hidden', background: '#C3C4CA', display: 'flex', flexDirection: 'column' }}>

      {/* Full-height mission stage */}
      <div style={{ flex: 1, overflow: 'hidden', position: 'relative' }}>
        <HullDiagram simResult={simResult} loading={loading} progress={tickProgress} activeTick={activeTick} />
        <TickStatePanel
          tick={activeTick}
          loading={loading}
          error={error}
        />
        <div style={{
          position: 'absolute',
          left: '50%',
          bottom: 18,
          transform: 'translateX(-50%)',
          display: 'flex',
          alignItems: 'center',
          gap: 7,
          padding: '6px 9px',
          border: '1px solid rgba(0,0,0,0.16)',
          background: 'rgba(195,196,202,0.78)',
          backdropFilter: 'blur(6px)',
          fontFamily: "'Courier New', monospace",
          zIndex: 2,
        }}>
          <button
            onClick={stepBack}
            disabled={!canStepBack}
            style={canStepBack ? controlButtonStyle : disabledControlButtonStyle}
            title="Step back"
          >
            ‹
          </button>
          <button
            onClick={togglePlayback}
            disabled={tickCount <= 1}
            style={tickCount > 1 ? controlButtonStyle : disabledControlButtonStyle}
            title={isPlaying ? 'Pause' : 'Play'}
          >
            {isPlaying ? 'Ⅱ' : '▶'}
          </button>
          <button
            onClick={stepForward}
            disabled={!canStepForward}
            style={canStepForward ? controlButtonStyle : disabledControlButtonStyle}
            title="Step forward"
          >
            ›
          </button>
        </div>
      </div>
    </div>
  );
}
