# 설치 이미지 보안 검사 (A17)

## 현재 구현과 제한

`scripts/scan_image.py`는 Trivy 0.74.0으로 Linux amd64 이미지의 OS·언어 패키지를 검사한다. 원격 검사는 registry digest, 로컬 검사는 전체 Docker image ID를 요구한다. 대회 코드나 서비스 컨테이너를 실행하는 도구가 아니다.

- 모든 심각도를 수집하고 UNKNOWN·HIGH·CRITICAL 또는 지원 종료 OS가 있으면 실패한다. 수정 버전이 없는 항목도 제외하지 않는다. LOW·MEDIUM은 보고서에 남긴다.
- 호출자의 `TRIVY_*` 설정과 저장소의 ignore/config 파일을 사용하지 않는다. 별도 작업 디렉터리와 빈 설정 파일을 쓴다. 취약점 DB는 version 2, 갱신 후 48시간 이내여야 한다.
- 이미지의 environment·build history는 결과에서 제외한다. 패키지 결과와 OS·이미지 식별 정보만 남기고 여기서 CycloneDX를 만든다. 변환 전후 모든 고유 package URL(PURL)과 버전, 최상위 이미지 ID가 일치해야 한다. 같은 PURL이 여러 경로에 설치된 경우 한 component로 합칠 수 있다. 전체 dependency graph나 스캐너가 발견하지 못한 바이너리의 완전성을 보장하는 검사는 아니다.
- application scope는 web source SHA와 backend/frontend/sandbox 역할을 이미지 label에서 확인한다. backend에는 FastAPI, sandbox에는 npm의 **실제 언어 패키지 탐지 결과**가 있어야 한다. 이 marker 검사는 모든 의존성을 찾았다는 증거가 아니다. frontend의 번들 JS는 별도의 source-lock SBOM 검사와 함께 판단한다.
- 새 출력 폴더에 sanitized report·SBOM을 쓰고 마지막에 manifest를 남긴다. manifest에는 이미지·역할·source SHA·scanner 버전/실행 파일 hash·DB 시각·결과 파일 hash·정책 판정을 기록한다. 정책 실패도 보고서를 남길 수 있으며 exit 1이다. 도구/입력 실패는 exit 2이며 성공 manifest로 처리하지 않는다.

CI의 필수 `image-security` job은 선택적인 `RUN_LONG_E2E` 조건 밖에 있다. backend/frontend/Compose 검사를 통과한 뒤, 기존 2GiB/1CPU/512PID BuildKit으로 세 실제 Dockerfile을 순서대로 빌드한다. `--iidfile`의 immutable 결과와 source/role label을 연결해 검사하고, sandbox의 별도 B++ commit도 확인한다. 세 결과가 모이면 `application-images.json`에 이미지별 manifest hash를 기록한다. 이 작업은 이미지 push·서비스 시작·배포를 수행하지 않는다.

**새 GitHub job과 전체 세 이미지의 보안 검사는 아직 실제 통과하지 않았다.** 세 실제 Dockerfile의 빌드 자체는 이후 동일한 2GiB/1CPU/512PID 한도에서 통과했다(진행표의 31244,1039.180초). 프런트 빌드 메모리 문제를 수정했으며 한도를 늘린 결과가 아니다. 후속 전체 E2E에서도 세 이미지 빌드는 완료했지만 DB 이미지 pull 중 디스크 여유 8GiB 안전선에 걸려 중단됐다. 빌드 성공·실행 검증·보안 검사를 구분한다. 현재 CI 이미지는 기본 빌드 입력 기준이다. 운영 bootstrap/test override, 실제 배포 이미지 digest와 검사 산출물의 연결, B++·복사된 Node 실행 파일 등 compiler inventory, 서명된 provenance는 추가 검증·구현이 필요하다. source-SHA label만으로 공급망 서명을 주장하지 않는다.

## 재현 명령

검증된 Trivy 실행 파일을 별도 준비하고, 사용하지 않은 출력 경로를 지정한다.

```sh
python3 scripts/scan_image.py \
  --trivy /absolute/path/to/trivy \
  --image docker.io/library/nginx@sha256:77da26c31397bf6694b4bf93275f5b40b0b120ba1b8f114264b603e592c561d6 \
  --source remote --scope base \
  --output-dir /fresh/path/nginx-report --cache-dir /private/path/trivy-cache
```

전체 CI 검사는 깨끗한 checkout, 검증된 명시적 builder ID, 정확한 commit을 요구한다. dirty/untracked 소스를 commit label 아래에 묶거나 외부 운영 이미지를 대신 검사하지 않는다.

```sh
python3 scripts/ci_image_security.py --commit "$GITHUB_SHA" \
  --trivy /absolute/path/to/trivy \
  --output-dir /fresh/path/application-image-security --cache-dir /private/path/trivy-cache
```

## 실제 검사 증거 — 2026-09-10

Trivy Windows ZIP SHA-256 `94c40e0696e4b907a74b7b2e1438d5d72ebaca83115817407f568a002d520842`와 checksums 파일 hash를 immutable GitHub release metadata와 대조했다. 실행 파일 hash는 `4c532e1f28f53282dc364671e87381cd77760fa9cafab143f576449c2207cdd5`다. Linux archive 고정값은 `2ae6fe3ee734b7fdf11335663e18c75ea12dccc76062f09f164a3b0f8be4371a`이며 CI에서 추출 전에 확인한다. cosign 서명 확인은 수행하지 않았다. [공식 릴리스](https://github.com/aquasecurity/trivy/releases/tag/v0.74.0), [Trivy image CLI](https://trivy.dev/docs/latest/references/configuration/cli/trivy_image/).

DB UpdatedAt `2026-09-10T01:14:50.595920862Z`, 원격 registry/Linux amd64 검사 결과:

| 이미지 | 설치 패키지 | 발견 항목 | 결과 |
|---|---:|---|---|
| 기존 Nginx 1.27.5 alpine, index `65645c7b…` | 68 | critical 2 / high 34 / medium 49 / low 26 | wrapper exit 1 |
| 검토 후보 Nginx 1.30.4 alpine, index `dc5069ad…` | 71 | high 7 / medium 1, libuuid 관련 | raw scanner exit 42, 미선택 |
| 선택 Nginx 1.30.4 alpine-slim, index `77da26c3…` | 21 | 0 | wrapper exit 0 |

숫자는 **패키지/권고 조합의 행 수**이며 독립적으로 악용 가능한 취약점 수가 아니다. 0건도 알려지지 않은 취약점이 없다는 뜻이 아니다. 새 slim 이미지의 필수 프록시 기능은 실제 runtime 검사로 별도 확인했다.

최신 wrapper 소스 hash `e8263cc855b25b213e08c18b0ac74cdd4d3258ee4e9ed57a9030837806cd4f92`로 기존/선택 이미지 각각 68/21개 고유 PURL의 CycloneDX 일치를 확인했다. 로컬 증거는 `.deploy/image-security/nginx-baseline-v3` 및 `nginx-slim-v3`에 있다.

| 파일 | 기존 이미지 SHA-256 | 선택 이미지 SHA-256 |
|---|---|---|
| report.json | `2a28360a86d6d12c971d45049ee1667483670ce7f34b2206ffe823a1f790dd21` | `0fc9bf8996ceaa315a130f424fd89fca340a1ccd0d2aa48b743de198fab349fd` |
| sbom.cdx.json | `2dd918884e37bff502853bea9a2bd123c6c872663498240b67f3874788973e25` | `8297249ccbfbb8343fa9288b319f528af4d0470e988f70efeaaba22c79f64515` |

### Nginx 실제 runtime 회귀

별도 `/home/vulpo/webcompiler-audit-nginx-JtT3qX`에서 source archive SHA-256 `d8673840a1226fd298d51f1528371bc52ad0d2aea28544bf64d2f8e6b0af6d21`로 `AUDIT_ROOT=<위 경로> RUN_EDGE_INTEGRATION=1 python3 -u backend/tests/test_edge_runtime_live.py -v` 실행: **2개 통과,40.989초,exit0**(7222).

실제 Nginx HUP·전환 실패 후 rollback·기존 POST 한 번 처리·blue/green WebSocket 유지·intent/commit 직후 중단 복구·master 강제 종료 후 재시작·다른 소켓 파일 보존을 확인했다. 외부 edge는 비root·read-only·cap drop·96MiB/0.25CPU/64PID, loopback 임시 포트에만 바인딩했다. 애플리케이션/API readiness는 HTTP fixture이므로 전체 앱 로드밸런싱 완료 증거가 아니다. 테스트 전용 container와 edge 폴더가 남지 않았음을 별도 SSH 조회로 확인했다. source archive와 pinned public image cache는 보존했다.

첫 archive의 `trusted_ingress.py` 누락 때문에 import가 실패했으며 실제 컨테이너 시작 전이었다. 두 번째 archive에 해당 module과 package initializer를 포함해 해결했다. 제품 프록시의 실패로 기록하지 않는다.

### 실제 Docker-source와 build IID 검증

Docker29.3/containerd store에서 public Nginx의 `docker image inspect .Id`는 index digest, 원격 Trivy의 ImageID는 config digest로 관측됐다. 같은 이미지의 **실제 Docker-source** 검사88243은14.430초/exit0으로 종료했고 Trivy ImageID가 Docker의 index ID와 일치했다. 서로 다른 source mode의 결과를 섞지 않으며 strict equality를 느슨하게 바꾸지 않았다.

이어서 source archive `7a66bbc4799a055aa7307e82dca8b9b460e454260fab7a8891ba3ac677f21364`를 별도 `/home/vulpo/webcompiler-audit-image-scan-Co9k75`에 검증·추출했다. `RUN_BOUNDED_BUILDER_INTEGRATION=1 RUN_AUDIT_IMAGE_SCAN=1 RUN_AUDIT_APPLICATION_BUILD=0 RUN_AUDIT_NODE_RUNTIME=0 TEST_TRIVY=<검증된 Linux binary> TEST_TRIVY_CACHE=<전용 cache> python3 -u backend/tests/test_build_builder_live.py -v` 실행60161은 **1개 통과,47.799초,exit0**다.

- Nginx base에 시험용 source/role/nonce label만 추가한 작은 이미지를 실제 Buildx로 만들었다. `--load --iidfile` 결과가 Docker inspect와 Docker-source Trivy ImageID에 같게 전달되는지 확인했다. 임의 tag를 다시 해석하지 않았다.
- 생성 image ID `sha256:35f9db2160267d71157b5dff843dc9bd146bf1adff16cbc52fb0ec23622a6767`, OS21개 패키지/PURL 일치, 발견0건. 같은 이미지를 backend 역할로 주장하면 exit2로 거부되고 성공 manifest가 남지 않았다.
- source SHA `cccc…`와 frontend 역할은 **fixture label**이다. 이 이미지는 실제 frontend 소스 빌드가 아니며 application build 전체 검증으로 계산하지 않는다. 일회용 보고서의 manifest는 terminal 출력에 기록했다(report hash `70ec87671154d781c2e0e9ced4e602403bcf995e4f9a27d702f74cff104d373b`, SBOM hash `584f3be88e174d48672c4a5a88e16025e5958e4a27b804ac78cbe14b67716ad7`). 임시 보고서는 fixture cleanup으로 제거했다.
- Linux scanner executable hash는 `d89bcc6510a267f11b773398cbf1be5520ce39f9e8b6633178c4487f05b7d791`이다. 검사 프로세스는 별도 user systemd unit의768MiB/추가 swap0/0.5CPU/128Tasks/600초 제한 아래 실행했다. 실행 중 systemctl 관찰과 테스트의 실제 cgroup 파일 검사로 확인했다. BuildKit은 별도512MiB/0.25CPU/256PID이며 실제 RUN의 상속도 검사했다.
- nonce builder·cache volume·테스트 이미지·임시 폴더를 정리했다. 운영 container/tag/data는 변경하지 않았다. 별도 Trivy 다운로드 DB cache도 용량 회수를 위해 지웠으며 다시 다운로드할 수 있다. scanner binary·source archive·첫 Docker-source 보고서는 보존했다.

최종 전체 로컬88185: **1848통과·353skip·8subtests/74.42초,exit0**. 집중 scanner/orchestration/CI wiring/cleanup56통과·7POSIX skip도 별도 확인했다. skip은 실제 검증으로 계산하지 않는다.

### 남은 검증

### main 병합 후속 검사 — 2026-09-10 12:39 UTC

PR #24의 CI `34477170700`에서 backend-tests, frontend-checks, compose-config는 성공했으나 image-security는 CycloneDX 버전 비교 오류로 중단됐다. Trivy 0.74.0은 Debian 패키지의 epoch를 PURL의 `epoch=1` 같은 qualifier로 분리하고, CycloneDX version에는 `1:version-release`로 포함한다. 기존 검증기는 qualifier를 버려 서로 다른 문자열로 판단했다. `scan_image.py`에서 Debian/RPM epoch를 복원하도록 수정하고, 중복·비정상 epoch와 잘못된 버전은 계속 거부한다. PURL 전체 집합·이미지 ID 대조 및 취약점 차단 정책은 유지한다. 관련 로컬 scanner/orchestration 테스트 **59개 통과**.

수정한 검증기로 현재 운영 백엔드의 불변 이미지 `sha256:1c64eae4593ff9ea3af26fd8c16599391cd022236c1fb64b408a70334f16aebf`를 **읽기 전용** 검사했다. 대상 이미지를 실행하거나 운영 데이터·컨테이너를 변경하지 않았다. 별도 systemd unit에 768MiB/추가 swap0/0.5CPU/128Tasks/600초 제한을 적용했고, 1.753초 후 종료했다.

- Trivy DB UpdatedAt: `2026-09-10T07:06:15.043595671Z`.
- Debian 13.6, 설치 패키지 131개 및 고유 PURL 131개가 변환 후 일치했다.
- 탐지 행 수: **Critical 3 / High 51 / Medium 62 / Low 58 / Unknown 5**. 정책 결과는 **실패, exit1**이다. 패키지/권고 조합의 행 수이며, 독립 취약점 수나 실제 악용 가능성을 의미하지 않는다.
- Critical 3개는 `perl-base 5.40.1-6`의 `CVE-2026-13221`, `CVE-2026-42496`, `CVE-2026-8376`이다. 보고서에서 이 항목들의 FixedVersion은 없으며 하나는 `fix_deferred`다. High/Unknown에도 배포판 수정 버전이 표시되지 않은 항목이 있다. 단순 버전 업데이트로 모두 해결된다고 단정하지 않는다.
- 서버 증거: `/home/vulpo/webcompiler-main-tests-0dfa1918/backend-scan-epoch-fixed/{report.json,sbom.cdx.json,manifest.json}`. report SHA-256 `8a76ce38f683d443913915e41ab79a47fdaede509a67ccc51607ff7637a090cf`, SBOM SHA-256 `4a1f06ef2de03cedf4328b72cf53079b109efaec4da32e86b1d1490886e0e43b`.

이 검사는 기존 운영 이미지의 **base scope** 결과로, 후속 PR의 정확한 소스 빌드나 세 역할 전체의 검증을 대신하지 않는다. PR #24는 초안으로 유지하며, 수정 후 CI의 정확한 새 이미지 검사도 별도로 실행한다. main에는 #22와 #23이 병합됐지만 새 자동 배포 성공은 아직 없다. 기존 운영 버전 `44b2af4c`를 유지한다.

보안 정책을 낮추거나 탐지 항목을 임의 예외 처리하지 않았다. 기반 이미지·의존성 교체는 현재 기본 자동 배포의 고정 계약 범위를 넘으므로 별도 변경 계획과 실제 런타임 회귀·수동 전환 검증이 필요하다. 수정 미제공 항목의 처리 방침도 확인해야 한다.

### 기존 감사의 남은 검증 범위

전체 세 app image의 실제 보안 검사, GitHub 필수 job 실제 실행, compiler inventory·빌드 override·운영 artifact 연결은 아직 남아 있다. 실제 빌드와 기본 스택의 6언어·일반/대회 채점 HTTP 흐름은 별도 통과 증거가 있으며 보안 검사 통과로 계산하지 않는다. 혼합 부하, 완전한 rollout/rollback, 대회 브라우저 E2E, 운영 메일·백업·보존 정책 등 본래 목표의 남은 조건도 유지한다.
