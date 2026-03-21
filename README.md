# 컴파일러 웹사이트 (Online Compiler)

온라인 코드 컴파일 및 실행 서비스입니다.

## 프로젝트 구조

```
project/
├── runtime/      # 코드 실행 샌드박스 환경 구성 (Docker)
├── backend/      # FastAPI 백엔드 서버
└── frontend/     # React 프론트엔드
```

## 각 모듈 설명

| 폴더 | 역할 |
|------|------|
| `runtime/` | 코드 격리 실행 환경 (Docker 기반 샌드박스) |
| `backend/` | REST API 서버 – 코드 제출·실행 요청 처리 |
| `frontend/` | 사용자 인터페이스 – 코드 에디터 및 결과 출력 |

## 빠른 시작

### 런타임 환경 빌드
```bash
cd runtime/docker
docker build -t compiler-sandbox .
```

### 백엔드 실행
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### 프론트엔드 실행
```bash
cd frontend
npm install
npm start
```