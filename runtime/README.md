# Runtime – B++ 실행 샌드박스 환경

프로젝트 언어인 B++ 코드를 안전하게 실행하거나,
IR/SSA/ASM 덤프를 생성하기 위한 runtime 영역입니다.

## 폴더 구조

```
runtime/
├── docker/                  # B++ runtime 이미지
│   └── Dockerfile
├── sandbox/                 # 컨테이너 entrypoint
│   └── run.sh
└── sandbox-runner/          # 샌드박스 실행 코어 / adapter / 테스트 자산
```

## 현재 역할

- `bpp <source.bpp>` 실행
- `-dump-ir`, `-dump-ssa`, `-asm` 모드 실행
- 결과 수집 및 JSON 반환
- 내부 검증용 sandbox 테스트 자산 보관

## 실행 방식

### 직접 실행

```bash
runtime/sandbox/run.sh bpp /workspace/hello.bpp --mode run
runtime/sandbox/run.sh bpp /workspace/hello.bpp --mode dump-ssa --opt-level O1
```

### JSON 요청 실행

```bash
runtime/sandbox/run.sh bpp-json /workspace/request.json
```

### B++ runner 직접 호출

```bash
python3 runtime/sandbox-runner/cmd/bpp_runner.py --source /workspace/hello.bpp --mode asm
```

## 참고

- `sandbox-runner/tests/samples/*.c` 는 제품 경로가 아니라 내부 sandbox 정책 검증용 샘플입니다.
- 실제 제품 경로는 B++ 소스 또는 B++ 컴파일 산출물을 받는 runtime entrypoint입니다.

## 빌드 방법

```bash
docker build -t compiler-sandbox ./docker
```
