# 준비 상태에 따른 API 로드밸런싱

2026-09-10 연결된 구현 기록. 기준은 `site-audit-2026-09-09.md` 5.4절이다. `deploy_server.sh`는 managed pool과 함께 `edge_deploy.py`의 preflight·prepare·candidate·switch adapter를 호출하지만, 실제 운영 전환은 실행·승인되지 않았다. 트랜잭션형 전환의 전체 end-to-end 검증·rollback·drain 등 아래 잔여 조건 때문에 배포 준비 완료로 보지 않는다. 운영 배포·main push·운영 데이터 변경 없이 격리 서버에서 검증한다.

## 구현한 흐름

1. controller가 해당 색상의 API 서비스 이름을 DNS로 조회한다. IPv4 주소는 명시된 API 네트워크 CIDR 안에 있어야 하며 최대 32개다. 조회가 지연돼도 OS DNS 호출을 계속 쌓지 않고 하나만 유지한다.
2. 각 주소의 `/ready`와 `/health`를 제한된 시간·응답 크기로 확인한다. 준비 상태, 정상 health, 정확한 배포 SHA가 모두 맞는 주소만 선택한다. redirect·중복 헤더·과도한 응답·다른 네트워크의 DNS 응답은 인정하지 않는다.
3. 명시적인 IP upstream을 가진 Nginx 설정을 임시 파일에 쓴 뒤 원자적으로 교체한다. controller는 Nginx 전용 PID namespace에서 PID 1이 Nginx인지 확인하고 HUP을 보낸다.
4. HUP 전달만으로 성공 처리하지 않는다. loopback에서만 읽을 수 있는 설정 generation 파일을 새 Nginx worker가 반환해야 반영됐다고 판단한다. 확인 실패 시 디스크 설정을 마지막 확인본으로 복원하며, 시작 시 확인본이 없으면 빈 pool 설정으로 닫는다.
5. 새 HTTP 요청과 WebSocket handshake는 Unix socket의 `/allow/<generation>` 검사를 통과해야 한다. 오래된 Nginx worker의 generation, 오래된 준비 상태, 중지·정지된 controller에는 요청을 허용하지 않는다. controller 오류는 503으로 반환한다. 기존 WebSocket의 실행을 다른 API로 자동 재생성하지 않는다.

controller에는 Docker socket, 앱 소스 쓰기 mount, DB 비밀값이 필요하지 않다. Nginx와 같은 비root UID로 **그 Nginx의 PID/network namespace만** 공유하고 전용 `/control` volume만 쓴다. API container에는 해당 volume을 연결하지 않는다. 인증 subrequest에는 클라이언트 Cookie·Authorization 등 원래 요청 헤더와 본문을 전달하지 않는다.

`/status`는 Unix socket에서만 제공한다. 준비된 API 하나가 남아 있으면 기존 pool의 서비스는 가능하지만, 배포 승인 기준인 `deploymentReady`는 신선하고 확인된 API가 **두 개 이상**이어야 한다. `app.proxy_promotion`은 SHA·poolId·generation·엄격한 상태값을 확인하고, 같은 generation과 복제본 수가 5초 이상 관측되어야 통과한다. 1초마다 조회하며 실패·구성 변경 시 관측 기간을 다시 시작하고 전체 60초를 넘기지 않는다. 일반 `/ready` 응답 하나로 이를 대신하지 않는다. 배포 스크립트는 target stack readiness 뒤 `edge_deploy` 전환의 pre-gate를 실행하고, adapter의 transactional switch가 edge postflight와 gate를 다시 실행한다. adapter 수준의 실패 복구는 확정 route를 복원하도록 연결됐지만, 전체 배포 스크립트의 성공·rollback 원자성은 아직 실제 운영 흐름으로 검증하지 않았다.

worker readiness 키는 배포 SHA·`RUNTIME_POOL_ID`·`RUNTIME_INSTANCE_ID`로 나눈다. 같은 SHA여도 blue worker만 살아 있으면 green API는 준비 완료가 아니어야 한다. 기존 pool 미분리 구현은 이 조건에서 SQLite·PostgreSQL 모두 green에 200을 반환해 결함을 재현했다. 후속 incarnation 구현은 같은 pool·SHA로 재배포하더라도 이전 worker의 준비 상태를 새 후보가 사용하지 않게 한다. shared-runtime overlay는 pool을 실제 Compose project에서, instance를 영속 후보 예약에서 전달한다. 직접 개발 실행의 pool 기본값은 `local`, instance는 빈 값이며 production은 명시적인 instance를 요구한다. 현재 incarnation의 실제 전체 검증은 진행표에서 추적한다.

Redis namespace·DB queue·`SANDBOX_POOL_ID`는 공통으로 유지한다. 준비 상태 분리를 이유로 이전 worker의 남은 sandbox를 새 worker가 회수하지 못하게 만들면 안 된다. 과거 hostname-only heartbeat는 같은 컨테이너의 재시작 프로세스가 TTL 안에 이전 준비 상태를 재사용할 수 있어, 현재 아래 프로세스 epoch 방식으로 교체하고 있다. drain 완료나 혼합 버전 스키마 호환성은 별도 검증 대상이다.

### Worker 프로세스 준비 상태 — 격리 통합 검증

worker와 개발 모드 내장 worker는 시작할 때 private 디렉터리에 새 epoch·PID·커널 생성 시각·hostname·설정 scope를 원자적으로 기록하고, 실행 동안 독점 파일 잠금을 유지한다. 별도 `app.readiness` 명령은 자기 PID나 import 시 생성한 UUID가 아니라 이 기록을 읽는다. 잠금 관측 전후의 PID 생성 시각과 marker 일치 여부도 확인한다. marker가 없거나 잘못됐거나 다른 소유·권한·symlink면 준비 완료로 판단하지 않는다. Linux에서는 boot ID와 `/proc` 시작 tick, Windows에서는 프로세스 생성 시각을 사용한다.

`WORKER_STATE_DIRECTORY`는 비어 있으면 container-local 임시 경로를 설정 scope로 나눠 사용한다. 지정할 때는 절대 경로여야 하며 POSIX 디렉터리/파일은 해당 UID 소유의 0700/0600이어야 한다. worker와 그 health CLI에는 같은 설정을 전달한다. 같은 호스트에서 동일 runtime worker를 여러 프로세스로 실행하려면 서로 다른 디렉터리를 명시한다. hostname과 이 설정 scope를 합친 stable slot이 Redis 소유권을 구분한다. 이 경로를 사용자 코드 sandbox에 mount하지 않는다.

`workers-v2` 준비 상태는 `slot:epoch`와 만료 시각을 저장하고 별도 owner hash가 현재 epoch를 정한다. 시작 시 이전 epoch를 교체하고 기존 준비 상태를 제거한 뒤 Docker probe를 수행한다. 보고/정리는 예상 epoch가 일치할 때만 유효하며, API 조회도 owner와 준비 상태를 같은 Lua 읽기에서 대조한다. 종료는 진행 중인 보고를 기다린 뒤 epoch를 revoke하므로 늦은 보고가 준비 상태를 다시 만들지 못한다. Redis 손실 후에는 재등록과 새 probe/보고가 필요하다. process crash나 Redis 연결 실패에 따른 외부 API의 감지 지연은 heartbeat 유효 기간(30초)에 제한되며, 이 지연을 0초라고 주장하지 않는다. 실제 CLI는 PID와 수명 잠금도 확인한다.

종료 시에는 긴 claim 완료를 기다리기 전에 준비 상태부터 revoke한다. 이때 process marker의 수명 잠금은 실제 종료까지 유지하되, 그 프로세스의 후속 등록·보고는 금지한다. owner hash만 유실되고 ready entry가 남은 경우도 재등록 중 이전 entry를 제거해 새 probe 이전에는 준비 완료가 되지 않게 한다. 이 두 경계를 포함한 process-epoch-v2 전체 격리 검사는 943 passed /20 host-tool skipped /2 subtests passed(637.54초)이며, 같은 소스의 별도 호스트 검사로 생략된 20개도 통과했다. 이 결과는 아래 후속 API 수명 변경을 포함하지 않는다.

이 식별자는 배포 runtime ID 및 작업 실행 lane UUID와 별개다. 아직 프로세스별 claim 연관·HTTP/WS 진행 수·모든 sandbox와 컨테이너 부재를 증명하는 retirement 절차까지 완료한 것은 아니다. 정확한 최신 실행 결과는 감사 후속 진행표에 기록한다.

### 프로세스 부재 관측 — namespace v7 후속 검증 중

비공개 `python -m app.process_observe --role api|worker --epoch <epoch> --runtime <runtime-id> --pool <pool> --release <sha> --sandbox-pool <sandbox-pool>`은 정확히 등록된 프로세스를 조회만 한다. 설정과 DB의 runtime 메타데이터를 모두 대조하며, DB 기록·claim·컨테이너를 변경하지 않는다. 출력의 `state`는 `alive`, `absent`, `unknown` 중 하나다. **종료 코드 0은 조회 성공일 뿐 부재를 뜻하지 않는다.** 호출자는 runtime·role·epoch·state를 JSON에서 정확히 대조해야 한다. unknown과 관측 오류는 종료 코드1이다.

Linux scope v3는 설정 외에 boot ID·PID namespace·user namespace·유효 UID를 묶는다. `/proc/self`의 PID와 현재 PID, `/proc/1/ns/pid`와 현재 PID namespace도 일치해야 한다. 이는 다른 namespace가 mount한 procfs의 PID 번호를 혼동하지 않기 위한 조건이다([Linux man-pages](https://www.man7.org/linux/man-pages/man7/pid_namespaces.7.html)). PID 시작 tick·boot ID의 형식 오류, 접근 거부, namespace 불일치는 부재 증거로 쓰지 않는다. Windows에서 이 부재 판정은 구현하지 않았으므로 unknown으로 남긴다. 기존 scope marker/DB 행을 새 scope에 자동 귀속하지 않는다.

프로세스가 없다는 관측만으로 미해결 HTTP/WS 기록이나 실행 claim을 지울 수 없다. 컨테이너의 full ID·시작 시점·namespace와 이 관측을 묶는 소유권 snapshot, 재시작/재생성 감지, sandbox 대조 및 검증된 retirement는 후속 구현 대상이다. 최신 로컬·실제 서버 검증 결과는 감사 후속 진행표를 따른다.

### API HTTP·WebSocket 접수와 수명 — 후속 구현 및 검증 중

최신 소스는 API-lifecycle-v2이며 로컬885개 통과, 실제 전체 서버 회귀는 진행 중이다. full-stack에서 발견한 관리자 감사 로그 중복과 CORS preflight 우회를 수정해 admission을 Audit/CORS 바깥에 배치했다. 접수/정리 DB commit은 관리자 변경으로 기록하지 않으며 preflight도 drain 뒤에는503을 반환한다. 거부 응답에는 동일한 허용 Origin 정책을 적용한다. 실제 Uvicorn의 SIGTERM 재전달 종료 코드를 fixture에 반영하고 별도 DB 종료 기록 검증을 유지했다. 정확한 archive와 실행 상태는 감사 후속 진행표를 따른다.

관리되는 runtime의 API는 시작 시 runtime ID와 별개의 프로세스 epoch·PID·생성 시각·hostname·scope를 `api_processes`에 등록한다. HTTP/WS는 본문 처리 전에 `active_api_requests`에 접수 기록을 commit한다. runtime 종료 차단과 같은 DB 잠금을 사용하므로 차단 commit 뒤에는 기존 연결의 다음 HTTP 요청과 새 WebSocket을 거부한다. 먼저 접수된 요청은 응답 스트리밍 또는 WebSocket handler가 끝날 때까지 기록을 유지한다. 코드를 실행하는 job 수명과 HTTP 접수 수명은 별개다.

`RUNTIME_MAX_ACTIVE_REQUESTS`는 runtime 내 API 복제본이 공유하는 HTTP+WS 동시 접수 상한이다. 기본 512, 허용 범위 1–4096이며 실행 큐의 전역 슬롯·IP/계정 제한을 대체하지 않는다. `/health`·`/ready`의 GET/HEAD는 진단을 위해 이 접수 경로를 우회한다. 관리되지 않는 로컬 개발 모드는 이 기록을 만들지 않으므로 종료 증거로 사용할 수 없다.

차단/접수 DB 오류는 HTTP 503(no-store·Retry-After) 또는 accept 이전 WebSocket 거부로 처리한다. 취소가 DB thread의 commit과 겹치면 어느 쪽이 먼저 끝나더라도 해당 요청의 기록만 정리한다. 완료 DB 쓰기가 실패하거나 API가 강제 종료되면 미해결 기록을 보존한다. 오래됐다는 이유로 0으로 바꾸지 않는다. `runtime_drain` 상태에는 `active_http`·`active_websockets`가 추가되며, 프로세스 정상 종료는 자기 요청이 없을 때만 기록한다. 현재 기록만으로 컨테이너·sandbox 종료를 승인하지 않는다.

이 변경은 추가형 `api_processes`·`active_api_requests` 테이블과 schema marker `20260910_api_admission_v5`를 사용한다. 기존 runtime/worker/작업 기록을 수정하거나 lane에서 API 기록을 추정하지 않는다. 이전 v4 marker는 아래 worker/runtime 변경 당시의 버전이다. 로컬 전체 878 passed /141 외부·플랫폼 skipped(35.89초). 실제 API 두 복제본과 별도 runtime에 열린 HTTP 스트림·WebSocket을 유지한 drain, SQLite·PostgreSQL 경합/추가형 migration 및 기존 readiness 회귀는 별도 소스 archive로 격리 서버에서 실행 중이다.

남은 범위: 강제 종료 프로세스의 정확한 부재 확인과 미해결 기록 정리, worker lane과 프로세스의 연결, 유한 시간의 WS 종료 안내 및 전체 edge/Compose retirement 절차. 접수 accounting으로 늘어난 DB 잠금 비용도 혼합 부하 검사 대상이다.

### Worker 작업 배정 차단 — 구현 및 격리 검증

후속 worker-process-binding-v2는 `worker_processes` 테이블과 lane의 nullable `process_id` FK/index를 추가한다. schema marker는 `20260910_worker_process_binding_v6`다. 관리되는 worker의 모든 실행 lane은 시작 때 확인한 동일한 프로세스 epoch에 연결하되 lane UUID는 각각 다르다. 이미 차단된 프로세스는 새 lane UUID로도 claim할 수 없고, 늦게 등록된 lane에는 프로세스의 차단 시각을 반영한다. runtime ID뿐 아니라 pool·release SHA·sandbox pool도 등록/차단/정리 때 대조한다. 기존 lane의 알 수 없는 process는 NULL로 보존한다.

종료 시 프로세스 차단을 commit한 뒤 lane을 차단하고 기존 claim 완료를 기다린다. 남은 running claim이 있으면 lease가 오래됐어도 `stopped_at`을 기록하지 않는다. 기존 claim의 start·renew·finish는 유지하며, 별도 프로세스는 같은 runtime이 아직 유효하면 작업을 받을 수 있다. 이 stop 기록은 worker 역할의 정상 정리 기록이지 OS 프로세스·컨테이너 부재 증명은 아니다.

전용 worker·개발 내장 worker·API의 프로세스 시작/DB 등록은 취소해도 계속 실행될 수 있는 thread 작업이다. 따라서 시작 중 취소되면 해당 thread가 끝난 뒤 그 소유권을 정리하며 반복 취소도 이 순서를 깨지 못한다. marker 정리는 예상 프로세스 identity가 현재 소유자와 같을 때만 수행한다. main lifespan은 소유 자원을 역순으로 정리해 늦은 등록이 열린 process row를 남기지 않게 한다.

현재 로컬 전체930 passed /167 외부·플랫폼 skipped(38.88초). 실제 managed worker2 lanes/실행 중 SIGTERM/기존 작업 완료/새 epoch로 다음 작업 처리, API·worker startup 취소 경합, SQLite·PostgreSQL migration, 기존 API/worker readiness 회귀는 격리 서버에서 집중 검사 중이다. 이 최신 변경의 전체 서버 회귀는 아직 남아 있다. process 부재를 검증하는 별도 reconciliation, sandbox/container 소유권 확인과 bounded retirement 및 전체 cold 배포 검증은 계속 미완료로 추적한다.

`ExecutionWorker` 실행 lane마다 불변 UUID·runtime pool·release SHA·sandbox pool을 기록하고, claim과 같은 DB commit에 `ExecutionJob.worker_id`를 저장한다. `execution_workers.draining_at`은 단조적인 종료 차단 기록이다. 종료 요청과 작업 배정은 같은 DB 잠금으로 직렬화한다. 차단 commit 뒤에는 그 UUID가 새 작업을 받을 수 없지만, 먼저 배정받은 작업은 기존 lease로 결과를 저장할 수 있다. 잠금 대기 또는 만료 sandbox 정리 도중 받은 로컬 종료 신호도 다음 배정 전에 다시 확인한다.

명시적인 initializer가 nullable owner FK·index와 worker 테이블을 추가했다. 후속 incarnation 변경은 worker 행의 별도 `runtime_id`·index를, 현재 runtime fence 변경은 `execution_runtimes` 테이블을 추가한다. schema readiness 버전은 `20260910_runtime_admission_v4`다. 기존 작업의 코드·결과·시각·lease는 보존하고 owner는 모르는 값인 NULL로, 기존 worker의 알 수 없는 runtime은 빈 문자열로 남긴다. 기존 종료 차단 기록도 보존하며 lane 기록으로 runtime 상태를 자동 추정하지 않는다. 구버전 worker는 새 차단을 따르지 않으므로, 실행 중인 구버전이나 소유권 미확인 작업이 없다는 확인 없이 혼합 버전 전환을 안전하다고 판단하면 안 된다.

현재 `worker_status`는 개별 lane의 자체 차단 상태와 DB claim 수를 읽는 내부 진단이다. runtime 차단은 별도로 `execution_runtimes.draining_at`에 저장하며 claim과 같은 DB 잠금으로 직렬화한다. 차단 뒤 새 lane UUID를 생성해도 그 runtime은 새 claim을 받을 수 없다. 기존 claim은 start·renew·finish가 가능하다. API/worker 시작도 해당 runtime이 차단됐으면 거부하고, readiness는 Redis 표시가 남아 있어도 DB 차단을 확인해 거부한다. 외부에서 개별 lane만 차단하는 것은 전체 runtime 차단과 다르다.

비공개 `python -m app.runtime_drain --runtime <id> --pool <pool> --release <sha> --sandbox-pool <sandbox>`는 기본적으로 상태만 조회한다. 네 값 모두 실행 환경의 identity와 같아야 하며 `--begin`을 명시할 때만 영속 차단한다. 알려진 runtime이 없으면 조회는 실패하고, 명시적 차단은 늦은 시작을 막는 tombstone을 만들 수 있다. 이 도구는 컨테이너를 종료하거나 운영 데이터를 삭제하지 않는다. runtime claim 수가 0이어도 알 수 없는 legacy owner·HTTP·WS·sandbox가 없다는 뜻은 아니다. 프로세스/컨테이너 및 health CLI 재시작 식별, API HTTP·WebSocket admission/accounting, 실제 sandbox 부재와 검증된 retirement는 아직 남아 있다. tombstone을 삭제해 같은 UUID의 재배정을 허용하는 보관 정책도 구현하지 않는다. 현재 runtime fence의 실제 통합 검증 상태는 감사 후속 진행표를 따른다.

worker-fence-v2 전체 격리 검증은 700 passed /20 host-tool skipped /2 subtests passed(393.60초)이며, 생략된20개도 같은 소스의 호스트 검사로 통과했다. `test_worker_drain.py`는 SQLite·PostgreSQL 잠금 경합, 기존 claim 완료와 신규 배정 차단, 종료 중 cleanup 및 rollback을 확인한다. `test_worker_schema_migration.py`는 두 DB의 추가형 migration·기존 데이터 보존·FK·반복 실행을 확인한다. `test_execution_worker_live.py`는 실제 worker crash 뒤 다른 pool worker의 sandbox 회수와 owner 보존을, `test_readiness_live.py`는 실제 전용 worker SIGTERM 차단 기록과 다른 pool의 준비 상태 유지를 확인한다. 전체 배포/retirement 검증으로 확대하지 않는다. 정확한 소스와 실행 기록은 [감사 후속 진행표](audit-remediation-status.md)에 기록한다.

## Compose 연결 상태

색상별 `edge_ingress` bridge에는 frontend와 api-proxy만 연결한다. API·worker·DB 연결망은 이 bridge에 연결하지 않는다. `frontend_plane`과 `api_plane`은 internal을 유지하며, 호스트 edge가 사용하는 포트는 명시적인 loopback 매핑으로만 연다. 내부 전용 bridge만 사용하면 이 서버에서 요청된 published port의 실제 매핑이 null이 되는 문제를 재현했다. 외부 연결 bridge와 내부 backend bridge를 함께 사용하는 구성은 [Docker 네트워크 문서](https://docs.docker.com/engine/network/)에도 설명돼 있다. 이 구성은 신뢰된 frontend/proxy의 egress를 허용한다는 뜻이며, 다중 호스트 HA나 상위 네트워크 공격 방어를 제공하지 않는다.

frontend 최종 이미지는 UID/GID10001, 내부8080, read-only root, capability 제거, NNP로 실행하며 PID·임시 파일은 크기가 제한된 `/tmp`에 둔다. 실제 이미지의 PID 원본은 `/run/nginx.pid`임을 확인해 수정했다. 외부 host 포트는 유지하고 Docker의 대상 포트만8080으로 통일한다. 실제 final-stage 테스트와 ingress listener 테스트를 별도로 기록하며, 두 검사를 통과했다고 전체 cold Compose/배포 검증 완료로 보지 않는다.

`base → deploy → shared-runtime → lb → ready-lb` overlay를 실제 Docker Compose로 해석해 검사한다. 마지막 `docker-compose.ready-lb.yml`은 다음 역할을 추가한다.

- `proxy-control-init`: 네트워크 없이 새 전용 volume을 초기화한다. 소유권 변경에 필요한 CHOWN·DAC_OVERRIDE만 허용한다. 파일 권한을 정한 뒤 UID/GID 10001로 넘긴다. 기존 release/poolId가 다르면 거부하고, 같은 설정의 재실행은 동작 중인 설정을 초기화하지 않는다.
- `api-proxy`: API 포트는 외부에 공개하지 않고 이 프록시만 loopback의 색상별 포트를 사용한다. `/control`은 읽기 전용이다.
- `proxy-controller`: 같은 검증 backend image의 별도 진입점이다. root filesystem은 읽기 전용이고 모든 capability를 제거한다. 전용 volume에만 쓰며 자원·로그 크기 상한을 둔다.

control volume 이름은 Compose project·배포 SHA·예약된 runtime instance로 파생한다. owner marker는 SHA·poolId·instance·UID/GID를 확인하므로 같은 SHA·색상의 과거 volume도 새 세대가 채택하지 않는다. controller 잠금은 같은 volume에서 두 controller가 socket이나 설정을 덮는 것을 막는다. `/health` peer 검사와 promotion CLI/edge 검증도 exact instance를 비교한다. 로컬 primitive의 빈 instance 허용은 production CLI가 빈 세대를 허용한다는 뜻이 아니다.

`scripts/ensure_api_network.py`가 배포 디렉터리 소유권·색상 label을 가진 internal bridge를 생성하거나 검증하고 실제 CIDR을 전달한다. RFC1918 IPv4, /16 이상으로 좁은 범위, 최대 4개를 허용하며 기존 네트워크의 다른 소유자·색상·worker/frontend endpoint는 거부한다. controller는 Docker socket을 받지 않는다. 검증 실패 시 네트워크를 지우거나 다른 서비스를 재연결하지 않는다.

최종 overlay의 API plane에는 backend와 api-proxy만 연결한다. frontend는 별도 internal frontend plane에서 api-proxy:8080만 사용한다. frontend의 API·WS·health 라우트도 이 프록시를 거치며, 빌드 인자는 기본 개발용 backend:8000과 managed용 api-proxy:8080 두 값만 허용한다. Nginx 1.27.5와 동적 DNS 설정으로 프록시 주소를 다시 조회한다. 실제 프록시 재생성 후 DNS 복구는 별도 검증 대상이다.

backend·worker·pooler·initializer는 공유 runtime 네트워크를 사용한다. 두 색상의 일반 `pgbouncer` DNS 이름이 섞이지 않도록 runtime DB URL은 색상별 고유 pooler alias를 지정한다. 배포 스크립트는 기존 임의 DATABASE_URL override를 조용히 덮어쓰지 않고 중단한다. 외부 DB 사용은 대상·초기화 경로를 검증한 별도 구성 승인이 필요하다. 운영 Compose 호출은 상속된 `COMPOSE_PROFILES`를 비워 legacy 색상별 DB/Redis가 다시 켜지지 않게 한다.

## Edge adapter 연결 상태

### 물리적 runtime inventory — 후속 구현 및 검증 중

관리형 색상의8개 서비스에는 runtime ID·pool·release SHA·sandbox pool·역할 label을 붙인다. adapter는 후보의 readiness/응답 확인 뒤 `scripts/runtime_inventory.py`로 전체 Docker ID·image ID·생성/시작 시각·재시작 횟수·PID를 조회한다. 최소2개 API와 나머지 필수 역할, controller가 참조하는 proxy의 정확한 PID/network namespace, private control volume, private API/frontend network의 실제 member 집합을 확인한다.

색상 API/frontend 포트는 각각 캡처한 api-proxy/frontend의 loopback published port와 일치해야 한다. 다른 서비스의 published port, 선언하지 않은 network/PID namespace/mount, privileged 실행 및 추가 capability는 거부한다. API/worker 등 제한형 역할에는 read-only root·cap-drop·no-new-privileges도 확인한다. worker만 지정된 Docker socket과 `.sandbox-work` bind mount를 허용한다. 공유 network와 PostgreSQL/Redis 자체는 색상 종료 대상으로 편입하지 않는다.

Docker 조회는 변경 없는 명령만 허용하며 subprocess 출력1MiB/20초 상한을 JSON 해석 전에 적용한다. inventory는64개 컨테이너·256KiB 기록 상한을 두고, 매 조회 시45초 관측 deadline을 확인한다(이미 진행 중인 CLI 한 호출은 자체 timeout으로 끝낸다). 비밀 환경변수·명령행·임의 label 원문은 저장하지 않고 private configuration digest로 변경을 감지한다.

전환 전 두 관측이 일치해야 `state/inventory-<runtime-id>.json`을 private 파일로 저장한다. 기존 기록과 다르면 덮어쓰지 않으며, edge 전환 후 commit 전에 다시 대조한다. 이 기록은 해당 시점의 일치 증거이지, snapshot 이후 프로세스가 영원히 동일하다는 보장이나 중지/삭제 허가가 아니다. 실물 이미지의 source-build provenance, DB process/claim/sandbox와의 연결, 검증된 retirement 및 전체 Compose 배포 리허설은 여전히 남아 있다. 실제 Docker fixture는 작은 sleep/true 서비스로 컨테이너 수명·관계만 검사하며 실제 application 기동 검증과 구분한다.

`deploy_server.sh`의 read-only `edge_deploy.py preflight`는 source archive·secret·stateful service·runtime build보다 먼저 실행된다. `prepare`는 `state/committed.json`을 권위 있는 확정 snapshot으로 복구·검증하고, 그 색상만 `active_color`로 반환한다. `candidate`는 stateful setup 전에 확정 색상 재빌드, pending intent, 미완료 `state/drains`를 거부한다. `switch` 내부에서 사후 검증 뒤 `committed.json`을 확정하고, 이어서 `.deploy/active-color`를 원자적인 호환 projection으로 쓴다. 마지막 projection 쓰기가 실패해도 이미 확정된 새 route를 유지하며 다음 `prepare`가 표시를 복구한다. 이 projection은 색상 선택의 권위 있는 저장소가 아니다.

이 연결은 legacy runtime을 자동 중지하거나 임의로 채택하지 않는다. preflight가 legacy 소유·이름 충돌을 발견하면 명시적 이관을 요구하고, 이전 route의 HTTP·worker·WebSocket drain/retirement은 별도 절차로 남긴다. 따라서 Bash 순서와 adapter 계약이 연결된 것과, 전체 Compose/DB/build 및 실제 controller gate를 포함한 end-to-end 배포가 검증된 것은 구분한다. 실제 Nginx/HTTP fixture에서 adapter의 controller gate만 stub으로 대체했으므로 별도 controller/promotion 테스트와 합쳐 전체 운영 검증을 주장하지 않는다.

## 확인한 것과 남은 검증

후속 edge 트랜잭션 모듈은 별도 실제 Nginx에서 rollback·commit 전후 crash 복구·HTTP/WS 유지·강제 종료 자동 재시작을 검증했고, 현재 `deploy_server.sh`의 adapter 호출 경로에도 연결됐다. 다만 위 fixture의 controller gate는 stub이며 실제 controller와 결합한 전체 배포 검증은 아니다. 프런트 최종 image에는 엄격히 검증한 SHA marker를 추가하고 두 static 경로와 잘못된 build 인자 거부를 실제 검사했다. 구체적인 범위와 잔여 운영 검증은 [edge 전환과 복구](edge-transactions.md)를 참고한다.

이전 전체 결과는 **audit-edge-v5: 실제 서버 570 passed / 20 host-tool skipped, 337.32초**다. 생략된 20개는 실제 호스트에서 edge 2개·공유 Redis/Compose 5개·API bridge 1개·Git/flock 12개로 별도 통과했다. 로컬 507 passed / 83 외부·플랫폼 skipped. 이번 프런트 변경은 최종 이미지 marker와 Nginx 설정이며 실제 final-stage 빌드·응답으로 검증했다. React 소스는 앞선 프런트 47개·타입 검사·빌드 이후 바뀌지 않았다. 소스 SHA와 범위는 [감사 후속 진행표](audit-remediation-status.md)에 기록했다. 실제 전체 배포나 무중단 전환은 아직 검증하지 않았다.

이전 전체 검증은 **audit-ready-v3: 실제 서버 413개 통과/호스트 도구 17개 생략, 295.78초**다. 생략한 검사는 호스트에서 공유 Redis/Compose 5개와 Git/flock 12개로 따로 통과했다. 로컬 전체 357개 통과/외부·플랫폼 73개 생략, 23.41초. 이 검증에는 아래 초기 시험 뒤 추가된 generation fencing·설정 복원·poolId·SHA별 worker 준비 상태 변경도 포함되지만, 이후 배포 연결 변경의 증거는 아니다.

배포 연결 후 audit-promotion-v1의 실제 controller/promotion 집중 검사 86개가 78.29초에 통과했다. 별도 실제 API bridge 생성·재사용·소유권/역할 거부 검사 1개(3.140초), 실제 Compose 해석 4개(0.901초)도 통과했다. 이후 프런트 런타임과 전용 네트워크까지 포함한 후속 검증은 [감사 후속 진행표](audit-remediation-status.md)에 기록한다.

- 실제 API 두 개·worker·Nginx·controller를 새 격리 container로 실행한 첫 시험은 43.85초에 통과했다. 다른 SHA 제외, 정상 API 하나의 중지, controller SIGSTOP/SIGCONT·강제 종료·재시작, worker 중지·재시작을 다뤘다.
- 후속 시험은 60.42초에 통과했다. 실제 initializer의 제한된 capability, 반복 초기화의 설정 보존, 다른 SHA volume 거부, 두 API의 실제 요청 분배, 큰 Cookie의 subrequest 차단 영향 제거, health는 정상이지만 ready가 아닌 API 제외를 추가했다.
- 위 두 시험 뒤 generation fencing·실패 설정 복원·poolId·SHA별 worker readiness를 보강했다. 최신 전체 회귀 결과는 [감사 후속 진행표](audit-remediation-status.md)에 별도로 기록하며 이전 시험으로 최신 변경을 검증했다고 주장하지 않는다.
- 단위/실제 TCP 시험으로 상태 만료 경계, 단일 생존 API, 설정 generation 변경 뒤 이전 승인 거부, 반복된 reload 실패 시 파일 복원·임시 파일 정리, DNS 지연의 단일 호출 유지, HTTP 응답 제한을 확인한다.

아직 남은 주요 작업:

- 연결된 배포 스크립트를 사용하는 전체 cold Compose/blue-green 전환 검증. 현재 실제 bridge·proxy·promotion 검사는 전체 배포 스크립트를 실행한 검사가 아니다.
- 트랜잭션형 edge 교체와 rollback, API/worker/WebSocket drain, 새·이전 스키마/실행 이미지 호환성, 전체 Compose 수명주기와 proxy 자체 재시작.
- 실제 Nginx의 오래된 keepalive 연결에 대한 generation 변경 시험과 idle/queued WebSocket 장시간 시험. 현재 설치된 Uvicorn의 ping 기본값은 20초지만, 이 값만으로 프록시 경유 연결 유지를 검증했다고 보지 않는다.
- 신뢰 ingress의 운영 연결 검증. 명시된 직전 peer의 단일 IP·프로토콜만 받는 ASGI/두 Nginx 경로는 구현했으며, 격리된 두 API·실제 Redis에서 사용자 구분·위조 헤더 무효화·HTTP/WS 공유 제한을 확인했다. 실제 TLS 종단의 헤더 정리와 host→Docker NAT peer 주소는 별도로 확인해야 한다. fixture의 loopback CIDR을 운영 값으로 복사하지 않는다. `WEBCOMPILER_EDGE_TRUSTED_INGRESS_CIDRS`와 `WEBCOMPILER_PROXY_TRUSTED_INGRESS_CIDRS`가 없으면 배포 사전 검사를 거부한다.
- membership 변동 시 reload는 최대 5초마다 수행하고 이전 worker 종료 상한은 150초다. 확인되지 않은 generation은 503으로 닫는다. 이 전환 구간의 지연·오류율과 오래 유지되는 WS worker의 메모리는 혼합 부하 시험에서 측정·개선해야 한다. 정상 사용자 수용 성능을 아직 보장하지 않는다.

근거: [Nginx reload 동작](https://nginx.org/en/docs/control.html), [auth_request 판정](https://nginx.org/en/docs/http/ngx_http_auth_request_module.html), [Docker Compose 서비스 격리 설정](https://docs.docker.com/reference/compose-file/services/).
