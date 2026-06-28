import React, { useState, useEffect, useCallback } from 'react';
import HullDiagram from './components/HullDiagram.jsx';

export default function App() {
  const [simResult, setSimResult] = useState(null);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState(null);

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

  return (
    <div style={{ width: '100vw', height: '100vh', overflow: 'hidden', background: '#e9ebee', display: 'flex', flexDirection: 'column' }}>

      {/* Minimal header */}
      <header style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 18px', height: 40, flexShrink: 0,
        borderBottom: '1px solid rgba(0,0,0,0.1)',
        background: 'rgba(233,235,238,0.95)',
        fontFamily: "'Courier New', monospace",
      }}>
        <span style={{ fontSize: 11, letterSpacing: '0.2em', color: 'rgba(0,0,0,0.35)', textTransform: 'uppercase' }}>
          SEAFORGE V2 — CORSAIR ASV — NORFOLK → BERMUDA
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          {error && <span style={{ fontSize: 10, color: 'rgba(180,0,0,0.6)', letterSpacing: '0.05em' }}>{error}</span>}
          <button
            onClick={loadResult}
            disabled={loading}
            style={{
              border: '1px solid rgba(0,0,0,0.2)', background: 'transparent',
              fontFamily: "'Courier New', monospace", fontSize: 10,
              color: 'rgba(0,0,0,0.4)', padding: '3px 10px', cursor: 'pointer',
              letterSpacing: '0.1em', textTransform: 'uppercase',
            }}
          >
            {loading ? '...' : '↺ RELOAD'}
          </button>
        </div>
      </header>

      {/* Full-height mission stage */}
      <div style={{ flex: 1, overflow: 'hidden' }}>
        <HullDiagram simResult={simResult} loading={loading} />
      </div>
    </div>
  );
}
