# core

러너의 핵심 실행 흐름을 담당한다.

예상 책임:

- 작업 준비
- 샌드박스 실행 시작/종료
- 상태 전이 관리
- 결과 수집 오케스트레이션

주의:

- 외부 API 형식과 저장소 세부 구현은 알지 않는다.

현재 추가된 초안:

- `state_machine.py`
  - 러너 상태 enum과 허용 전이 검사 함수
- `runner.py`
  - 요청 검증 이후 실행/수집/결과 생성의 코어 흐름
- `validation.py`
  - 내부 ExecutionRequest 검증과 reason code 반환
