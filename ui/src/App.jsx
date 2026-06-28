import React, { useState, useEffect, useCallback, useRef } from 'react';
import HullDiagram from './components/HullDiagram.jsx';

const TICK_STEP_MS = 1000;
const MIN_STEP_SPEED = 1;
const MAX_STEP_SPEED = 64;

export default function App() {
  const [simResult, setSimResult] = useState(null);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState(null);
  const [tickPosition, setTickPosition] = useState(0);
  const [stepSpeed, setStepSpeed] = useState(1);
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

  const loadResult = useCallback(async () => {
    setLoading(true);
    setError(null);
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
  const clampedTickPosition = tickCount > 0
    ? Math.max(0, Math.min(tickPosition, tickCount - 1))
    : 0;
  const activeTickIndex = tickCount > 0
    ? Math.max(0, Math.min(tickCount - 1, Math.round(clampedTickPosition)))
    : 0;
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
  const tickProgress = (() => {
    if (tickCount <= 0 || totalDistanceNm <= 0) {
      return Math.min((simResult?.result?.distance_completed_pct ?? 0) / 100, 1);
    }

    const fromIndex = Math.floor(clampedTickPosition);
    const toIndex = Math.min(tickCount - 1, fromIndex + 1);
    const t = clampedTickPosition - fromIndex;
    const fromDistance = ticks[fromIndex]?.distance_completed_nm ?? 0;
    const toDistance = ticks[toIndex]?.distance_completed_nm ?? fromDistance;
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
      if (!direction || tickCount <= 1) {
        stopHeldStep();
        return;
      }

      const previousTime = lastFrameTimeRef.current ?? now;
      lastFrameTimeRef.current = now;
      const deltaTicks = ((now - previousTime) / TICK_STEP_MS) * stepSpeedRef.current;
      const nextPosition = Math.max(
        0,
        Math.min(tickCount - 1, tickPositionRef.current + direction * deltaTicks),
      );
      setDisplayedTickPosition(nextPosition);

      if (
        (direction > 0 && nextPosition >= tickCount - 1)
        || (direction < 0 && nextPosition <= 0)
      ) {
        stopHeldStep();
        return;
      }

      frameRef.current = window.requestAnimationFrame(stepFrame);
    };

    const startHeldStep = (direction) => {
      if (tickCount <= 1) return;
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
  }, [setDisplayedStepSpeed, setDisplayedTickPosition, tickCount]);

  const canStepBack = tickCount > 1 && clampedTickPosition > 0;
  const canStepForward = tickCount > 1 && clampedTickPosition < tickCount - 1;

  const stepBack = useCallback(() => {
    if (!canStepBack) return;
    setDisplayedTickPosition(Math.max(0, Math.round(tickPositionRef.current) - 1));
  }, [canStepBack, setDisplayedTickPosition]);

  const stepForward = useCallback(() => {
    if (!canStepForward) return;
    setDisplayedTickPosition(Math.min(tickCount - 1, Math.round(tickPositionRef.current) + 1));
  }, [canStepForward, setDisplayedTickPosition, tickCount]);

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

  return (
    <div style={{ width: '100vw', height: '100vh', overflow: 'hidden', background: '#C3C4CA', position: 'relative' }}>
      <HullDiagram simResult={simResult} loading={loading} progress={tickProgress} activeTick={activeTick} />

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
