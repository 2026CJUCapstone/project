# adapter

외부 시스템과 러너 코어를 연결하는 계층이다.

예상 책임:

- Job 요청 파싱
- 내부 모델로 변환
- 실행 결과를 외부 응답 형식으로 직렬화

원칙:

- 입력 형식 변경은 이 계층에서만 흡수한다.
- 코어 로직은 외부 JSON/DB 스키마를 직접 다루지 않는다.

현재 추가된 초안:

- `public_api.py`
  - 공식 API 요청 normalizer
  - 공식 API 요청 validator
  - queued 응답 생성
  - admin policy -> internal limits 변환
  - internal result -> public job response mapper
