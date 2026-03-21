import React from 'react';

function CodeEditor({ language, code, onChange }) {
  return (
    <textarea
      value={code}
      onChange={(e) => onChange(e.target.value)}
      rows={20}
      spellCheck={false}
      style={{
        width: '100%',
        fontFamily: 'monospace',
        fontSize: '14px',
        backgroundColor: '#2a2a3e',
        color: '#cdd6f4',
        border: '1px solid #444',
        borderRadius: '4px',
        padding: '12px',
        resize: 'vertical',
      }}
      aria-label={`${language} 코드 에디터`}
    />
  );
}

export default CodeEditor;
