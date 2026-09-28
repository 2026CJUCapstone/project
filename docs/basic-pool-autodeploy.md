# Basic 2-API 자동 배포

`deploy_server.sh`는 배포 lock/정확한 SHA/깨끗한 tracked checkout을 먼저 확인한다. 서버 `.deploy/basic-pool.json`이 있으면 샌드박스와 데이터 계층을 그대로 유지하는 `basic_pool_application_release.py`로 진입하며 관리형 blue/green 배포로 넘어가지 않는다. 이 경로는 현재 운영 SHA가 새 SHA의 조상인지 확인하고, 스키마·의존성·Compose·Nginx·런타임 계약이 바뀌면 자동 배포를 중단한다. config가 없을 때만 기존 관리형 경로를 사용한다.

현재 운영 선택 파일(version1)은 다음 비밀 없는 구조다. 운영 데이터와 비밀이 들어 있는 `operator-state.json`은 기존 pool 안에 유지한다.

```json
{
  "version": 1,
  "pool_root": "/home/vulpo/webcompiler-basic-lb-EIXszgyU",
  "project": "webcompiler-basic-eixszgyu",
  "postgres": "webcompiler-postgres",
  "backend_port": 18003,
  "frontend_port": 15176
}
```

## 자동 실행 순서

1. main의 정확한 commit이 CI에 통과했는지 확인한다. fork PR/다른 branch/실패 CI는 SSH 전에 거절한다. SSH는 사전에 신뢰한 해당 host:port 키를 고정한다.
2. 같은 commit을 checkout한 GitHub runner에서 Node24/npm ci로 `/webcompiler/` 프런트를 빌드한다. package helper가 정확한 SHA marker를 넣는다.
3. 단일 SSH stdin으로 gzip bundle을 전달한다. 기존 remote deploy lock을 잡은 다음 임시0600 파일에 수신하고 digest를 확인한다. 같은 lock을 fetch→checkout→image build→전환까지 유지한다.
4. 원격 Git archive만 source로 사용한다. 현재 운영 SHA가 새 SHA의 조상인지 확인하고 이전 release와 schema/bootstrap/dependency lock/Dockerfile/nginx/Compose/runtime 계약을 비교한다. 기존 Windows archive의 알려진 UTF-8 텍스트 파일은 CRLF/LF 차이만 정규화하며 그 밖의 bytes/파일 추가·삭제는 보존한다. 새 shell은 실제 LF여야 한다. 변경된 계약이나 삭제된 backend module은 자동 overlay를 거절한다. 승인된 migration/clean image 준비 후 별도 절차가 필요하다.
5. 정확한 기존 dependency image 위에 앱과 새 프런트만 COPY하고, 운영 중인 샌드박스 이미지는 그대로 재사용한다. Docker context는 역할별 허용 파일만 복사한 별도 디렉터리이며 비밀을 포함한 journal/DB dump는 전송하지 않는다. CPU1/2GiB/no network/no pull 빌드이며 3GiB 가용공간이 필요하다. 이것은 clean dependency build나 새 이미지 SBOM attestation이 아니다.
6. 비공개 runtime-secrets 파일에서 완전한 SMTP 설정을 읽고 후보 이미지로 STARTTLS 인증과 NOOP을 수행한다. 실패하면 서비스 전환 전에 중단한다. 그 뒤 edge 일시503 → 신규 접수 차단 → 접수 작업 drain → DB dump/목록 검증 → API2개·worker·frontend만 교체한다. PostgreSQL/Redis/PgBouncer/proxy 컨테이너를 재생성하지 않는다.
7. health/release SHA/관리자 인증6언어 실제 실행/보호 데이터 fingerprint/기존 stateful IDs를 검사한 후 공개한다. 실패 시 이전 이미지와 새 runtime incarnation으로 rollback하며 DB dump를 덮어쓰지 않는다.

## 복구와 한계

`.deploy/basic-pool-pending.json`은 private release journal 경로를 가리킨다. journal은0600이며 자격증명을 포함하므로 출력·Git 업로드하지 않는다. `deployed`/`rolled-back`이 아닌 중단 상태에서는 다음 자동 배포를 막는다. 관리자가 해당 journal·실제 컨테이너·lock/edge 상태를 확인하고 복구해야 한다. 무조건 marker 삭제나 DB restore로 해결하지 않는다. 이전 이미지·dump를 자동 prune하지 않는다.

현재 topology에서 동일한 코드/설정 계약의 업데이트를 자동화한다. DB migration·dependency/컴파일러 toolchain 갱신·topology 변경·다중 호스트 HA를 자동화했다고 주장하지 않는다. 동시 사용자 데이터 변경 때문에 fingerprint 검사가 실패하면 데이터 삭제 없이 rollback하고 원인을 확인한다.

## 승인된 B++ 그래프 출력 런타임 교체

일반 배포는 여전히 모든 runtime 변경을 거부한다. 예외는 운영자가 이번 출력 전용
패치를 명시적으로 승인하고, 별도로 빌드한 불변 이미지와 정확한 이전/후속 SHA를
`.deploy/basic-pool-runtime-approval.json`에 기록한 경우뿐이다. 파일은 운영자 소유
일반 파일이며 권한 0600이어야 한다. 이 파일은 비공개 운영 기록이며 Git에 넣지 않는다.

허용 필드는 `version: 1`, `previous_sha`, `candidate_sha`, `previous_image`,
`candidate_image`, `runtime_digest`뿐이다. 이미지 값은 tag가 아닌 전체 `sha256:` ID다.
digest는 `python3 scripts/basic_pool_runtime_release.py digest SOURCE_ROOT`로 계산한다.
Dockerfile의 `io.bpp.runtime_source_digest` label, compiler ref/repo/build policy도
확인한다. label은 운영자가 수행한 빌드 기록을 묶는 값이지 별도 서명된 provenance가
아니다. 정확한 committed archive, 빌드 로그, 검증 결과를 함께 보존한다.

허용 변경은 runtime Dockerfile, 두 exploration 패치 파일, exploration 검증기 네 개뿐이다.
launcher, compiler ref, 나머지 runtime 파일, 스키마, 의존성, 보안 설정, topology는
기존과 동일해야 한다. 파일 삭제도 거부한다. 이전 배포에 소비된 승인은 이후 변경에
재사용되지 않는다. 잘못된 승인/이미지/계약은 점검 화면에 진입하기 전에 중단된다.

1. 운영자 승인 후 충분한 디스크 여유와 별도 named BuildKit의 CPU·메모리·PID 상한을
   확인하고 정확한 Git archive에서 후보 이미지만 빌드한다. stable tag는 바꾸지 않는다.
2. 기존 native compiler gate와 새 O0/O1 exploration gate를 후보 이미지에서 통과시킨다.
3. 승인 파일을 기록한 후 CI에 통과한 main SHA의 배포 workflow를 실행한다.
4. 배포는 위 검증기를 네트워크 없는 제한 컨테이너에서 다시 실행한 뒤, 기존
   접수 차단·drain·DB 백업·fingerprint 절차로 API/worker/frontend와 SANDBOX_IMAGE를
   함께 전환한다. DB와 큐의 컨테이너는 교체하지 않는다.
5. 이전 env에 기존 불변 sandbox ID를 보존하므로 검증된 rollback은 이전 런타임도
   복구한다. 후보 시작 후 데이터 무결성이 확인되지 않은 실패는 기존 정책대로
   점검 상태를 유지하고 수동 검토한다. DB dump를 운영 데이터 위에 덮어쓰지 않는다.

서버의 자동 sandbox updater는 이 승인 경로를 대신하지 않는다. 별도 빌드 환경·용량이
충족되지 않으면 런타임 배포 완료로 기록하지 않는다.
