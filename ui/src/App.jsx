import React, { useState, useEffect, useCallback } from 'react';
import HullDiagram from './components/HullDiagram.jsx';

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
            onClick={() => {
              setIsPlaying(false);
              setTickIndex((current) => Math.max(0, current - 1));
            }}
            disabled={!canStepBack}
            style={canStepBack ? controlButtonStyle : disabledControlButtonStyle}
            title="Step back"
          >
            ‹
          </button>
          <button
            onClick={() => {
              if (isPlaying) {
                setIsPlaying(false);
                return;
              }
              if (tickCount > 0 && activeTickIndex >= tickCount - 1) {
                setTickIndex(0);
              }
              setIsPlaying(true);
            }}
            disabled={tickCount <= 1}
            style={tickCount > 1 ? controlButtonStyle : disabledControlButtonStyle}
            title={isPlaying ? 'Pause' : 'Play'}
          >
            {isPlaying ? 'Ⅱ' : '▶'}
          </button>
          <button
            onClick={() => {
              setIsPlaying(false);
              setTickIndex((current) => Math.min(tickCount - 1, current + 1));
            }}
            disabled={!canStepForward}
            style={canStepForward ? controlButtonStyle : disabledControlButtonStyle}
            title="Step forward"
          >
            ›
          </button>
          <span style={{
            minWidth: 68,
            fontSize: 10,
            letterSpacing: '0.1em',
            color: 'rgba(0,0,0,0.46)',
            textAlign: 'right',
          }}>
            {tickCount > 0
              ? `${String(activeTickIndex + 1).padStart(2, '0')}/${String(tickCount).padStart(2, '0')}`
              : '00/00'}
          </span>
        </div>
      </div>
    </div>
  );
}
