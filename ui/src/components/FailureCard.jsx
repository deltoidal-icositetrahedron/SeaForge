import React from 'react';

export default function FailureCard({ simResult }) {
  if (!simResult || simResult.status !== 'failed' || !simResult.failure) return null;

  const f = simResult.failure;

  return (
    <div
      className="fade-in-down"
      style={{
        border: '1px solid #440000',
        background: '#0a0000',
        margin: '0',
      }}
    >
      <div
        style={{
          background: '#140000',
          borderBottom: '1px solid #440000',
          padding: '10px 16px',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
        }}
      >
        <span style={{ color: '#ff3333', fontSize: 13, letterSpacing: '0.1em' }}>
          &#9888; MISSION FAILURE
        </span>
        <span className="badge-failed">{f.mode || 'UNKNOWN MODE'}</span>
      </div>

      <div style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        {f.segment_label && (
          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
            <span
              style={{
                fontSize: 10,
                color: '#555',
                textTransform: 'uppercase',
                letterSpacing: '0.15em',
                minWidth: 130,
                paddingTop: 1,
              }}
            >
              SEGMENT FAILED
            </span>
            <span style={{ color: '#e0e0e0', fontSize: 12 }}>
              {f.segment_label}
              {f.distance_nm !== undefined && (
                <span style={{ color: '#555', marginLeft: 8, fontSize: 11 }}>
                  @ {f.distance_nm.toFixed(0)} nm
                </span>
              )}
            </span>
          </div>
        )}

        {f.why && (
          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
            <span
              style={{
                fontSize: 10,
                color: '#555',
                textTransform: 'uppercase',
                letterSpacing: '0.15em',
                minWidth: 130,
                paddingTop: 1,
              }}
            >
              ANALYSIS
            </span>
            <span style={{ color: '#bb8888', fontSize: 12, lineHeight: 1.5 }}>{f.why}</span>
          </div>
        )}

        {f.suggested_fix && (
          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
            <span
              style={{
                fontSize: 10,
                color: '#555',
                textTransform: 'uppercase',
                letterSpacing: '0.15em',
                minWidth: 130,
                paddingTop: 1,
              }}
            >
              RECOMMENDED ACTION
            </span>
            <span style={{ color: '#00cc66', fontSize: 12, lineHeight: 1.5 }}>{f.suggested_fix}</span>
          </div>
        )}
      </div>
    </div>
  );
}
