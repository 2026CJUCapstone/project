# 격리 PostgreSQL 제출·대회·재채점 검증

## 2026-09-27 실제 API `/ready`와 강제 종료 감지 시간

[최신 격리 실행](evidence/isolated-postgres-managed-r4-2026-09-27.json)은 **1 PASS/40.81초**다. 실제 Uvicorn API와 두 `app.worker.serve()` 프로세스가 전용 PostgreSQL/Redis Unix socket을 사용했다. `/ready`는 워커 시작 전 503, 준비 상태 게시 후 200이었다. 첫 워커를 SIGKILL한 **직후에도 200**을 반환했다. 재등록 없이 기다리자 기존 heartbeat가 만료된 뒤 503으로 바뀌었고, 새 워커가 작업을 회수·완료하면 다시 200, SIGTERM으로 정상 종료하면 503이 됐다. 검사는 코드의 30초 유효 기간에 5초를 더한 시한 안에 만료 전환을 요구한다. 즉 강제 종료를 즉시 감지한다는 주장은 틀리고, 현재 설계의 감지 지연은 heartbeat에 의해 제한된다. 이 간격 동안에도 큐에 이미 저장된 작업은 새 워커가 복구했지만, API가 실행 가능하다고 표시하는 지연은 로드밸런싱 운영 검토 대상으로 남긴다.

직전 [API 경계 첫 실행](evidence/isolated-postgres-managed-r3-2026-09-27.json)은 **1 PASS/10.95초**로 즉시 200과 재시작/종료 전환을 확인했으나 만료까지 기다리지는 않았다. 두 실행 모두 Docker health/실행 lane은 합성이고, 실제 공개 프록시나 Docker 채점 수락이 아니다. 세 격리 컨테이너와 `audit_*` 스키마·임시 파일은 각 실행 후 제거했다.

- [r3 JSON](evidence/isolated-postgres-managed-r3-2026-09-27.json) SHA-256 `f302a036c93bde224a0d128ab3040feda68db6b55edd5b6fbb62fa824f8bd24b`; [XML](evidence/isolated-postgres-managed-r3-2026-09-27.xml) `26efb9482c54c54c669fc3743183ec5f2a2f1f782a2f23d2546613808986ba8b`
- [r4 JSON](evidence/isolated-postgres-managed-r4-2026-09-27.json) SHA-256 `97deef1cf1721efc7459118cc08d58dc7d07ef2dc175499f45bae4c22e1a6651`; [XML](evidence/isolated-postgres-managed-r4-2026-09-27.xml) `e0ddd1907be49da3e014d92aa403c3565dbef57aa2dc710567d86a1014113730`
- r4 소스 묶음 SHA-256 `26eeaaf99f71e3ddada92766443eccac2e7c82da4607e099de1f176cae02808a`; 실행 도구 SHA-256 `de07bc2ce13037244d9ae4183ff00ab79ac584eff36e711bbe41e883ece2e0b6`

## 2026-09-27 관리형 워커 후속 — 실제 PG·Redis, 합성 실행 lane

[최종 원시 결과](evidence/isolated-postgres-managed-r2-2026-09-27.json): **1 PASS/7.57초**, 동일 파일의 SQLite 변형 1개는 제외됐다. 서로 다른 두 OS 프로세스가 실제 `app.worker.serve()`를 production 설정으로 실행했다. 첫 프로세스는 PostgreSQL 작업을 claim하고 Redis 준비 상태를 게시한 뒤 SIGKILL됐다. 다음 프로세스는 같은 전용 스키마/Redis socket에서 새 `WorkerProcessRecord` epoch와 Redis 소유권을 얻고 만료된 작업을 회수해 한 번 완료했다. 이전 토큰의 완료는 거절됐다. 새 프로세스의 SIGTERM 종료 뒤 DB drain/stop 시각과 Redis 준비 상태 해제도 확인했다.

이 검사는 `app.worker`의 등록·lifecycle·signal 경로와 진짜 PostgreSQL/Redis를 사용한다. Docker 권한을 주지 않기 위해 `build_worker`와 `health_loop`만 시험용 실행 lane/health 함수로 바꿨다. 따라서 실제 Docker 실행기, 정상 Docker health probe, API/프록시 failover의 증거는 아니다. SIGKILL 직후 Redis TTL 동안 API가 보는 상태는 위 r3/r4 후속 검사에서 확인했다.

서버에 있던 Redis 이미지 `sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf`를 전용 세 번째 컨테이너로 사용했다. PG/Redis/클라이언트 모두 네트워크와 공개 포트가 없고 Unix socket으로만 연결했다. Redis는 읽기 전용 루트, 비루트, 권한 상승 금지, 128MiB/0.5 CPU/48 PID, 32MiB tmpfs였다. 클라이언트에 Docker socket이 없고 운영 DB/Redis URL·비밀을 쓰지 않았다. 첫 실행은 테스트 스키마의 `schema_migrations` 준비 누락으로 1 FAIL이었다. [첫 실패 기록](evidence/isolated-postgres-managed-r1-2026-09-27.json)을 남기고 준비 코드를 고친 뒤 통과했다. 두 실행 모두 컨테이너·`audit_*` 스키마·임시 경로 잔여가 없었다.

- 첫 실패 JSON SHA-256: `c366fcf6267c6cc7cc99762f7ace990dcbdbcca348790eea877e55c2918ee187`
- [최종 JSON](evidence/isolated-postgres-managed-r2-2026-09-27.json) SHA-256: `372eb17e528e45eb3ae9f283022ff58c765a9b1797104180a5088ea1f77c5174`; [XML](evidence/isolated-postgres-managed-r2-2026-09-27.xml) SHA-256: `c5647abcbbb22d13a7b757a74fb2ff2c716205adb1835d6590dee74dd8f99f49`
- 실행 소스 묶음 SHA-256: `b4ad5156a59d89ecbb621380609e1f03d89f32cdbbdea7066ead0985b2554479`; 실행 도구 SHA-256: `de07bc2ce13037244d9ae4183ff00ab79ac584eff36e711bbe41e883ece2e0b6`

2026-09-27 KST. 전체 신입생 콘테스트 Goal의 부분 증거이며 운영 배포나 운영 데이터 검사가 아니다.

후속 프로세스 복구 검사: [첫 프로세스 검사 JSON](evidence/isolated-postgres-r3-2026-09-27.json)에서 29 PASS/39.91초였다. 이때 첫 claimant는 별도 프로세스였고 SIGKILL을 받았지만, 회수는 pytest 프로세스가 했다. 검사를 보강한 [두 프로세스 검사 JSON](evidence/isolated-postgres-r4-2026-09-27.json)에서는 **1 PASS/5.84초**였다. 첫 자식이 PostgreSQL에 claim을 commit한 뒤 SIGKILL로 종료됐다. 두 번째 새 자식이 같은 작업을 정확한 lease 경계에서 회수해 토큰을 교체하고 한 번만 완료했다. 옛 토큰과 중복 완료는 거절됐고, 제출 행·시도 횟수·소유자별 조회를 확인했다. r4는 변경된 검사만 재실행했다. `app.worker` 자체나 Docker 실행기를 강제 종료한 검사는 아니므로 아래 별도 수락 항목으로 유지한다.

추가 [ExecutionWorker 프로세스 검사](evidence/isolated-postgres-r6-2026-09-27.json)는 **1 PASS/6.90초**다. 첫 별도 프로세스가 실제 `ExecutionWorker.run_once()`로 작업을 claim하고 시작 가드를 통과한 뒤 SIGKILL을 받았다. 새 프로세스의 `ExecutionWorker.run_once()`가 기존 작업을 회수해 합성 실행 결과를 저장했다. PostgreSQL에 동일 작업 한 행, 두 번의 시도, 새 worker ID가 남았으며 첫 worker 토큰으로 결과를 덮어쓸 수 없었다. 이 검사는 `app.worker.serve()`·`WorkerProcessRecord` epoch·Redis 준비 상태·Docker sandbox를 사용하지 않는다. 실행 코드의 반환값은 합성 runner가 만들었다.

## 결과

- 실제 PostgreSQL 16.13: **28 PASS, 16 deselected, 37.63초**. 제외된 16개는 같은 파일의 SQLite 변형이다. PostgreSQL 검사는 건너뛴 항목이 없다.
- 로컬 관련 회귀: **92 PASS, 12 SKIP, 65.69초**. 로컬에는 명시적인 PostgreSQL 접속 대상이 없으므로 새 PG 전용 12개를 건너뛰었고, 위 격리 실행에서 동일한 12개를 실제 검증했다. 두 결과를 합산해 서로 다른 검사 수라고 주장하지 않는다.
- 첫 격리 실행 **19 PASS / 9 FAIL**도 보존한다. 임시 DB 생성기의 `--no-locale`만 지정하여 SQL_ASCII가 된 문제가 8개 검사에서 한국어 저장을 막았다. `--encoding=UTF8`과 실행 전 확인을 추가했다. 나머지 하나는 테스트 데이터가 원본 문제를 저장하기 전에 FK 연결을 생성한 문제였고, 부모 레코드를 먼저 저장하도록 수정했다. 제품 제약조건이나 검증을 완화하지 않았다.

## 이번에 확인한 범위

| 대상 | 실제 확인 | 남은 경계 |
| --- | --- | --- |
| 제출 큐 | 독립 DB 연결의 중복 접수, 전역 동시 실행 제한, 임대 갱신·만료, 오래된 작업자의 완료 거절, 결과·점수 트랜잭션 | 실행기는 합성 결과를 사용함. 실제 채점 프로세스 강제 종료·재시작은 미검증 |
| 프로세스 종료 | 별도 Python 프로세스가 claim을 commit하고 SIGKILL로 종료된 뒤, 새 자식 프로세스가 회수·완료. 행 한 개, 두 번의 시도, 새 토큰, 이전 토큰 거부 | 테스트의 자식은 큐 API만 사용하며 sandbox를 생성하지 않음. 바인딩된 daemon claim, `app.worker`, Redis, 실제 채점 코드는 미검증 |
| ExecutionWorker 복구 | 실제 `ExecutionWorker.run_once()`를 별도 두 프로세스에서 실행해 첫 프로세스 강제 종료 후 새 프로세스가 작업을 한 번만 완료 | runner와 sandbox pool은 합성; `app.worker` 서비스·Redis·Docker 환경을 포함한 운영 경로는 미검증 |
| 콘테스트 | 마감 직전 접수와 지연 채점, 첫 정답·오답 패널티·공동 순위, 중복 득점 방지, 일반 풀이와 대회 득점 경쟁, 종료 작업 반복 | 시간은 통제된 테스트 시계. HTTP 검사는 ASGI 내부 요청이며 공개 프록시 경로가 아님 |
| 재채점 | 두 연결의 동시 반영 한 번만 적용, 반영 중 실패 전체 롤백, 동시 검수 요청 멱등성, 반려와 반영의 직렬화 | 합성 출처·실측 승인 자료를 사용. 실제 출제 검수 승인으로 사용할 수 없음 |
| DB 변경 | 구 제출 큐 보존, 출제·재채점 감사 기록 보존, 과거 NULL 검수 근거 유지, 반복 초기화 | 모든 이전 스키마 조합과 대용량 DB 전체 검증은 아님 |

`test_contests.env`는 기본 SQLite 동작을 유지한다. 새 `test_contest_postgres.py`만 명시적인 간접 fixture 선택으로 PostgreSQL을 사용한다. 기존 행동 검사를 재사용하므로 PG용으로 기대 결과를 낮추지 않는다. 각 검사는 무작위 전용 스키마를 만들고 해당 스키마만 제거한다. 종료 시 남은 `audit_*` 스키마는 없었다.

## 격리와 자원

아래 기존 PostgreSQL/큐 검사에는 서버에 이미 있던 두 이미지만 사용했다. 위 관리형 워커 후속에는 앞서 적은 Redis 이미지를 추가했다. 이미지 다운로드·빌드·시스템 설치 없음.

- DB: `sha256:20edbde7749f822887a1a022ad526fde0a47d6b2be9a8364433605cf65099416`
- 테스트 Python: `sha256:d7ab3494aad02142fe7fc4abee8175283a2ce68e57cfc7bb24da034753065930`

두 컨테이너 모두 네트워크 없음, 포트 공개 없음, 읽기 전용 루트, 비루트 계정, 모든 capability 제거, 권한 상승 금지. 각 512MiB/추가 swap 없음/0.5 CPU/48 PID. DB 데이터는 256MiB tmpfs로 이미지의 기본 데이터 볼륨 경로를 덮어써 익명 데이터 볼륨을 만들지 않는다. 연결은 전용 임시 경로의 Unix socket만 사용한다. 테스트 컨테이너에는 Docker socket을 주지 않았으며 소스와 DB socket 경로는 읽기 전용이다. 테스트 최대 실행 시간은 300초다.

운영 비밀 파일·DB·Redis·큐·점수판과 연결하지 않았다. 운영 대회 등록·배포·Git push 없음. 각 격리 실행에서 컨테이너가 제거됐고, 결과 복사/해시 대조 후 임시 경로도 제거했다. 이 격리는 신뢰한 테스트 코드용이며 별도 Docker daemon이나 별도 물리 서버를 사용했다는 뜻은 아니다.

## 원시 증거

- [첫 실패 JSON](evidence/isolated-postgres-r1-2026-09-27.json): SHA-256 `f75847e37329f82eb4757921db7ee10a2fdf1bc3c023af554d289da6ccacdb1a`
- [최종 JSON](evidence/isolated-postgres-r2-2026-09-27.json): SHA-256 `f83917cca358c6fd4a744946801a3ea83cf4161e8323cbbdd2f3e3725ab79af1`
- [개별 검사 XML](evidence/isolated-postgres-r2-2026-09-27.xml): SHA-256 `c47d70c335126f4eb0dadbc9bc13cd2703badbb3d3ff0da39224e4b6c70ee2c0`
- [첫 프로세스 검사 JSON](evidence/isolated-postgres-r3-2026-09-27.json): SHA-256 `b0bd9be7a234be4b2d52f69a0a242f6513c81138ee6e1efcf970de56e2f2b9f7`; [XML](evidence/isolated-postgres-r3-2026-09-27.xml): `e8e11a2232e5e871b277eb8fa87155d0cfa5b4fba1938e8d671f55768f27f2fe`
- [두 프로세스 검사 JSON](evidence/isolated-postgres-r4-2026-09-27.json): SHA-256 `b8ef898d6b3bc29647f7c7cd4aefe5eb367a0dea7844e1847872da70ab7ec9af`; [XML](evidence/isolated-postgres-r4-2026-09-27.xml): `cced1f064bfa397880475ecca7c09e285f246257802d598c0db59a3887bebcdd`
- [ExecutionWorker 첫 검사 JSON](evidence/isolated-postgres-r5-2026-09-27.json): SHA-256 `bc9954d3d27286a7c7b123f20c46332ca48883a5da9899b9a8f0242bae499a6a`; [XML](evidence/isolated-postgres-r5-2026-09-27.xml): `58b9634059a865e28bf5960b20ddbbcc704227eb2bc5ca49b5375298e83aacf9`
- [ExecutionWorker 최종 JSON](evidence/isolated-postgres-r6-2026-09-27.json): SHA-256 `81b104035d6362d3fe87532c450483214c5c2c5d619482251dcf6cc5e5de7fc7`; [XML](evidence/isolated-postgres-r6-2026-09-27.xml): `c7faa778affee1cddd8d89ee9660eec37590de31e9434aefc0ea5b6fa58deedf`
- 최종 소스 묶음: `3b62a5209a327957533884229fb9b5f43b8c6552b99375806bb222884fa0f92c`. JSON의 `sourceFiles`에 실제 파일별 SHA-256을 포함한다.
- 실행 도구: `scripts/run_isolated_postgres_tests.py`, SHA-256 `e87989d3fab9addc5244b7f5358ac2310913ed5112b60df1612286a09e003128`.
- r4 소스 묶음 SHA-256 `229dd72b40328a12086af0c848da3774ed36f3596b84c8060f5a4b8c4648132c`; 도구 SHA-256 `ed2c05326424ad08f8634a56e87286f15ab751706e2e8776488397c2bd4e4de3`.
- r6 소스 묶음 SHA-256 `0097e98ff3fa565f4237be76af8e4699274938a3fead35a66395a2c9cf62ad9e`; 도구 SHA-256 `d942fee264d95660d34f87b90114cde0748c3285cc0f7d1f0e4ca220cfd48fb1`.

## 다음 검증

실제 `app.worker`의 Docker health/실행 lane과 Redis·HTTP 프록시를 잇는 장애 복구 검증, 강제 종료 감지 지연의 운영 수용 기준, 최종 설치 B++ 런타임 수락, 전체 출제 데이터와 여섯 언어 반복 측정, 과거 해결 출처 처리·큰 대회 처리·호스트 자원 예산 검증은 별도로 남아 있다. 출처 이용 조건·난이도·일정·J 배점·AI 관련 운영 정책·종료 후 공개 결정도 이 테스트 결과로 대신 승인하지 않는다. 전체 V01–V20/C01–C12 완료 선언은 하지 않는다.
