# policy

실행 제한과 보안 정책을 담당한다.

예상 책임:

- wall time, cpu time, memory, process 제한
- 파일 시스템 접근 규칙
- 네트워크 차단 규칙
- syscall 허용/차단 규칙
- 정책 위반 판정

현재 추가된 초안:

- `engine.py`
  - 실행 엔진 추상화
  - `local` 엔진 구현
  - `namespace` 엔진 placeholder
- `template.py`
  - admin policy payload를 PolicyTemplate로 정규화
  - PolicyTemplate -> ExecutionLimits 변환
