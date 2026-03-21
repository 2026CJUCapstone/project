import React from 'react';

function OutputPanel({ output }) {
  if (!output) return null;

  return (
    <div
      style={{
        backgroundColor: '#181825',
        border: '1px solid #444',
        borderRadius: '4px',
        padding: '12px',
        marginTop: '12px',
      }}
    >
      <h3 style={{ marginBottom: '8px' }}>실행 결과</h3>
      {output.stdout && (
        <pre style={{ color: '#a6e3a1', whiteSpace: 'pre-wrap' }}>{output.stdout}</pre>
      )}
      {output.stderr && (
        <pre style={{ color: '#f38ba8', whiteSpace: 'pre-wrap' }}>{output.stderr}</pre>
      )}
      <p style={{ fontSize: '12px', color: '#888', marginTop: '8px' }}>
        종료 코드: {output.exit_code} | 실행 시간: {output.execution_time}s
      </p>
    </div>
  );
}

export default OutputPanel;
