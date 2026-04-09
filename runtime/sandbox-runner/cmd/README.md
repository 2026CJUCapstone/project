# cmd

실행 바이너리 또는 워커 프로세스 진입점을 두는 디렉터리다.

예상 역할:

- 실행 Job 수신
- 입력 어댑터 호출
- 러너 코어 초기화
- 결과 직렬화 및 반환

현재 추가된 초안:

- `poc_runner.py`
  - 내부 요청 JSON 기반 runner 프로토타입
- `api_demo.py`
  - 공식 `run` 요청 -> adapter -> runner 흐름 데모용 CLI
- `bpp_runner.py`
  - B++ source 또는 JSON request를 받아 `bpp` CLI를 호출하는 runtime entrypoint
