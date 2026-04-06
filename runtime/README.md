# Runtime – 코드 실행 샌드박스 환경

사용자가 제출한 코드를 안전하게 격리하여 실행하는 Docker 기반 샌드박스입니다.

## 폴더 구조

```
runtime/
├── docker/          # 언어별 Docker 이미지 정의
│   └── Dockerfile   # 기본 샌드박스 이미지
└── sandbox/         # 샌드박스 실행 설정 및 스크립트
    └── run.sh       # 코드 실행 래퍼 스크립트
```

## 지원 예정 언어

- Python
- C / C++
- Java
- JavaScript (Node.js)

## 빌드 방법

```bash
docker build -t compiler-sandbox -f docker/Dockerfile .
```
