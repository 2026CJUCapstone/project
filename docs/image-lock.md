# 기본 이미지 고정과 검증 (A17)

## 반영한 범위

`runtime/image-lock.json`은 외부 이미지 8종의 multi-platform index digest와 Linux amd64 하위 manifest digest를 기록한다. 처음7종을 고정한 뒤 Node24 glibc 공급 이미지를 추가했다. 2026-09-10 Docker Hub에서 받은 manifest 원문 바이트의 SHA-256과 응답 `Docker-Content-Digest`가 같은지 대조했다. Node 두 이미지의 config 원문 hash와 `NODE_VERSION=24.21.0`도 확인했다. 이미지 layer를 다운로드하거나 서버 컨테이너를 변경하지 않았다.

Dockerfile과 Compose에는 `이름:태그@sha256:...` 형태의 **index digest**를 사용한다. 태그는 읽기 위한 설명이고 콘텐츠 선택은 digest로 고정된다. amd64 하위 digest는 검증 증거로 기록하며 index digest 또는 Docker의 로컬 이미지 config ID와 혼동하지 않는다. [Docker 이미지 고정 안내](https://docs.docker.com/build/building/best-practices/).

| 이미지 | 고정한 소비 지점 |
|---|---|
| Python 3.12 slim | backend Dockerfile |
| Node 24 alpine | frontend 빌드 단계, Node24.21.0 |
| Node 24 bookworm slim | Ubuntu 실행 이미지에 복사할 glibc Node24.21.0/npm 공급 단계 |
| Nginx 1.30.4 alpine-slim | frontend 실행 단계, API 프록시 Compose 기본값, 외부 edge 기본값; 실제 이미지 검사와 Nginx 회귀는 [보안 검사 기록](image-security.md) 참조 |
| Ubuntu 24.04 | B++ 및 다중 언어 실행 이미지 Dockerfile |
| PostgreSQL 16 alpine | 기본 Compose, 관리형 공유 DB helper 기본값, 감사용 Compose |
| Redis 7 alpine | 기본 Compose, 관리형 공유 Redis helper 기본값, 감사용 Compose |
| PgBouncer 1.24.1-p1 | 기본 Compose의 pooler |

`WEBCOMPILER_NGINX_IMAGE`는 기존처럼 API 프록시에만 적용된다. 외부 edge까지 같은 override를 적용하도록 권한 범위를 넓히지 않았다. `WEBCOMPILER_SHARED_POSTGRES_IMAGE`와 `WEBCOMPILER_SHARED_REDIS_IMAGE` 등 기존 운영자 override도 유지했다. 따라서 이 변경은 **기본값 고정**이며 모든 외부 override의 digest 사용을 강제하는 전역 정책은 아니다.

## 기존 데이터와 변경 절차

관리형 helper는 이미지가 로컬에 없으면 실패하며 임의 pull을 하지 않는다. 필요한 digest 이미지는 승인된 준비 절차에서 미리 확보해야 한다. 이전 태그 alias가 있다는 이유만으로 정확한 digest 이미지가 준비됐다고 가정하지 않는다.

기존 PostgreSQL이나 edge의 실제 이미지가 새 기본값과 다르면 기존 거부 조건이 유지된다. Redis도 이전 태그로 만든 컨테이너의 `Config.Image`가 새 설정과 다르면 거부한다. 이 차이를 이유로 DB·Redis·edge를 자동 삭제·업그레이드·adopt하지 않는다. 운영자 override가 필요하면 실제 사용 이미지와 복구 계획을 확인한 별도 승인 절차를 따른다.

업데이트할 때는 새 index와 amd64 manifest를 조회·hash 대조하고, lock과 연결된 기본값을 함께 수정한다. 전체 빌드, 해당 이미지의 필수 명령/환경 및 실제 서비스 시작, 장애 복구 검증 후 별도 배포 승인을 받는다. pin을 고정한 채 보안 업데이트를 영구히 멈추는 것이 목적이 아니다.

## 검증 증거

### Linux Node24 실행 검증 — 2026-09-10

운영 서비스와 분리된 `/home/vulpo/webcompiler-audit-node24-jL4B1s`에서 고정 소스 아카이브 SHA-256 `2e977994d8800c918c6c904218fc3b6eb6ade82911ccf8ac272c605366ca687d`를 검증하고 실행했다. 명령은 `RUN_BOUNDED_BUILDER_INTEGRATION=1 RUN_AUDIT_NODE_RUNTIME=1 RUN_AUDIT_APPLICATION_BUILD=0 python3 -u backend/tests/test_build_builder_live.py -v`다. 실제 검사55143은 **1개 통과,467.081초,exit0**로 종료했다(Node 이미지 빌드427.1초).

- 실제 runtime Dockerfile에서 Node/Ubuntu 설치 부분과 마지막 `WORKDIR /sandbox` 이후의 COPY·chmod·사용자·ENTRYPOINT 부분을 그대로 사용했다. 중간 B++ 소스 빌드만 제외했다. 모의 Node나 별도 실행기를 사용하지 않았다.
- Node/nodejs24.21.0, npm/npx11.19.0, 동적 라이브러리 연결을 확인했다. `sandboxuser`가 실제 `run.sh`를 직접 실행하여 Hello World·표준입력 합42·한글 바이트 보존·BigInt·구문 오류·실행 오류를 검사했다. smoke RUN의 네트워크는 껐다. 이미지의 User와 Entrypoint도 확인했다.
- 전용 BuildKit은512MiB·추가 swap0·0.25CPU·256PID로 제한했다. 실제 RUN의 호스트 cgroup에서 제한 상속을 확인했다. Node 빌드900초 및 디스크 여유8GiB 중단 조건을 적용했다. 이것은 호스트 전체 디스크 quota나 전체 sandbox 격리 인증은 아니다.
- nonce 전용 이미지2개·빌더 컨테이너·캐시 volume과 임시 폴더 정리를 확인했다. 운영 서비스·데이터·이미지 태그를 변경하지 않았다. 테스트 소스 아카이브는 증거로 남겼다.

Terra 검토에서 발견한 Bash 우회 실행과 테스트용 packaging 재구성 문제를 root가 수정했다. Luna의8개 단순 fixture를 검토하고 사용했으며, root가 경계 추출·기한/디스크 중단·다른 소유자 정지 거부 회귀를 작성했다. 집중85개와8subtests/0.49초, 현재 전체 로컬 **1793통과·353skip·8subtests/73.35초**다. 별도 Windows fixture 확인은 Linux 증거에 합산하지 않는다.

단계 실행 로그는 `.deploy/node-runtime-probe-v2-stages-20260910.log`에 보존했다(SHA-256 `b3782889af35861865078bc0c02f6d9f4e41987f330dcaf00dba9f144463dc3d`). 이미지 저장 중 복사한 로그이므로 최종 export/정리 결과는 포함하지 않으며, 위 terminal 결과와 구분한다.

**이 결과는 Node Linux 호환성 증거다.** 전체 B++ 이미지 빌드·6개 언어 채점·API/worker 통합·로드밸런싱·배포/rollback·이미지 CVE/SBOM 검증은 남아 있다. 실패했던2GiB frontend 빌드를 재시도하거나 자원 한도를 늘리지 않았다. 아래 “서버 pull/실행 없음” 문구는 이전 Node 전환 시점의 이력이다.

### 최신 Node24 전환 검증

Node 공식 배포의 Windows24.21.0 ZIP을 공개 SHA-256 `158f7685b44de51f6c0df1d153526cbcd3e1bc739a8dfc607721cef75de9e541`과 대조하고 별도 `.deploy/node24-audit-20260910`에 압축 해제했다. 시스템 Node 설정은 변경하지 않았다. 프런트의 별도 복사본에서 npm11.19.0으로 새 설치를 실행했으며, DOMPurify 선택 의존성의 lock 누락을 고친 뒤 `npm ci`·51개 테스트·타입 검사·빌드가 모두 통과했다(빌드43.80초). 저장소의 기존 `node_modules`나 켜진 개발 서버는 교체하지 않았다. 설치 시0 vulnerabilities를 보고했지만 whatwg-encoding deprecation, oxide/esbuild installScripts 정책 경고와 큰 bundle 경고는 남았다. 이것을 이미지/OS 전체 취약점 검사로 해석하지 않는다.

실제 이미지 index/config의24.21.0 확인·Windows Node의 stdin/한글/BigInt/구문 오류·구성 회귀를 합친26개가14.89초에 통과했다. `TEST_NODE24_EXECUTABLE`로 opt-in하는 `test_node_lts_execution.py`의5개는 Windows Node binary 검사이며 Linux sandbox/격리 검증이 아니다. 최종 전체 로컬은 **1787통과·353skip,76.46초**다. 이전 이미지7종/1781개 기록은 전환 전 이력이다.

CI와 `.nvmrc`는24.21.0으로 고정했다. 공식 릴리스/이미지 메타데이터 검증 및 로컬 성공과 별도로, 새 Linux 실행 이미지의 실제 빌드·6개 언어 회귀·채점 경로 검증은 남아 있다. SSH 읽기 전용 확인에서 서버에 새 NodeRuntime digest가 아직 없었다. 서버 이미지 pull이나 컨테이너 변경은 하지 않았다.

### 이전 이미지 고정 검증 이력

- `backend/tests/test_image_registry_live.py`: `RUN_IMAGE_REGISTRY_INTEGRATION=1`에서 실제 registry를 digest로 조회한다. 7개 index의 원문 hash/응답 header/amd64 참조, 7개 하위 manifest의 원문 hash/header를 검사했다. 별도 바이트·헤더 변조와 입력 상한 회귀도 포함한다. 이 테스트는 config/layer 다운로드, CVE 검사 또는 컨테이너 시작 검증이 아니다.
- `backend/tests/test_image_lock_defaults.py`: Luna가 작성하고 주 에이전트가 검토한 Dockerfile/Compose/helper의 기본값 연결과 override 보존 검사 4개.
- `backend/tests/test_image_pin_reuse.py`: 주 에이전트가 작성한 이전 Redis 태그/다른 PostgreSQL 이미지의 무변경 거부와 명시적 override 보존 검사 4개. 실제 Docker 대신 명령 기록 fixture를 사용한다.
- registry 실제 검사와 기존 ownership/wiring 회귀를 합친 실행은 78개/11.59초 통과했다. 기본값/재사용 집중 검사는 8개/0.80초 통과했다. 최초 Redis 재사용 테스트 실패는 제품 거부는 맞았으나 예상 오류 문구가 틀린 테스트였으며 수정했다.

기존 live 테스트의 image-inspect 준비 조건과 fixture 실행 참조도 같은 pin으로 맞췄다. **이전 태그에서 통과한 실제 컨테이너 테스트를 새 digest의 실행 증거로 재사용하지 않는다.** 새 참조로 실제 실행하는 검증은 남아 있다.

최종 현재 소스 전체 로컬 회귀는 **1781통과·347skip,77.51초**다. registry opt-in 검사는 별도 실제 실행에서 통과했으며 기본 전체 실행의 skip을 통과로 바꿔 계산하지 않았다. Bash 배포 스크립트 문법 검사와 diff whitespace 검사도 통과했다.

## 아직 완료하지 않은 부분

기본 이미지 고정만으로 A17이나 전체 목표가 완료되지는 않는다.

- Node20 지원 종료에 따라 frontend/CI/실행 이미지 구성을 Node24.21.0 LTS로 변경했다. NodeSource 원격 설치 스크립트를 제거하고 glibc 공식 이미지에서 Node와 npm 트리를 복사한다. 위 Linux probe에서 Node 공급 부분과 실제 runtime packaging·sandboxuser 실행은 통과했다. **중간 B++ 빌드를 포함한 전체 Dockerfile과6개 언어 채점은 아직 검증하지 않았다.** Node 단독 또는 Windows 테스트로 대신하지 않는다. [Node.js 공식 릴리스 상태](https://nodejs.org/en/about/previous-releases).
- 실행 이미지의 apt 저장소와 설치 패키지 버전은 이 index lock으로 고정되지 않는다. 컴파일러/toolchain 실행 프로필, 설치 이미지·OS SBOM/CVE 검사가 남아 있다.
- 직접 만든 backend/frontend/sandbox 이미지의 최종 ID/digest, 검사된 SHA와 산출물 연결, provenance는 별도다. 현재 runtime inventory의 이미지 ID/구성 관측은 upstream 승인 정책이나 서명 검증을 대신하지 않는다.
- 변경된 기반 이미지로 전체 빌드·서비스 기동·rollout/drain/rollback을 재검증해야 한다. 격리 frontend 빌더의 2GiB 메모리 부족 문제도 아직 해결되지 않았다.

운영 이미지 pull·컨테이너 변경·데이터 변경·배포·main push는 이번 작업에서 수행하지 않았다.
