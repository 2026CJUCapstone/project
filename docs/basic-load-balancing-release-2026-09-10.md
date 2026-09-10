# 기본 로드밸런싱 배포 결과 — 2026-09-10

사용자가 전체 감사 대신 기본2-API 로드밸런싱·동작 확인·배포까지만 요청하여 범위를 축소했다. 이 완료는 A01–A25 전체 또는 상업용 운영 검증 완료가 아니다.

## 실행 구성

- 공개 주소: https://cuha.cju.ac.kr/webcompiler/
- 서버 소스 커밋: `eef08f2486926bbf5eb1017886d0b88634eddb45`. 별도 서버 로컬 Git snapshot으로 수동 배포했다. main push/GitHub CI 배포는 하지 않았다.
- 서버 작업·복구 경로: `/home/vulpo/webcompiler-basic-lb-EIXszgyU`. `operator-state.json`에는 비밀이 포함되므로600권한으로 보관하며 공개하지 않는다.
- Compose project `webcompiler-basic-eixszgyu`: base → lb → `scripts/basic-lb.compose.yml` → `scripts/basic-lb.production.compose.yml`.
- API2개, 별도 worker, PgBouncer, Redis, API proxy, frontend 모두 healthy. API는 비공개이며 proxy `127.0.0.1:18003`, frontend `127.0.0.1:15176`을 기존 edge 뒤에 연결했다.
- 기존 `webcompiler-postgres`/`webcompiler-postgres-data`를 유지한다. 두 API/worker가 같은 DB와 Redis DB1/production namespace를 사용한다. DNS least-connections proxy이며, 관리형 blue/green lifecycle/controller는 이번 경로에서 사용하지 않았다.
- 기존 host TLS Nginx의 X-Real-IP/proto를 loopback edge에서 정규화하고 새 proxy가 단일 client address를 API로 전달한다. 테스트 upstream 주소 헤더는 공개 전에 제거했다.
- runtime instance: `f487d118987f435cac1c7594d2fe3bdf`.

| 역할 | 실제 이미지 ID |
|---|---|
| backend/worker | `sha256:af93641b6c4fbdc829cb8b0fb113869d146f6743b6ebc24c0726fd1442d7901f` |
| frontend | `sha256:8fb6313bdc25b5cd3aef187871370cfc3f2b835f34b760bfafb78d754332a5d5` |
| sandbox | `sha256:5d1590bc099feeb72017ebf22a6721add973b269922027f3fd980414a669625a` |

## 실제 통과한 검증

1. 운영 백업을 격리 PostgreSQL에 복원했다. 계정9, 문제26, 일반 제출24, 대회2, 대회 제출12; legacy pending0. 원본9개 테이블의 기존 컬럼 전체를 행 정렬/hash로 대조했다. 이전 이미지 ORM도 migration된 복사본을 조회했다.
2. 격리 복사본에서 서로 다른 API peer2개, 동일 로그인 양쪽 처리,6언어 출력42, 일반 최초20점/중복0점, 대회 동일 접수ID 재시도/정답500점/순위1/종료 후 일반17점/비공개 문제 및 숨긴 테스트 접근 조건을 검증했다. API1개 중지 후 인증 요청12개와 새 Python 작업 성공, 재시작 후2개 peer 복귀도 확인했다.
3. 운영 HTTPS에서 최종 SHA, 관리자 로그인, 문제·대회 목록 조회, **익명**6언어 실행42를 확인했다. 실제 Secure owner cookie와 접수ID polling을 사용했다.
4. 운영 API1개를 중지하고 공개 health8회와 새 익명 Python 실행을 확인했다. 재시작 후 API2개와 worker가 모두 healthy로 복귀했다. 공개 환경에 예시 사용자·문제·대회를 새로 만들지는 않았다.
5. 브라우저 공개 홈에서 React 렌더링과 승인된 문구, 콘테스트 목록의 기존2개 대회 카드(진행 중1/종료1)와 상세 링크를 확인했다. 전체 관리자·풀이 브라우저 조작/모바일 검증은 이번 범위가 아니다.
6. 최종 로컬 회귀40passed/4외부조건skip: 보관, housekeeping, basic profile, proxy, contests. skip은 통과가 아니다. backend/frontend 실제 Linux 빌드는2GiB/1CPU/512PID BuildKit으로 완료했다. 전체 image security/GitHub CI/provenance는 미검증이다.

## 전환 중 수정·복구

- HTTP loopback의 익명 polling404: production Secure cookie가 HTTP에서 재전송되지 않은 검증 조건 오류였다. 실제 작업은 completed. 로컬은 인증 header로, 익명은 공개 HTTPS로 재검증했다.
- worker health probe는 실제6.304초여서3초 timeout을 초과했다. timeout10초/interval15초로 조정하고 healthy를 확인했다.
- 새 housekeeping의7일 익명 TTL이 기존 익명 제출1개를 삭제했다. worker를 멈추고 최종 backup에서 **그1개만** 복원했다. 운영 DB 전체를 덮지 않았다. 원본9개 테이블 fingerprint가 다시 일치했다. 익명 TTL의 명시적0을 비활성화로 처리하고 basic profile에서0으로 설정했다. 회귀 및 실제 retention pass 재실행 후에도 원본이 유지됐다. 향후 삭제 정책 승인을 대신하지 않는다.
- 수정 release에 이전 runtime ID를 재사용하여 시작이 거부됐다. 새 ID로 재기동했다. 이 동안503 점검 응답을 유지했고, 검증 후에만 공개 route를 전환했다.

## 보존 및 미완료

- 이전 blue/green API는 중지하여 보존했다. legacy worker는 API 내장형이며 별도 worker가 없었다. 기존 frontend/PostgreSQL/이미지를 삭제하지 않았다.
- `production-cutover.dump`, `preflight-production.dump`, 원래 edge 설정/정확 container ID는 위 서버 경로에600권한으로 보관한다. 별도 DB로 실제 backup restore를 수행했다. 폐기 시점은 아직 정하지 않았다. 테스트 복원 PostgreSQL은 중지 상태다.
- 백업/이전 이미지/읽기 호환성은 확보했지만 **최종 운영 버전의 전체 rollback/drain 전환은 미검증**이다. 새 쓰기가 생긴 DB에 과거 백업을 덮지 않는다. 복구는 신규 제출 차단→worker/queue drain→정확 원본 route/API 및 데이터 호환성 확인 순서가 필요하다.
- 기존 `.deploy/active-color`가 이 basic pool을 관리하지 않는다. 향후 배포 시 새 포트와 상태 파일을 먼저 확인하고 예전 deploy script를 무심코 재실행하지 않는다.
- 이번 전용 BuildKit container/독점 cache만 제거했으며 실행 이미지/복구 자료는 보존했다. 최종 여유11618MiB. 다른 프로젝트나 전역 cache는 정리하지 않았다.
- 단일 물리 서버이므로 호스트 장애/DB·Redis HA는 미해결이다. 대규모 봇·혼합부하·장애복구·전체 보안·SMTP/외부설정·알림/backup RPO-RTO·최종 관리형 LB 목표는 기존 감사 문서의 미완료로 남긴다.
