# samples

정상 실행과 비정상 실행을 검증하는 테스트 샘플을 둔다.
이 디렉터리의 샘플은 제품 경로가 아니라 sandbox 정책 검증용 내부 자산이다.

## 현재 샘플 구조

- `hello/`
  - 정상 실행 경로 검증
- `runtime-error/`
  - 사용자 프로그램 비정상 종료 검증
- `segfault-error/`
  - signal 기반 런타임 오류 검증
- `infinite-loop/`
  - 시간 제한 검증
- `memory-exhaustion/`
  - 메모리 제한 검증
- `process-explosion/`
  - 프로세스 수 제한 검증
- `forbidden-file-access/`
  - 파일 접근 차단 검증
- `forbidden-network-access/`
  - 네트워크 차단 검증
- `excessive-output/`
  - 출력 제한 검증
- `io-context/`
  - stdin/args/working directory 검증
- `_template/`
  - 새 샘플 추가용 템플릿

## 샘플 작성 원칙

- 샘플 하나당 하나의 정책/실패 유형 검증에 집중한다.
- 기대 결과는 `failure-classification.md` 기준으로 적는다.
- 정책 검증 PoC의 임시 샘플 언어는 `C`를 사용한다.
- 각 샘플 디렉터리에는 설명 문서와 실제 검증용 `main.c`를 같이 둔다.
