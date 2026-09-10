# Edge 전환과 장애 복구

## 기존 색상별 DB·Redis 보존

공용 DB·Redis로 전환하더라도 이전 색상의 데이터 컨테이너를 orphan으로 삭제하지 않는다. 기본 inventory는 알 수 없는 컨테이너를 계속 거부한다. 운영자가 보존 대상을 확인한 경우에만 배포 호출 전에 `WEBCOMPILER_BLUE_PRESERVED_STATEFUL_IDS` / `WEBCOMPILER_GREEN_PRESERVED_STATEFUL_IDS`를 환경 변수로 명시한다. 값은 해당 색상 프로젝트의 PostgreSQL·Redis **전체 64자리 컨테이너 ID**를 쉼표로 연결한 목록이며 색상당 최대4개다. 이름·짧은 ID·중복·다른 프로젝트는 허용하지 않는다. 초기 preflight가 runtime-secrets 파일 로드보다 앞서므로 이 설정을 그 파일에만 추가해서는 안 된다. 이번 구현에서 실제 운영 ID를 선택하거나 등록하지 않았다.

`prepare`는 읽기 전용 preflight 결과를 다시 관찰한 뒤, edge를 시작하기 전에 `.deploy/edge-v2/state/preserved-stateful.json`에 양 색상의 보존 기준을 원자적으로 저장한다. 보존 대상이 없는 색상의 빈 목록도 함께 고정하므로, 중간에 종료돼 한쪽만 나중에 등록할 수 있는 상태가 남지 않는다. 이 파일은 특정 release에 종속되지 않는다. 이후 preflight와 모든 inventory 관찰은 컨테이너 ID·역할·설정 digest가 기존 기준과 같은지 확인한다. 새 release의 capture가 바뀐 설정을 재승인하지 않으며, 보존 목록 추가·누락·교체도 거부한다. 원본 환경 변수나 비밀번호는 기록에 저장하지 않는다.

보존 대상은 새 shared network나 양 색상의 API·frontend·ingress 전용망에 붙을 수 없고, 관리형 `io.webcompiler.*` 소유 라벨이 있으면 예외로 취급하지 않는다. 기존 별도 bridge는 유지할 수 있지만 network ID·endpoint·alias를 포함해 설정을 고정한다. Docker 설정 변경이나 재연결로 관찰값이 달라지면 명시적인 재검증/승인 절차가 필요하다. 기준 파일을 지워 우회하는 운영 절차는 제공하지 않는다.

보존 대상은 managed process/stop 목록에 포함되지 않는다. 이 예외는 데이터 이관·legacy 앱 종료·공용 서비스 채택 또는 운영 배포 허가가 아니다. 실제 관리형 Compose 최초 기동→버전 교체→drain→동일 색상 재생성, 운영 데이터 이관/복구는 별도 미완료 항목이다. 실제 fixture와 현재 소스의 검증 결과는 [감사 후속 진행표](audit-remediation-status.md)에 구분한다.

## 최신 구현 보완 — 신뢰 ingress·실패 후보 정리

아래 초기 구현 이력 중 retirement 미연결 표현은 현재 `scripts/runtime_retirement.py`의 단계별 구현 및 [감사 후속 진행표](audit-remediation-status.md)로 갱신한다. runtime fence→HTTP/WS/claim 정지 대기→sandbox 부재→정확한 컨테이너의 강제 종료 없는 stop 요청→물리 종료 재검증→영속 인증서→해당 drain marker 정리 순서다. 성공한 stop 명령이나 시간 만료만으로 완료 처리하지 않는다. 전체 배포 스크립트를 통한 실제 수명주기 증명은 여전히 남아 있다.

첫 후보 실패로 확정 release가 없는 경우도 처리한다. 소유된 실행 중 edge가 정확한 닫힌 설정을 private socket으로 확인하고, 저장된 설정도 일치하며, 두 listener가503을 반환해야 정리를 시작한다. 후보에 미완료 작업이 있으면 기다린다. 모든 종료 조건을 증명한 인증서가 저장된 뒤에만 정확히 일치하는 실패 후보 예약을 제거하므로, 다음 재시도는 이미 차단된 runtime ID를 재사용하지 않는다. 이 단계의 현재 회귀는 DB/컨테이너 관측 fixture를 쓰므로 실제 전체 cold 배포 시험으로 확대하지 않는다.

`Layout.trusted_ingress`는 owner와 ACK·설정 digest에 포함한다. host edge의 `WEBCOMPILER_EDGE_TRUSTED_INGRESS_CIDRS`, API 프록시의 `WEBCOMPILER_PROXY_TRUSTED_INGRESS_CIDRS`는 확인한 직전 연결 주소를 명시해야 한다. 기존 owner에 이 필드가 없거나 값이 다르면 자동 채택하지 않는다. 운영 TLS 계층의 헤더 정리·실제 peer 주소 및 기존 소유 상태의 이관은 별도 검증/승인 조건이다.

### DB·컨테이너 연결 관찰

읽기 전용 `Deployment.inspect_runtime(release)`는 배포 상태 잠금 안에서 기존 Docker 소유권 기록을 재검증하고, 전체 컨테이너 ID에 고정된 `python -m app.runtime_inspect`를 실행한다. API·worker의 hostname과 namespace scope, 모든 DB process epoch, lane 소유 관계와 작업 수 합계를 대조한다. 알 수 없는 상태·누락·중복·다른 컨테이너 응답·관찰 도중 DB 또는 Docker 변경은 거부한다. 안정된 결과에도 살아 있는 프로세스와 미완료 요청/claim이 포함될 수 있다.

이 경로는 조회만 수행한다. 런타임 fence 설정, 컨테이너 종료, DB 기록 정리, sandbox 종료 확인 또는 drain 기록 제거를 대신하지 않는다. CLI 성공이나 active count 0을 종료 허가로 해석하면 안 된다. 새 hostname 필드가 없는 기존 inventory는 자동으로 덮어쓰지 않고 명시적인 재검증이 필요하다.

2026-09-10 구현·연결 기록. 감사 A09·A18·A25 및 5.4절의 배포 전환에 해당한다. `deploy_server.sh`는 이제 `scripts/edge_deploy.py`의 `preflight`, `prepare`, `candidate`, `switch`를 호출한다. `preflight`는 읽기 전용이고 `prepare`와 `switch`는 실행·영속 상태를 변경할 수 있다. 이는 운영 배포 승인이나 전체 end-to-end 검증 완료를 뜻하지 않는다.

## 저장과 전환 규칙

`scripts/edge_transaction.py`는 Docker와 독립된 상태 전환 모듈이다. 배포 디렉터리 아래의 명시적인 전용 경로만 사용하며 POSIX 소유권·권한·비심볼릭 링크·프로세스 잠금을 검사한다. 배포 전체 잠금은 호출자가 별도로 유지해야 한다.

- `owner.json`: listener 포트 구성과 저장소 형식. 소유 표시가 없는 기존 디렉터리는 채택하지 않는다.
- `config/nginx.conf`: Nginx가 읽는 설정. 디렉터리를 읽기 전용으로 bind mount하므로 파일의 원자적 교체가 실제 container에도 보인다.
- `status/control.sock`: 해당 계정만 접근하는 Nginx 응답 소켓. 공개 HTTP 경로가 아니다.
- `state/committed.json`: 확정된 색상·SHA·포트·generation, 설정 원문과 digest, 기대 응답을 함께 저장하는 **권위 있는 확정 snapshot**이다. 색상 선택과 복구는 이 기록을 기준으로 하며, 복구 시 새 버전의 렌더러로 이전 설정을 다시 만들지 않는다.
- `state/pending.json`: 전환 전 확정 상태와 후보 상태, operation ID를 저장한다. 롤백 중에도 원래 후보 정보를 보존한다.
- `state/candidate.json`: Compose를 시작하기 전에 예약한 색상·SHA·포트·배포 세대 ID·routing generation이다. 같은 미완료 후보의 재시도는 같은 기록을 사용한다. 다른 후보, 손상된 기록, 미완료 전환·종료 기록은 덮어쓰지 않고 거부한다.
- `state/drains/`: 확정되지 않은 후보 또는 이전 버전 중 종료 확인이 필요한 대상. 현재 유지하는 대상과 구분해서 기록한다. 첫 배포 성공에는 이전 서버가 없으므로 만들지 않는다.
- `state/inventory-<runtime-id>.json`: 후보 전환 전에 관찰한 실제 컨테이너 ID·시작 시점·이미지 ID·역할/세대·namespace·네트워크·loopback 포트의 소유권 기록이다. 전환 전 두 번의 관찰이 같아야 저장하고 전환 후 다시 대조한다. 원문 환경 변수와 비밀은 기록하지 않는다. 같은 마운트 목록의 순서 차이는 목적지별 정규화로 처리하지만 중복 목적지·내용 변경·컨테이너 교체·재시작은 거부한다. 기존 기록이 다르면 덮어쓰지 않는다. 이 snapshot은 프로세스·요청·claim·sandbox 종료 증거나 컨테이너 삭제 권한이 아니다.

후보 사전 검사 → intent 저장 → 설정 파일 교체 → Nginx 문법 검사와 reload → private socket에서 정확한 설정 확인 → 앱 사후 검사 → commit 기록 → intent 정리 순서다. 파일은 임시 파일 쓰기·fsync·원자적 교체·부모 디렉터리 fsync로 저장한다.

commit 이전의 중단은 이전 확정 설정으로 복구한다. commit 이후 intent 정리 전 중단은 새 확정 설정을 유지한다. 최초 배포가 실패하고 확정본이 없으면 두 listener는 503으로 닫는다. 복구의 Nginx 확인 또는 앱 검증이 실패하면 intent를 남기고 성공으로 보고하지 않는다. 손상된 intent는 지우거나 임의 해석하지 않는다.

미완료 intent가 없는 정상 복구 호출은 현재 상태만 확인한다. 확인되지 않은 설정 차이가 있으면 명시적 repair가 필요하다. 종료 대기 기록의 저장 상한은 새 전환만 제한하며, 비상 복구를 막지 않는다. **이 상한은 안전한 drain 확인이나 서버 종료 권한을 대신하지 않는다.**

## 배포 세대 예약 — 구현, 격리 검증 진행 중

이전 구현은 `candidate()`가 만드는 UUID를 저장하지 않고 `switch()`에서 새 UUID를 만들었다. 현재는 후보 생성 때 서로 별개인 배포 runtime ID와 routing generation을 예약하고, 후보 재시도 및 `switch()`가 그 기록을 읽는다. 후보 없이 전환하거나 다른 SHA·색상·포트를 재사용하는 요청은 거부한다. commit 뒤에도 마지막 후보를 보존하므로 후보 정리 중단이 새 ID 생성으로 이어지지 않는다. 확정본과 같은 후보 기록만 다음 예약으로 대체할 수 있으며, 미완료 drain 기록이 있으면 여전히 거부한다. 빌드 중단 뒤 실행 중인 서비스가 있을 수 있으므로 실패 후보를 자동 삭제하지 않는다.

배포 runtime ID, 프로세스 재시작 ID, worker lane UUID, routing generation은 서로 다른 수명과 역할을 갖는다. `ExecutionJob.worker_id`는 lane UUID로 유지하고 worker 기록에 별도 `runtime_id`를 추가했다. 예약 ID는 production overlay의 initializer·API·worker·controller·proxy initializer에 전달하고 control volume 이름·owner에도 포함한다. `/health`, worker 준비 상태 키, peer 선택, promotion CLI와 edge 사후 검증은 정확한 세대까지 비교한다. caller의 `RUNTIME_INSTANCE_ID`로 예약 ID를 덮어쓸 수 없다. production 앱 시작에는 명시적인 nonzero 32-hex ID가 필요하며, 로컬 개발의 빈 ID는 배포 증거가 아니다.

runtime 전체의 영속 worker claim 차단과 정확한 대상에만 동작하는 비공개 `app.runtime_drain` CLI를 추가했다. 현재 통합 검증 중이며 아직 edge retirement에 연결하지 않았다. 전체 Bash/Compose 시작을 포함한 후보 예약 전후 crash 복구, API HTTP/WS admission 및 진행 수 집계, worker 프로세스 health/CLI 재시작 식별과 개별 프로세스/샌드박스 부재 확인은 남아 있다. 이 조건을 완료해야 drain 기록을 검증된 retirement로 전환할 수 있다. worker/runtime DB 차단 및 claim 수 조회는 이 절차의 일부이며, 그 수가 0이라는 이유로 컨테이너를 종료하거나 기록을 삭제하지 않는다. 과거 runtime ID 없는 DB 행과 edge snapshot을 임의로 새 배포에 귀속시키지 않는다. 이전 형식 snapshot의 관리형 전환은 명시적인 검증/이관 대상이며 자동 수리하지 않는다.

## Nginx 실행과 검증

종료 확인의 선행 자료는 비공개 `python -m app.runtime_inspect --runtime <id> --pool <pool> --release <sha> --sandbox-pool <pool>`로 조회한다. 실행 컨테이너의 구성과 정확히 같은 세대여야 하고, 먼저 영속적인 runtime drain이 설정돼 있어야 한다. 프로세스·lane·HTTP/WS·만료됐지만 아직 running인 claim을 한 DB snapshot으로 읽는다. 등록 누락, 알 수 없는 lane 소유자·요청 종류, 조회 상한 초과는 부분 결과로 대신하지 않고 실패한다. 코드·실행 결과·사용자 정보는 조회 결과에 포함하지 않는다.

`--local-role api` 또는 `worker`는 현재 hostname과 커널 namespace 기반 scope에 속한 epoch만 관찰한다. 빈 결과와 unknown은 실패이며, 성공(exit0)에도 alive와 absent가 모두 포함될 수 있다. **exit0 또는 active0만으로 종료를 허가하면 안 된다.** 메인 스레드가 zombie여도 다른 스레드가 살아 있는 경우에는 absent를 반환하지 않는다. 현재 이 CLI는 읽기 전용 증거 수집이며, Docker snapshot과 모든 epoch의 완전한 연결·별도 sandbox 확인·종료 후 재검증을 수행하는 retirement 절차는 아직 구현 중이다.

`scripts/edge_runtime.py`는 nginx:1.27.5-alpine의 사전 설치된 image ID를 사용한다. 전용 container는 비root, read-only filesystem, capability 제거, no-new-privileges, 96MiB 메모리·swap 동일 상한, 0.25 CPU, PID 64개와 제한된 로그를 사용한다. 두 listener는 host network의 loopback 주소만 사용한다. 기존 container는 소유 label·정확한 실행 명령·image·mount·자원 구성이 일치해야 한다. 다른 소유자의 container를 지우거나 점유 포트를 비우지 않는다.

`launch_committed()`는 최초 또는 중지된 edge를 확정 설정으로 시작한다. 후보 활성화는 이미 검증되어 실행 중인 container에서만 가능하다. HTTP generation 경로는 공개하지 않으며, private socket 응답의 release·layout·generation·template digest가 모두 맞아야 한다. 긴 호스트 경로는 디렉터리 fd를 통해 소켓에 연결한다.

설정 확인만으로 전환 성공으로 보지 않는다. 실제 시험에서 새 generation 응답 직후에도 이전 Nginx worker가 새 public 요청을 잠시 받았다. `wait_postflight`는 제한된 시간 안에 두 listener의 API와 독립적인 프런트 응답이 연속해서 기대 대상인지 확인하게 한다. `edge_deploy.Deployment.switch()`는 전환 전 `gate`·target 검증과 전환 후 edge 검증·`gate`를 `Transaction.switch()`의 pre/postflight로 연결한다. 다만 이 문서의 HTTP fixture gate는 실제 controller가 아닌 stub이므로, 별도 controller/promotion 검사와 합쳐 전체 운영 배포 검증의 증거로 주장하지 않는다. 단순 200 응답으로 대신하면 안 된다.

reload에는 container 내부의 `nginx -s reload`를 사용한다. Docker kill API를 통한 HUP은 수동 중지 상태를 기록해 나중의 자동 재시작을 막을 수 있었다. 실제 강제 종료 회귀에서 확인한 결함이며, [Moby 구현](https://raw.githubusercontent.com/moby/moby/master/daemon/kill.go)과 [Docker 재시작 정책](https://docs.docker.com/engine/containers/start-containers-automatically/)을 함께 확인했다.

강제 종료는 Unix 소켓 경로를 남길 수 있다. Docker가 이전 container 프로세스를 종료한 뒤 실행하는 시작 명령은 전용 경로의 같은 UID 소켓만 정리한다. 일반 파일·심볼릭 링크·다른 UID의 소켓은 거부한다. 살아 있는 Nginx 옆에서 임의로 소켓을 삭제하지 않는다.

## 현재 검증 범위

실제 격리 호스트에서 다음 흐름을 검사한다. API·프런트 역할은 각각 별도의 loopback HTTP fixture이며 실제 운영 API 배포의 증거는 아니다.

- 503 초기 상태, blue 전환, 두 listener 및 프런트 경로 검증
- green 사후 검사 실패와 blue 복구
- 전환 전 HTTP 제출을 한 번만 처리하고, blue 및 잠시 열린 green의 WebSocket 연결을 롤백 이후까지 유지
- 실제 자식 프로세스 종료로 남긴 후보 설정을 Nginx 재시작이 읽은 뒤 이전 commit으로 복구
- 새 commit 저장 후 프로세스 종료 시 새 버전 유지
- 소유권·명령·container PID 확인 후 pidfd로 master 강제 종료, 자동 재시작·PID 변경·RestartCount 증가 확인

기본 흐름은 30.611초에 통과했고, 일반 파일·심볼릭 링크 보호를 추가한 실제 edge 검사 2개도 32.458초에 통과했다. 이전 audit-edge-v5 전체 서버 검사570개 통과/호스트 전용20개 생략, 337.32초. 해당20개는 호스트에서 별도 통과했고, 로컬은507개 통과/외부·플랫폼83개 생략이다. 프런트 marker 실제 최종 이미지·managed pool을 포함한 집중 검사73개도93.87초에 통과했다. 정확한 소스 해시와 범위는 `audit-remediation-status.md`에 기록한다.

## 배포 연결 후 남은 작업

- `deploy_server.sh`는 source archive·secret·stateful 서비스·runtime build 전에 read-only `preflight`를 수행한다. `prepare`는 확정 snapshot을 복구·확인하고 그 색상을 반환한다. `candidate`는 stateful setup 전에 같은 확정 색상 재빌드, pending intent, 미완료 drain 기록을 거부한다. legacy 중지·채택은 여전히 별도 승인된 이관 절차로 분리한다.
- 기존 shared PostgreSQL helper의 같은 이름 container 자동 채택·시작·network 연결을 없애고, 소유권/설정 검증 및 생성 자원 상한을 적용한다. shared Redis의 검증을 PostgreSQL 검증으로 간주하지 않는다.
- `committed.json`을 색상 선택과 복구의 유일한 기준으로 사용하고 `.deploy/active-color`는 `Store.write`로 원자적으로 갱신하는 호환 projection으로만 유지한다. 소스 archive와 영속 edge 상태를 분리한다.
- 후보와 이전 버전 모두의 API·worker·HTTP keepalive·WebSocket 작업을 확인하는 명시적인 drain/종료 기록과 재실행 복구. 전환이 남긴 `state/drains`가 있으면 검증된 drain reconciliation 전까지 다음 candidate build를 거부한다. 150초 shutdown 상한은 정상 drain 완료의 증거가 아니다.
- 실제 배포 스크립트의 cold start·두 색상 전환·실패 rollback·상태 표시 갱신 중단·proxy 재생성/DNS 복구·스키마 호환성 검사. 현재 adapter의 end-to-end 동작과 전체 Bash/build/DB/controller gate 결합은 아직 실제 배포로 검증하지 않았다.
- 외부 TLS 경로의 검증과 신뢰 ingress 설정. 임의 X-Forwarded-For 신뢰는 허용하지 않는다.
- 5.4절의 혼합 부하·정상 사용자 지연·연결 재시도·작업/점수 무결성 측정.

운영 데이터 변경·배포·main push는 별도 명시적 승인 없이는 실행하지 않는다.
