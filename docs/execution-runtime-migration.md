# 실행 작업자 분리: 현재 구현과 전환 조건

이 문서는 미배포 변경의 운영 전환 조건이다. 아래 명령이 추가됐다는 사실만으로 기존 배포 스크립트가 전환 준비를 마친 것은 아니다. 운영 적용은 별도 배포 지시 후 수행한다.

## 프로세스 역할

- API는 코드를 DB에 접수하고 작업 ID를 반환한다. WebSocket은 Redis를 통해 입력과 출력을 중계한다. API에는 Docker 소켓과 호스트 소스 디렉터리를 마운트하지 않는다.
- `python -m app.worker`가 DB 임대로 작업을 가져와 Docker에서 실행한다. 작업자만 Docker 소켓과 전용 sandbox 디렉터리를 쓴다. 작업자 호스트의 Docker 권한은 강한 권한이므로 API 분리가 컨테이너 탈출 방어를 대체하지 않는다.
- 대화형 실행은 연결 또는 작업자가 중단되면 취소한다. 이전 입력을 새 프로세스에 자동 재생하지 않는다. 다시 실행하려면 사용자가 실행 버튼을 눌러야 한다.
- 작업자 복제본은 같은 DB와 Redis, 같은 Docker 실행 풀을 사용한다. 현재 구현은 서로 다른 Docker 호스트로 작업자를 임의 확장하는 구성이 아니다.

작업자는 전용 sandbox 디렉터리의 실제 소유 UID/GID로 실행하고 Docker 소켓의 GID만 보조 그룹으로 추가한다. `cap_drop: ALL`을 유지한 root 프로세스도 다른 소유자의 775 디렉터리에 쓸 수 없으므로, 무조건 root로 실행하거나 디렉터리를 777로 바꾸지 않는다. 시작 helper가 `stat`으로 `WEBCOMPILER_WORKER_UID`, `WEBCOMPILER_WORKER_GID`, `WEBCOMPILER_DOCKER_GID`를 설정한다. 작업자는 여전히 Docker 소켓을 통해 호스트에 강한 권한을 가진다. 별도 테스트는 반드시 고유 `SANDBOX_POOL_ID`와 DB/Redis namespace를 사용한다.

## 단일 색상의 다중 API 구성 (미배포)

`docker-compose.lb.yml`은 기본 Compose 위에 덧씌우는 API 풀 설정이다. 기본 두 API는 호스트 포트를 열지 않으며, 비root·read-only Nginx만 loopback의 18000 포트로 공개된다. Compose 2.24.4 이상(`!reset`)과 Nginx 1.27.3 이상의 Docker DNS 동적 upstream 기능이 필요하다.

단독 격리 구성의 프록시 설정은 `python3 scripts/render_api_proxy.py --upstream backend:8000 --docker-dns`의 출력으로 생성한다. 생성한 읽기 가능한 파일의 절대 경로를 `WEBCOMPILER_API_PROXY_CONFIG`로 지정하고, 기본 Compose 뒤에 `-f docker-compose.lb.yml`을 사용한다. 현재 관리형 배포 스크립트는 이 overlay뿐 아니라 `docker-compose.shared-runtime.yml`·`docker-compose.ready-lb.yml`과 edge adapter를 연결한다. 관리형 경로의 설정 생성·readiness 투입·전환 조건은 [readiness 로드밸런싱](readiness-load-balancing.md)과 [edge 전환](edge-transactions.md)을 따른다. 스크립트 연결 자체가 전체 최초 배포·전환·롤백 실물 검증이나 운영 적용 승인을 뜻하지 않는다.

API는 같은 secret·DB·Redis·실행 풀을 사용해야 한다. 프록시는 Docker DNS에서 복제본 주소를 갱신하며 `least_conn`으로 분산한다. 사용자 제공 forwarding header는 덮어쓴다. **바깥 TLS 프록시의 실제 클라이언트 IP 전달·신뢰 범위는 별도 연결 대상**이며 이 설정만으로 IP별 정상 이용자 구분이 완성되지는 않는다. 운영에는 테스트용 upstream 진단 헤더를 내보내지 않는다.

DNS 멤버십 변경 중 기존 연결 시도가 실패하면 Nginx의 이전 peer 세대가 무효화될 수 있다. 제한된 GET/HEAD 재초기화 경로를 두며 POST 본문이나 WebSocket 시작은 그 경로에서 재전송하지 않는다. 제출 재시도는 클라이언트의 동일 요청 ID로 처리한다. 복제본 강제 종료 시 모든 요청의 무중단을 보장하는 구성으로 해석하지 않는다.

## DB 초기화

운영 API에서 자동 DDL은 금지한다. `python -m app.initialize`를 직접 PostgreSQL 연결로 실행한다. PgBouncer의 transaction pooling 경유 주소와 초기화용 직접 주소를 구분한다.

초기화는 한 연결에서 PostgreSQL advisory transaction lock 또는 SQLite writer lock을 잡고 스키마 변경·초기 데이터·이전 기록 전환을 수행한다. 동시에 실행해도 순서대로 처리하며, 실패한 전환은 커밋하지 않는다. 성공한 버전 표식이 있어야 readiness가 통과한다.

이전 버전의 미완료 실행이 있으면 기본적으로 초기화가 실패한다. `--allow-legacy-recovery`는 **이전 API/작업자를 모두 중지하고 해당 sandbox가 정리됐음을 운영자가 확인한 뒤에만** 사용한다. 이 옵션은 실제 프로세스나 Docker 종료를 검사하는 도구가 아니며, 임대 만료를 종료 증거로 취급하지 않는다.

- 대회 제출은 저장된 접수 시각·코드·대회 문제 사본으로 새 작업에 연결한다. 요청 ID와 제출 ID를 유지하며 재실행해도 작업을 중복 생성하지 않는다.
- 이전 일반 실행은 불변 채점 입력이 없으므로 현재 문제로 재채점하지 않는다. 기록이 있다면 시스템 오류로 종료하고 재제출이 필요함을 남긴다. 애초 저장되지 않은 이전 요청의 코드는 복원할 수 없다.
- 복구 건수가 설정된 대기열 한도를 넘으면 전체 전환을 롤백한다. 한도를 검토하거나 별도 복구 계획을 세우기 전 무한 재시도하지 않는다.
- 기존 관리자 비밀번호는 초기화 환경변수로 덮지 않는다. 빈 비밀번호 해시나 과거 취약 기본 비밀번호를 교체하는 경우에는 세션 버전도 올린다.

## 준비 상태와 종료

`/health`는 API 프로세스의 생존 확인이다. `/ready`는 DB 버전 표식, Redis 응답, 최근 작업자 heartbeat를 확인하고 준비되지 않았으면 503을 반환한다. 오류 응답에는 DB 주소·예외·코드를 넣지 않는다.

작업자는 DB·Redis와 Docker 실행 이미지 접근을 확인한 뒤 5초 간격으로 준비 상태를 알린다. heartbeat 유효 시간은 30초다. `python -m app.readiness`는 해당 작업자 컨테이너의 상태를 검사한다. SIGTERM을 받으면 새 작업 접수를 멈추고 준비 상태를 철회하며, 기존 작업은 기본 135초 동안 마무리한다. Compose 종료 유예는 150초다. 이 숫자를 바꾸면 작업 제한 시간과 종료 유예도 함께 검토한다.

## 아직 필요한 배포 연결

1. 초기 전환 때 이전 실행 경로를 정지·배수하고 복구 대상 및 sandbox 정리를 확인한다.
2. 초기화가 실제 공유 DB를 향하게 하고, 배포 색상과 관계없이 API/작업자가 공통 Redis를 사용하게 한다. 기존 색상별 Redis를 그대로 쓰면 안 된다.
3. 검증한 SHA로 이미지를 고정하고, 새 API가 `/ready`를 통과한 뒤 프록시 대상을 전환한다. HTTP와 WebSocket의 배수 및 이전 작업자 종료를 확인한다.
4. 실제 프록시의 두 API 분산·접수 API 종료 후 완료·재시작 복귀·공유 제한·WebSocket은 격리 서버에서 확인했다. 복제본 증감 중 오류 조건, 제한된 혼합 부하 시험 및 실제 배포 경로 연결은 추가 검증한다.
5. 새 실행 본문·결과의 보관 정책, 감사 기록, 이미지 고정 및 외부 백업/알림 설정을 마무리한다.

검증 결과와 남은 항목은 [감사 후속 수정 진행표](audit-remediation-status.md)에 기록한다.
