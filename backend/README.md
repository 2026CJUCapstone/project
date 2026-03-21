# Backend – FastAPI 서버

코드 제출, 실행 요청, 결과 반환을 담당하는 REST API 서버입니다.

## 폴더 구조

```
backend/
├── app/
│   ├── main.py          # FastAPI 앱 진입점
│   ├── api/
│   │   └── routes/
│   │       └── compiler.py   # 컴파일 관련 API 라우터
│   ├── core/
│   │   └── config.py    # 환경 설정 (CORS, 포트 등)
│   ├── models/
│   │   └── schemas.py   # Pydantic 요청/응답 스키마
│   └── services/
│       └── compiler.py  # 실제 컴파일·실행 비즈니스 로직
├── tests/
│   └── test_compiler.py # API 단위 테스트
├── requirements.txt     # Python 의존성
└── .env.example         # 환경 변수 예시
```

## 실행 방법

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API 문서: http://localhost:8000/docs
