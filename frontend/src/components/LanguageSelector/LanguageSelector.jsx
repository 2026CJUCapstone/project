import React from 'react';

const LANGUAGES = [
  { value: 'python', label: 'Python' },
  { value: 'c', label: 'C' },
  { value: 'cpp', label: 'C++' },
  { value: 'java', label: 'Java' },
  { value: 'javascript', label: 'JavaScript' },
];

function LanguageSelector({ language, onChange }) {
  return (
    <div style={{ marginBottom: '12px' }}>
      <label htmlFor="language-select" style={{ marginRight: '8px' }}>
        언어 선택:
      </label>
      <select
        id="language-select"
        value={language}
        onChange={(e) => onChange(e.target.value)}
        style={{ padding: '4px 8px', borderRadius: '4px' }}
      >
        {LANGUAGES.map((lang) => (
          <option key={lang.value} value={lang.value}>
            {lang.label}
          </option>
        ))}
      </select>
    </div>
  );
}

export default LanguageSelector;
