# 배포 소스와 실행 이미지 고정

이 문서는 미배포 변경의 동작과 운영 전환 전 조건을 설명한다. 스크립트를 추가하거나 테스트를 통과한 것만으로 운영 배포가 검증된 것은 아니다. 사용자의 별도 지시 없이 main에 push하거나 운영 배포를 실행하지 않는다.

## 검증한 커밋만 배포

검증 SHA는 Compose의 공통 앱 환경에 `DEPLOYMENT_SHA`로 전달한다. API의 `/health`는 `deploymentSha`와 `Cache-Control: no-store`를 반환하며, 설정이 없는 로컬 실행은 null로 표시한다. 이것은 이미지 digest 검증을 대체하지 않는다. 배포 전후 API 전환 검사는 liveness인 `/health`가 아니라 DB·Redis·worker 상태를 확인하는 `/ready`를 사용한다. initializer도 color-local PostgreSQL이 아닌 런타임 pooler의 공유 DB를 직접 초기화하도록 연결했다. 두 색상의 Compose 해석 결과는 검증했지만 실제 신규 환경 배포와 rollback/drain은 아직 미검증이다.

Deploy workflow는 성공한 CI 실행의 `head_sha`를 사용한다. 수동 실행도 동일 SHA에 대해 이 저장소의 `main` push CI 성공 기록을 먼저 확인한다. SHA·저장소·원본 저장소·브랜치·workflow 경로·완료 상태가 맞지 않거나 GitHub API 조회에 실패하면 SSH 전에 중단한다. 같은 이름의 다른 workflow나 fork 저장소의 성공 기록은 인정하지 않는다.

checkout 전에 job 조건에서도 같은 저장소의 main/push 성공만 허용한다. fork PR의 브랜치 이름이 main인 경우에도 그 코드로 검증기나 SSH 도구를 실행하지 않는다. 수동 workflow 실행 역시 main에서만 허용한다.

`verify_deploy_ci.py`는 GitHub API를 읽기만 한다. 요청마다 10초 제한, 응답 4MiB 제한과 유한 페이지 수를 두고, 토큰을 다른 호스트로 넘기는 redirect를 거부한다. 인증 토큰과 응답 본문을 로그에 출력하지 않는다.

## SSH와 소스 갱신

`dispatch_deploy.py`가 한 번의 SSH 연결로 전체 작업을 수행한다. 알려진 호스트 키를 `WEBCOMPILER_DEPLOY_KNOWN_HOSTS`에서 받아 임시 600 파일에 넣고, 정확한 host/port 항목이 있는지 확인한다. `StrictHostKeyChecking=yes`이며 실시간 `ssh-keyscan` 결과를 처음부터 신뢰하는 경로는 없다. 토큰·배포 경로 등은 셸 인자가 아니라 인용 처리한 표준입력으로 보낸다.

`sync_remote_repo.sh`는 `.deploy/deploy.lock`을 잡은 상태로 지정된 40자리 SHA만 fetch한다. origin이 다르거나 tracked 파일에 변경이 있으면 중단한다. detached checkout에서 `--no-overwrite-ignore`를 사용하고 `--force`나 `git clean`은 사용하지 않는다. 무시된 운영 파일과 새 tracked 파일이 충돌하는 경우에도 덮지 않고 실패한다.

동일 잠금은 이미지 빌드와 배포가 끝날 때까지 유지한다. `deploy_guard.sh`는 자식에게 전달된 FD9의 경로와 잠금, 실제 HEAD를 확인한다. 직접 배포 스크립트를 실행하는 경우에도 SHA 지정과 같은 잠금이 필요하다. workflow의 `cancel-in-progress`는 false여서 다음 실행이 현재 전환을 강제로 끊지 않는다.

## 빌드 입력과 컴파일러

### 배포 이름 공간과 비밀 파일

`WEBCOMPILER_PROJECT_PREFIX`의 기본값은 `webcompiler`다. 별도 값은 색상 Compose project, edge·공유 PostgreSQL/Redis의 기본 이름, Redis namespace, sandbox pool과 이미지 태그에 함께 적용된다. 별도 prefix에서는 edge/blue/green의 backend/frontend 포트 여섯 개를 모두 명시해야 한다. 경로의 `.deploy`·`.sandbox-work`는 여전히 checkout에 속하므로 격리 리허설은 별도 checkout과 검증된 별도 자원/포트가 필요하다. 명시적 override를 운영 자원으로 지정하면 prefix만으로 격리되지 않는다. 공용 systemd unit을 사용하는 sandbox updater는 custom prefix에서 배포 시작 전에 거부한다.

`.deploy/runtime-secrets.env`는 실행할 셸 스크립트가 아니라 비밀값·메일 설정의 리터럴 파일이다. `runtime_secrets.py`가 전체 파일을 검증한 뒤 허용된 키만 셸 인용으로 전달한다. POSIX에서 현재 사용자 소유의 일반 파일·600 수준 권한을 요구하고 symlink/FIFO, 중복 키, 지원하지 않는 키, 64KiB 초과 입력을 거부한다. `export`, 단일/이중 인용과 빈 값은 지원하지만 변수·명령 치환은 하지 않는다. 줄 전체 주석만 지원한다. scope/포트/이미지/경로 설정은 이 파일이 아닌 배포 시작 환경에서 공급한다.

허용 키는 `WEBCOMPILER_SECRET_KEY`, `WEBCOMPILER_ADMIN_PASSWORD`, `WEBCOMPILER_POSTGRES_PASSWORD`, `SECRET_KEY`, `ADMIN_PASSWORD`, `PASSWORD_RESET_BASE_URL`, `SMTP_HOST/PORT/USERNAME/PASSWORD/FROM/STARTTLS` 및 마지막 두 종류의 `WEBCOMPILER_` 접두사 형태다. PostgreSQL 비밀값은 운영자가 공급해야 하며 자동 생성·교체하지 않는다. 기존 파일이 shell expansion이나 다른 설정 키를 쓰는 경우 운영자가 먼저 형식을 확인하고 이전해야 한다. 이번 작업에서 실제 운영 비밀 파일을 읽거나 수정하지 않았다.

초기화와 로딩은 같은 파서를 사용하므로 `export`·인용된 기존 키도 유지한다. 입력 오류는 비밀값 없이 진단하며 생성된 export 내용을 로그로 출력하지 않는다. 이 형식 검증은 실제 운영 credential 유효성이나 메일 전달 검증을 대체하지 않는다.

초기화는 POSIX의 `O_NOFOLLOW`·비차단 open·파일 잠금으로 얻은 descriptor를 검사한 후 빠진 앱 키만 기록한다. pathname을 다시 여는 셸 append/chmod는 사용하지 않는다. 필수 PostgreSQL 형식과 기존 앱 key/admin의 최소 길이(32/16자), raw/prefixed alias의 실제 우선순위도 preflight/prepare 앞에서 확인한다. 잘못 제공된 기존 비밀값은 자동 교체하지 않는다. 파일 생성·보완은 읽기 전용 edge preflight 이후, edge prepare 이전에 수행한다.

부모 디렉터리도 현재 사용자 소유·다른 사용자 쓰기 금지인지 확인한 directory FD에 묶는다. 쓰기 전후 파일 identity와 반환 전 부모 identity를 확인하며, 검사한 mapping을 그대로 인용된 export로 받아 prepare 전에 사용한다. prepare 뒤 pathname을 다시 읽지 않는다. 환경에서 이미 공급한 유효한 앱 credential은 생성값으로 바꾸지 않고 같은 값으로 보존한다. 줄바꿈이나 인용 후 4096바이트를 넘는 값은 저장 전에 거부한다. 이 경계는 비밀 파일의 경로 교체를 방어하며, 같은 OS 계정이 전체 코드·프로세스를 제어하는 상황의 격리를 보장하지 않는다.

tracked 파일이 깨끗해도 untracked 파일이 Docker COPY에 섞일 수 있다. 따라서 `materialize_deploy_source.sh`로 해당 커밋의 Git archive를 별도 `.deploy/source-<SHA>-<임의값>`에 추출하고, Compose와 Docker 빌드는 이 디렉터리만 사용한다. Compose의 자동 `.env` 읽기도 비활성화한다. 운영 secret과 sandbox 작업 디렉터리는 기존 PROJECT_ROOT 아래에 남긴다. 소스 아카이브는 감사·복구를 위해 보존하며 보관/정리 정책은 추가 작업이다.

backend 이미지는 `webcompiler-backend:<SHA>`, 배포용 컴파일러는 `compiler-sandbox:<SHA>`로 구분한다. 기본 B++ revision은 `runtime/bpp-ref.txt`에 기록한다. 초기 고정값은 서버의 기존 compiler-sandbox 이미지에서 읽은 `io.bpp.ref` 값이며, 버전을 바꾸려면 이 파일을 수정하고 컴파일러 회귀·이미지 빌드 검증을 다시 수행해야 한다. SHA 태그는 다른 배포·자동 updater와의 혼합을 막지만 레지스트리 digest 고정 및 실제 재빌드 검증을 대체하지 않는다.

자동 updater 설치는 기본적으로 하지 않는다. 명시적으로 사용하는 updater는 deploy.lock→sandbox-updater.lock 순서로 잠그고, 후보 이미지 빌드에는 후보 태그를 직접 전달한다. 기존에 설치된 운영 timer를 이번 로컬 수정으로 중지한 것은 아니다. updater의 stable 태그는 새로운 배포용 SHA 태그와 별개다.

### 제한된 BuildKit builder gate

이미지 build에는 기본 builder나 원격 daemon을 암묵적으로 선택하지 않고 `WEBCOMPILER_BUILD_BUILDER`로 이름을 명시해야 한다. 읽기 전용 `verify_build_builder.py`는 `docker buildx ls`에서 정확히 하나의 static `docker-container` builder와 실행 중인 단일 node만 받아들이며, node endpoint는 정확히 `unix:///var/run/docker.sock`여야 한다. dynamic/default builder, 여러 node, 멈춘 node와 다른 endpoint는 거부한다. 이 검증기는 builder를 생성·bootstrap·수정하지 않는다. 운영 builder의 생성·변경·삭제는 이 변경으로 승인되지 않았으며, 별도 운영 승인과 host 검증이 필요하다.

node 이름으로 대응하는 `buildx_buildkit_<node>` 컨테이너를 찾은 뒤, 실행 중·비정지 상태와 64자리 full container ID를 확인한다. 첫 성공 결과는 `WEBCOMPILER_BUILD_CONTAINER_ID`로 bind되고, 이후 단계는 같은 full ID와 이름 조회가 계속 일치해야 한다. 이름만 같은 교체 컨테이너를 조용히 채택하지 않는다. `WEBCOMPILER_BUILD_MEMORY_MB`(기본 2048), `WEBCOMPILER_BUILD_CPU_MILLIS`(기본 1000), `WEBCOMPILER_BUILD_PIDS`(기본 512)는 유한 범위의 명시 값이어야 한다. verifier는 양의 memory/PID 상한, memory와 같은 swap 한도(추가 swap 없음), CPU quota/period 상한, host PID/network mode 부재를 검사한다.

Linux host에서는 builder 컨테이너의 host PID가 cgroup-v2에서 해당 Docker container scope에 속하는지도 확인하고, 그 scope의 `memory.max`, `memory.swap.max`, `cpu.max`, `pids.max`가 inspect한 HostConfig와 정확히 일치해야 한다. 이것은 builder 컨테이너 경계의 fail-closed 증거다. BuildKit cache와 `--load`한 이미지의 디스크 quota, Docker daemon/host 전체의 자원 경계, 같은 Docker 권한을 가진 다른 주체와의 완전한 동시 변경 방지는 이 gate가 증명하지 않는다.

`build_sandbox_image.sh`는 `docker buildx build --builder … --load`를 사용하고 build 전후에 ID를 다시 확인한다. `deploy_server.sh`와 두 local wrapper는 sandbox build 뒤에도 같은 `WEBCOMPILER_BUILD_CONTAINER_ID`로 verifier를 실행한 후 `docker compose build --builder …`를 명시적으로 수행하고, 다시 검증한 뒤 `docker compose up --no-build`로만 시작한다. 따라서 이 경로에서는 `up --build`가 fallback builder를 고르는 용도로 쓰이지 않는다. optional sandbox updater의 installer도 unit 파일을 쓰기 전에 verifier를 통과해야 하며, systemd 환경에 builder 이름·세 budget·full ID를 그대로 전달한다. 이후 builder가 교체되거나 설정이 달라지면 updater는 이를 새 builder로 채택하지 않고 실패한다.

CI의 local composite action은 `webcompiler-ci` 이름의 기존 builder·컨테이너·state volume이 있으면 재사용하지 않고 거부한 뒤, 고정 BuildKit image와 explicit local endpoint로 전용 builder를 만들도록 선언한다. 이 action은 2GiB memory/no-extra-swap, 1 CPU quota, PID 512 및 `runtime/buildkitd.toml`의 `max-parallelism = 1`을 요청하고, bootstrap 뒤 full ID를 확인해 후속 step에 전달한다. cleanup도 성공적으로 bind된 그 ID를 verifier로 다시 확인할 때만 같은 CI builder를 제거한다. 이는 workflow 설정의 의도와 fail-closed cleanup 경로를 설명할 뿐, GitHub CI가 실제 실행되었다는 증거는 아니다.

격리 host의 v6 smoke는 SHA `82486a1d32340af44cde8065237f7412afd2139f7d8d436d142ba381caac6dc7`에서 1개 test, 38.131초로 완료되었다. 이 test의 BuildKit `RUN`은 container common cgroup 안에 있었고, **test builder**의 512MiB memory/no-extra-swap, 0.25 CPU, 256 PID 설정을 관측했다. 이는 간단한 host cgroup 경계 증거일 뿐이며, 전체 B++ compiler build, backend/frontend app image, Compose 수명주기, GitHub long-E2E 또는 운영 rollout을 검증한 결과가 아니다.

## 증거와 미완료 조건

### 색상과 무관한 DB·Redis 수명

배포 스크립트는 base → deploy → shared-runtime → lb → ready-lb 다섯 Compose 파일을 합친다. shared-runtime은 색상별 PostgreSQL·Redis를 `legacy-color-infra` profile로 제외하고, API·worker·initializer가 필수 공통 Redis URL과 namespace를 사용하도록 한다. 상속된 COMPOSE_PROFILES도 비운다. initializer는 공유 PostgreSQL에 직접, API·worker는 색상별 고유 PgBouncer alias를 통해 같은 DB에 연결한다. 임의 DB URL override는 조용히 변경하지 않고 사전 검증 대상으로 거부한다. 마지막 두 overlay는 private API pool과 managed proxy/promotion을 연결한다. 이 설정은 Docker Compose 2.24.4 이상이 필요하며 스크립트에서 버전을 확인한다. 개발용 base/deploy 실행은 기존 로컬 DB·Redis를 유지한다. 이 배포 스크립트로 실제 운영 전환은 실행하지 않았다.

기본 관리형 Redis는 공유 bridge의 `webcompiler-redis`와 별도 `webcompiler-redis-data` volume을 사용한다. 호스트 포트를 공개하지 않으며, 320MiB 메모리/swap 상한·0.5 CPU·128 PID·로그 회전·read-only root·no-new-privileges를 적용한다. Redis는 256MiB maxmemory/noeviction, AOF everysec을 사용한다. 접근 가능한 bridge에는 신뢰하는 앱 역할만 연결해야 한다. AOF everysec은 전원 장애 시 최근 쓰기 손실을 완전히 막지 못하며 제출의 원본은 PostgreSQL이다. 단일 Redis/호스트의 고가용성은 별도 미완료 조건이다.

`ensure_shared_redis.py`는 배포 경로 해시로 자원 소유권을 확인한다. 이미 있는 자원의 소유자·이미지 설정·네트워크·포트·mount·자원/로그/보안 정책이 다르면 재생성하거나 초기화하지 않고 거부한다. 같은 설정이면 기존 데이터를 유지하고 중지된 같은 컨테이너만 다시 시작한다. 이미지를 자동 pull하지 않는다. 운영자가 외부 Redis URL을 명시했다면 임의의 로컬 Redis로 대체하지 않는다. 해당 외부 서비스의 TLS·인증·가용성·자원 정책은 별도 검증해야 한다.

`verify_shared_redis_cutover.py`는 실행 중인 두 색상과 legacy의 API/worker를 읽기만 한다. 새 배포와 Redis URL 또는 namespace가 다르거나 active-color의 실행 상태를 확인할 수 없으면 중단한다. 기존 실행·quota·lease가 다른 저장소에 남은 채 새 색상을 시작하는 것을 허용하지 않는다. 기존 데이터 이관에 필요한 offline/drain 절차와 검증은 남아 있으며, 이 guard를 우회하는 자동 reset/migration 옵션은 제공하지 않는다. 공유 DB가 비었는데 이전 색상이 있으면 온라인 dump/restore로 전환하지 않고 거부한다.

색상 전환의 `up`은 `--remove-orphans`를 사용하지 않는다. 이전 색상과 legacy 정리는 frontend/API/worker/PgBouncer만 중지하고 DB·Redis·volume은 삭제하지 않는다. 이 변경이 완전한 drain/transactional rollback 구현을 뜻하지는 않는다.

격리 서버에서 실제 Redis 두 클라이언트의 공통 counter, 반복 실행의 동일 container ID, stop/start 후 데이터 유지, 소유권/설정 변경 거부를 검증했다(1개 테스트, 7.703초). 실제 Compose 해석은 두 색상·관리형/외부 URL·필수 설정 누락·개발용 구성 보존을 검증했다(3개 테스트, 0.684초). 실제 앱의 blue/green 전환이나 외부 Redis 연결 시험은 아니다.

### 외부 검증 및 나머지 전환 작업

- 임시 Git 저장소에서 최신 main보다 이전의 검증 SHA 선택, 동시 sync 거부, 자식 프로세스 잠금 유지, dirty/staged/ignored 파일 보존, 잘못된 SHA/origin/잠금 거부, 소스 archive 격리를 검증했다. 실제 운영 checkout이나 DB를 사용하지 않는다.
- CI 조회·SSH 전달은 모의 transport 단위 테스트로 검증했다. 실제 GitHub 환경의 권한·키·보호 규칙과 SSH 배포는 아직 실행하지 않았다.
- 운영 적용 전에 신뢰 경로로 확인한 **정확한 host/port의 known_hosts**를 새 secret에 등록해야 한다. `production` GitHub environment의 승인자·branch 보호 규칙도 실제 설정을 확인해야 한다. environment 이름을 YAML에 쓰는 것만으로 승인 규칙이 생기지 않는다.
- 소스 아카이브·새 helper·B++ pin 파일 모두 동일 검증 커밋에 포함해야 한다. 고정 컴파일러 이미지의 실제 재빌드, 이미지 digest와 provenance, 오래된 source/image 보관 정책은 미완료다.
- [readiness 기반 managed LB](readiness-load-balancing.md)를 deploy_server.sh에 연결했다. 색상별 proxy 포트로 기존 edge 목적지를 바꾸고, 전환 전후 정확 SHA/pool/generation의 두 복제본 상태를 5초 이상 관측하는 검사를 추가했다. 실제 private network·API/worker/proxy/frontend 런타임과 promotion 검증은 전체 배포 스크립트 실행을 대체하지 않는다. 기존 Redis/DB offline cutover, 실제 edge 전환·요청 drain·실패 rollback·전체 Compose 수명주기는 남아 있다. 전체 진행표는 [감사 후속 수정 진행표](audit-remediation-status.md)에 있다.

참고: ignored 파일 덮어쓰기 제어는 [Git checkout 문서](https://git-scm.com/docs/git-checkout), 호스트 키 정책은 [OpenSSH 문서](https://man.openbsd.org/ssh_config#StrictHostKeyChecking)를 기준으로 했다.
