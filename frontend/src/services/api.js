import axios from 'axios';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000/api/v1';

const apiClient = axios.create({
  baseURL: API_URL,
  headers: { 'Content-Type': 'application/json' },
});

/**
 * 코드 실행 요청
 * @param {string} language - 프로그래밍 언어
 * @param {string} sourceCode - 실행할 소스 코드
 * @param {string} [stdin=''] - 표준 입력
 * @returns {Promise<{stdout, stderr, exit_code, execution_time}>}
 */
export async function runCode(language, sourceCode, stdin = '') {
  const response = await apiClient.post('/compiler/run', {
    language,
    source_code: sourceCode,
    stdin,
  });
  return response.data;
}
