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
docker build -t compiler-sandbox -f runtime/docker/Dockerfile runtime
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

## Docker

로컬 스택:

```bash
bash scripts/docker_up.sh
```

서버 배포 스택:

```bash
bash scripts/deploy_server.sh
```

프로덕션 프런트엔드는 `/webcompiler/` 베이스 경로를 사용하고, 서버에서는 내부 포트 `127.0.0.1:15173`(frontend), `127.0.0.1:18000`(backend)로 바인딩되도록 구성되어 있다.
