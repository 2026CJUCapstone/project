import React, { useState } from 'react';
import CodeEditor from '../components/CodeEditor/CodeEditor';
import LanguageSelector from '../components/LanguageSelector/LanguageSelector';
import OutputPanel from '../components/OutputPanel/OutputPanel';
import { runCode } from '../services/api';

const INITIAL_CODE = {
  python: 'print("Hello, World!")',
  c: '#include <stdio.h>\nint main() {\n  printf("Hello, World!\\n");\n  return 0;\n}',
  cpp: '#include <iostream>\nint main() {\n  std::cout << "Hello, World!" << std::endl;\n  return 0;\n}',
  java: 'public class Main {\n  public static void main(String[] args) {\n    System.out.println("Hello, World!");\n  }\n}',
  javascript: 'console.log("Hello, World!");',
};

function CompilerPage() {
  const [language, setLanguage] = useState('python');
  const [code, setCode] = useState(INITIAL_CODE['python']);
  const [output, setOutput] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleLanguageChange = (lang) => {
    setLanguage(lang);
    setCode(INITIAL_CODE[lang] || '');
    setOutput(null);
    setError(null);
  };

  const handleRun = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await runCode(language, code);
      setOutput(result);
    } catch (err) {
      setError(err.message || '실행 중 오류가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: '24px', maxWidth: '1200px', margin: '0 auto' }}>
      <h1 style={{ marginBottom: '16px' }}>🖥️ Online Compiler</h1>
      <LanguageSelector language={language} onChange={handleLanguageChange} />
      <CodeEditor language={language} code={code} onChange={setCode} />
      <button onClick={handleRun} disabled={loading} style={{ margin: '12px 0' }}>
        {loading ? '실행 중...' : '▶ 실행'}
      </button>
      {error && <p style={{ color: 'red' }}>{error}</p>}
      <OutputPanel output={output} />
    </div>
  );
}

export default CompilerPage;
