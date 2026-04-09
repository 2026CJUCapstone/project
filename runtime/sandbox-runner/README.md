# sandbox-runner

`sandbox-runner`는 사용자 프로그램을 격리된 환경에서 실행하고,
정책 위반/실패/메트릭을 표준화해 수집하는 인원 B 전용 런타임 영역이다.

## 역할

- 샌드박스 실행 흐름 관리
- 제한 정책 적용
- 실행 결과 수집
- 실패 분류 표준화
- 백엔드 연동용 adapter 제공

## 포함 범위

- `cmd/`
  - 데모/프로토타입 실행 진입점
- `config/`
  - 기본 정책과 실행 환경 설정
- `internal/core/`
  - 러너 상태 전이, 요청 검증, 결과 조립
- `internal/policy/`
  - 실행 엔진 추상화와 정책 템플릿
- `internal/adapter/`
  - 공개 API/백엔드 payload를 내부 요청으로 연결
- `internal/model/`
  - 결과 모델, 코드셋, 스키마
- `scripts/`
  - PoC 빌드/실행 스크립트
- `tests/`
  - 샘플 프로그램, 요청 예시, backend handoff payload 예시

## 현재 상태

- `cmd/poc_runner.py`
  - 내부 요청 JSON 기반 runner 프로토타입
- `cmd/api_demo.py`
  - 공식 `run` 요청 -> adapter -> runner 흐름 데모
- `scripts/build_samples.sh`
  - 테스트 C 샘플 빌드
- `scripts/run_sample.sh`
  - 제한 정책을 적용한 샘플 실행
- `tests/samples/`
  - timeout, OOM, process limit, runtime error 등 검증용 샘플
- `tests/requests/`
  - runner 입력 예시
- `tests/payloads/`
  - backend-worker handoff 예시

## 실행 예시

샘플 빌드:

```bash
bash sandbox-runner/scripts/build_samples.sh
```

내부 runner 실행:

```bash
python3 sandbox-runner/cmd/poc_runner.py sandbox-runner/tests/requests/hello.request.json
```

공개 API 흐름 데모:

```bash
python3 sandbox-runner/cmd/api_demo.py sandbox-runner/tests/requests/public-run.request.json hello
```

## 업로드 원칙

- 업로드 대상:
  - 소스 코드
  - 설정 파일
  - 스크립트
  - 테스트 샘플/요청 예시
- 제외 대상:
  - `build/`
  - `reports/`
  - `__pycache__/`
