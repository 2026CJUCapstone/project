# Frontend – React 클라이언트

코드 에디터와 실행 결과를 표시하는 React 웹 애플리케이션입니다.

## 폴더 구조

```
frontend/
├── public/
│   └── index.html           # HTML 진입점
├── src/
│   ├── components/
│   │   ├── CodeEditor/      # 코드 에디터 컴포넌트
│   │   │   └── CodeEditor.jsx
│   │   ├── OutputPanel/     # 실행 결과 출력 컴포넌트
│   │   │   └── OutputPanel.jsx
│   │   └── LanguageSelector/# 언어 선택 드롭다운
│   │       └── LanguageSelector.jsx
│   ├── pages/
│   │   └── CompilerPage.jsx # 메인 컴파일러 페이지
│   ├── services/
│   │   └── api.js           # 백엔드 API 호출 모듈
│   ├── styles/
│   │   └── global.css       # 전역 스타일
│   ├── App.jsx              # 루트 컴포넌트
│   └── index.jsx            # 앱 진입점
├── package.json
└── .env.example
```

## 실행 방법

```bash
npm install
npm start
```

빌드:
```bash
npm run build
```