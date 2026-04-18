# model

러너 내부에서 사용하는 도메인 모델을 둔다.

예상 책임:

- 실행 요청 내부 모델
- 실행 결과 내부 모델
- 실패 분류 모델
- 상태 전이 모델

원칙:

- 외부 응답 형식과 분리한다.

현재 추가된 초안:

- `codes.py`
  - runtime outcome / violation reason / signal code 상수
- `request-model.schema.json`
  - 내부 실행 요청 모델의 JSON schema 초안
- `request-model.example.json`
  - 내부 실행 요청 예시
- `result-model.schema.json`
  - 내부 실행 결과 모델의 JSON schema 초안
- `result-model.example.json`
  - Timeout 사례 기준 예시 결과
- `models.py`
  - 내부 요청/결과/제한/위반 모델의 Python dataclass 초안
