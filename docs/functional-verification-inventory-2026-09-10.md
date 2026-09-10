# 기능 검증 인벤토리 — 2026-09-10

이 문서는 현재 제품의 백엔드 라우트와 프론트엔드 화면/기능을 실제 검증할 때의
범위, 후보 테스트 위치, 외부 의존성과 상태 변경을 정리한 **검증 재고**다. 실행
결과 보고서가 아니며, 아래에 테스트 파일이 있다는 사실만으로 PASS를 주장하지
않는다. PASS는 실제 실행 명령, 환경, 로그와 함께 별도로 기록해야 한다.

## 검증 방식과 표기

| 표기 | 의미 | 자격증명·변경 조건 |
| --- | --- | --- |
| U | 순수 단위·정적·mock 검증 | 외부 자격증명 불필요. 외부 시스템과 영속 데이터 변경 없음 |
| L | 격리된 로컬 ASGI/DB 통합 검증 | 임시 SQLite/Redis와 fixture 계정·토큰을 사용한다. fixture 내부의 회원·문제·제출·프로젝트 등은 변경될 수 있지만 운영 데이터는 건드리지 않는다 |
| E | 실제 다중 서비스/브라우저 검증 | 실제 API 2개, Postgres, Redis, worker/sandbox, 브라우저 또는 실제 이미지가 필요하다. 테스트 계정과 데이터가 변경된다 |
| M | 메일 전달 검증 | SMTP sandbox/자격증명과 실제 수신함 또는 mail sink가 필요하다. 단순 mock 발송은 메일 전달 증거가 아니다 |
| P | 운영 배포·장애·복구 검증 | 명시적인 운영 권한, 백업/복구 계획, 배포·중지·rollback 변경 승인이 필요하다 |

기존 테스트 경로는 “어디서 계약을 확인할 수 있는가”를 가리키는 후보일 뿐이다.
파일 존재나 정적 assertion은 실제 외부 서비스, 브라우저 동작, 메일 수신 또는
운영 데이터 보존을 대신하지 않는다.

## 백엔드 라우트 인벤토리

라우터 prefix는 `backend/app/main.py`의 실제 등록을 기준으로 적었다.

| 기능·라우트 | 확인할 계약/시나리오 | 후보 테스트 위치 (실행 필요) | 검증 방식·변경/외부 조건 |
| --- | --- | --- | --- |
| 상태·준비 `/health`, `/ready` | liveness와 readiness 분리, schema/Redis/worker 의존성, 안전한 503/no-store, drain 시 readiness 철회 | [`test_runtime_readiness.py`](../backend/tests/test_runtime_readiness.py), [`test_readiness_live.py`](../backend/tests/test_readiness_live.py), [`test_embedded_readiness.py`](../backend/tests/test_embedded_readiness.py), [`test_ready_proxy_live.py`](../backend/tests/test_ready_proxy_live.py) | U/L로 실패 폐쇄 계약을 확인하고, E에서 실제 의존성·두 API의 응답을 확인한다. 데이터 변경은 없지만 실제 Redis/Postgres/worker가 필요할 수 있다 |
| 계정 생성·로그인 `/api/v1/auth/register`, `/login` | username/email/nickname 중복, 비밀번호 해시, username·email·nickname 로그인, canonical token 응답, rate limit, 세션 버전 | [`test_product_features.py`](../backend/tests/test_product_features.py), [`test_auth_session_version.py`](../backend/tests/test_auth_session_version.py), [`test_jwt_compatibility.py`](../backend/tests/test_jwt_compatibility.py), [`test_admission_rate_limits.py`](../backend/tests/test_admission_rate_limits.py), [`Header.auth.test.tsx`](../frontend/src/app/components/Header.auth.test.tsx) | L에서는 fixture 회원을 생성·변경한다. E에는 disposable 일반 사용자와 필요 시 admin 자격증명이 필요하며 회원/세션 행이 생성된다 |
| 현재 사용자·프로필 `/api/v1/auth/me`, `/profile` GET/PATCH | 인증된 사용자 식별, rating/proficiency 표시, email/nickname/avatar 변경과 중복 보호, 다른 계정으로의 교차 접근 차단 | [`test_product_features.py`](../backend/tests/test_product_features.py), [`test_leaderboard.py`](../backend/tests/test_leaderboard.py), [`test_auth_session_version.py`](../backend/tests/test_auth_session_version.py), [`Header.auth.test.tsx`](../frontend/src/app/components/Header.auth.test.tsx) | L에서 fixture 토큰과 임시 DB로 변경을 확인한다. 실제 화면에서는 로그인 계정과 브라우저 localStorage를 사용하므로 E에 테스트 계정과 변경 가능한 프로필 값이 필요하다 |
| 비밀번호 재설정 `/api/v1/auth/password-reset/request`, `/confirm` | 모르는 identity에도 계정 존재를 노출하지 않는 응답, 만료·single-use token, 비밀번호 변경, 기존 JWT 폐기, 실패 시 token 무효화 | [`test_product_features.py`](../backend/tests/test_product_features.py), [`test_auth_session_version.py`](../backend/tests/test_auth_session_version.py), [`PasswordReset.test.tsx`](../frontend/src/app/pages/PasswordReset.test.tsx) | 알 수 없는 identity와 debug/local token은 L로 가능하다. 알려진 계정에 대한 실제 발송은 M이며 SMTP 자격증명과 수신함/mail sink가 필요하다. confirm은 비밀번호·auth_version을 변경하므로 disposable 계정을 쓴다 |
| 문제 관리·조회 `/api/v1/problems` | public/private/system/deleted 가시성, difficulty/tag/search/페이지네이션, 문제/테스트케이스 생성·수정·soft-delete, 숨은 테스트 비노출, user progress | [`test_problem_integrity.py`](../backend/tests/test_problem_integrity.py), [`test_problem_submission.py`](../backend/tests/test_problem_submission.py), [`test_list_pagination.py`](../backend/tests/test_list_pagination.py), [`test_product_features.py`](../backend/tests/test_product_features.py) | 읽기는 U/L/E 모두 가능하다. create/update/delete와 private/hidden 사례는 admin/creator 토큰과 DB 변경이 필요하다. 운영 검증에서는 전용 문제를 만들고 반드시 정리한다 |
| 연습 제출·제출 내역 `/api/v1/problems/{id}/submit`, `/submissions` | code/input 크기·소유권, durable receipt, 채점 verdict, 첫 정답만 점수 지급, history 필터·페이지네이션, 만료 receipt의 410과 재접수 금지 | [`test_problem_submission.py`](../backend/tests/test_problem_submission.py), [`test_execution_api.py`](../backend/tests/test_execution_api.py), [`test_execution_results.py`](../backend/tests/test_execution_results.py), [`test_execution_retention_owner.py`](../backend/tests/test_execution_retention_owner.py), [`executionApi.test.ts`](../frontend/src/app/services/executionApi.test.ts) | L은 fake worker/격리 DB로 receipt·점수 행을 변경한다. 실제 채점 E는 Redis/Postgres와 worker/sandbox 및 언어 toolchain을 요구하고 제출/점수/기록을 남긴다 |
| 리더보드 `/api/v1/problems/leaderboard`, `/leaderboard/score` | ranking/rating/tier, admin score 권한, 동일 정답의 중복 award 방지, admin 제외, 사용자 통계 | [`test_leaderboard.py`](../backend/tests/test_leaderboard.py), [`test_execution_results.py`](../backend/tests/test_execution_results.py), [`test_scoreboard_cache.py`](../backend/tests/test_scoreboard_cache.py), [`Leaderboard` route assertions in `routes.test.tsx`](../frontend/src/app/routes.test.tsx) | L에서는 임시 user/problem/score를 만든다. E에서는 실제 제출 또는 명시된 disposable score가 DB/cache를 변경하므로 운영 계정·정리 계획이 필요하다 |
| 컴파일·실행 `/api/v1/compiler/compile`, `/run`, `/queue` | B++ 분석 결과와 diagnostics, run stdout/stderr/exit code, 지원 언어(B++, C, C++, Python, Java, JavaScript), queue 상태·필터·verdict·소유권, generic error/no secret leak | [`test_compiler.py`](../backend/tests/test_compiler.py), [`test_compiler_routes.py`](../backend/tests/test_compiler_routes.py), [`test_compiler_service.py`](../backend/tests/test_compiler_service.py), [`test_durable_judging.py`](../backend/tests/test_durable_judging.py), [`test_execution_worker.py`](../backend/tests/test_execution_worker.py), [`compilerStore.test.ts`](../frontend/src/app/store/compilerStore.test.ts), [`durableCallers.test.ts`](../frontend/src/app/services/durableCallers.test.ts) | U는 parser/graph/오류 계약만 확인한다. L은 mocked runner/queue를 사용한다. 실제 6언어와 sandbox 한도·프로세스 격리는 E이며 Docker 이미지, worker, Redis/Postgres, 실제 toolchain이 필요하다 |
| durable 실행 `/api/v1/executions` POST/GET | idempotency 재시도는 같은 receipt, 다른 code는 conflict, owner/session 격리, 202/410/404/409/429/413, content retention과 결과 공개 범위 | [`test_execution_api.py`](../backend/tests/test_execution_api.py), [`test_execution_retention.py`](../backend/tests/test_execution_retention.py), [`test_execution_retention_migration.py`](../backend/tests/test_execution_retention_migration.py), [`test_submission_durable_integration.py`](../backend/tests/test_submission_durable_integration.py), [`executionApi.test.ts`](../frontend/src/app/services/executionApi.test.ts) | L은 임시 DB와 fake clock/worker로 영속 상태를 변경한다. E는 두 API가 같은 Postgres/Redis를 보는지와 실제 worker 완료를 확인하므로 실제 서비스 자원이 필요하다 |
| 터미널 `/ws/terminal` | 허용 Origin, start payload/UTF-8/byte budget, admission, broker session/lease/renew/close, idle/start deadline, sandbox relay, 1013/503 및 sanitized error | [`test_terminal_admission.py`](../backend/tests/test_terminal_admission.py), [`test_terminal_broker.py`](../backend/tests/test_terminal_broker.py), [`test_terminal_receipt.py`](../backend/tests/test_terminal_receipt.py), [`test_terminal_uncertain_cleanup.py`](../backend/tests/test_terminal_uncertain_cleanup.py), [`test_terminal_live.py`](../backend/tests/test_terminal_live.py) | U/L에서 protocol·broker를 fake로 확인한다. E는 실제 WebSocket 브라우저/클라이언트, Redis broker, Docker sandbox와 네트워크가 필요하고 세션·작업 폴더가 생성/종료된다 |
| 프로젝트 저장 `/api/v1/projects` GET/PUT/DELETE | 사용자·scope 격리, scope/path/NUL·크기 검증, revision CAS, 동시 저장 winner 1개, delete 후 old revision 거부 | [`test_project_revisions.py`](../backend/tests/test_project_revisions.py), [`test_product_features.py`](../backend/tests/test_product_features.py), [`CodeEditor.identity.test.tsx`](../frontend/src/app/components/CodeEditor.identity.test.tsx) | L에서 임시 DB와 여러 fixture 계정을 사용한다. PUT/DELETE는 DB 변경이다. 브라우저 E는 계정 A/B, localStorage revision, 탭 경쟁을 실제로 재현하며 운영 데이터는 쓰지 않는다 |
| 커뮤니티 `/api/v1/community/posts`, `/counts` | notice/admin 권한, author/admin edit/delete, public/private/deleted 필터, problem별 comment count·pagination, 계정 전환 | [`test_community_counts.py`](../backend/tests/test_community_counts.py), [`test_product_features.py`](../backend/tests/test_product_features.py) | GET/count는 L로 확인 가능하다. 게시·수정·삭제는 사용자/admin 자격증명과 DB 변경이 필요하며 E 브라우저에서는 disposable post를 생성하고 삭제한다 |
| 관리자 `/api/v1/admin/users` GET/PATCH | admin-only 검색·페이지네이션, role/profile 변경, 자기 자신 demote 금지, uniqueness, 감사 actor/route metadata | [`test_admin_audit_api.py`](../backend/tests/test_admin_audit_api.py), [`test_admin_audit_transactions.py`](../backend/tests/test_admin_audit_transactions.py), [`Admin.access.test.tsx`](../frontend/src/app/pages/Admin.access.test.tsx) | U/L에서 권한과 감사 트랜잭션을 확인한다. E는 admin credential과 변경 가능한 계정이 필요하고 user/role/profile/audit 행을 변경한다 |
| 대회 `/api/v1/contests` 전 구간 | admin create/edit/publish, problem snapshot/visibility, join/deadline, participant-only problem, durable contest submit, scoreboard/pending/finalization, idempotency | [`test_contests.py`](../backend/tests/test_contests.py), [`test_e2e_contest_flow.py`](../backend/tests/test_e2e_contest_flow.py), [`ContestPages.test.tsx`](../frontend/src/app/pages/ContestPages.test.tsx), [`test_execution_results.py`](../backend/tests/test_execution_results.py) | L은 fake clock/worker와 임시 DB로 가능하다. 실제 E는 admin·참가자 계정, 실제 queue/grading, 시간 경계와 cache를 사용하며 contest/problem/participation/submission/score 행을 변경한다 |
| 공통 admission·CORS·trusted ingress | Origin/CIDR, API/WS prefix, runtime-wide admission, rate limit, unsafe input/secret sanitization, API 하나 중지 중 신규 요청 경로 | [`test_api_admission.py`](../backend/tests/test_api_admission.py), [`test_api_admission_rejection.py`](../backend/tests/test_api_admission_rejection.py), [`test_trusted_ingress.py`](../backend/tests/test_trusted_ingress.py), [`test_ingress_validation.py`](../backend/tests/test_ingress_validation.py), [`apiBase.test.ts`](../frontend/src/app/services/apiBase.test.ts) | U/L은 middleware 계약과 거부 응답을 확인한다. LB 장애·두 API 공유 상태는 E/P로만 의미가 있으며 한 API를 중지하는 변경, trusted proxy 설정과 실제 client address가 필요하다 |

## 프론트엔드 화면·기능 인벤토리

라우트 정의는 [`frontend/src/app/routes.ts`](../frontend/src/app/routes.ts)와 실제
lazy page를 기준으로 했다. 화면 단위 테스트가 없는 기능은 “실패”라는 뜻이
아니라, 브라우저 또는 API 통합 단계에서 별도로 실행해야 한다는 뜻이다.

| 화면/경로 | 기능 및 백엔드 연결 | 후보 프론트 테스트·추가 검증 |
| --- | --- | --- |
| Landing `/` | IDE/challenges/community/leaderboard 진입 CTA, 지원 언어와 B++ AST·SSA·IR·ASM 안내 | [`routes.test.tsx`](../frontend/src/app/routes.test.tsx)에서 copy/links를 확인한다. 실제 navigation·배포 base path는 브라우저 E에서 확인한다 |
| IDE `/ide` | Monaco local worker, 언어 선택, compile/run, output console, challenge context, AST/SSA graph·IR/ASM analysis, durable polling, project autosave, terminal | [`IDE.mobile.test.tsx`](../frontend/src/app/pages/IDE.mobile.test.tsx), [`CodeEditor.identity.test.tsx`](../frontend/src/app/components/CodeEditor.identity.test.tsx), [`CompilerGraphViewer.test.tsx`](../frontend/src/app/components/CompilerGraphViewer.test.tsx), [`compilerStore.test.ts`](../frontend/src/app/store/compilerStore.test.ts), [`localMonaco.test.ts`](../frontend/src/app/services/localMonaco.test.ts), [`monacoWorkerAssets.test.ts`](../frontend/src/app/services/monacoWorkerAssets.test.ts), [`durableCallers.test.ts`](../frontend/src/app/services/durableCallers.test.ts) 후보가 있다. 실제 compile/graph/6언어/terminal/project save는 backend E와 브라우저가 함께 필요하다 |
| Challenges `/challenges`, `/challenges/:challengeId` | 문제 검색·난이도·tag·pagination, 상세 description/sample, progress, 제출·최근 제출·queue/IDE/submissions 이동 | [`routes.test.tsx`](../frontend/src/app/routes.test.tsx)와 backend 문제/제출 테스트를 함께 본다. 목록 filter와 제출 후 화면 갱신은 별도 브라우저 E가 필요하며 제출은 DB/queue를 변경한다 |
| Compile Queue `/queue` | compile/run/grading 상태, verdict/kind/user/problem 필터, pagination·group, receipt deep link | 직접 page test는 재고상 별도 파일이 없고 [`compilerStore.test.ts`](../frontend/src/app/store/compilerStore.test.ts)·[`durableCallers.test.ts`](../frontend/src/app/services/durableCallers.test.ts)가 client 후보이다. 실제 queue 표시는 E receipt와 worker 상태가 필요하다 |
| Submissions `/submissions` | problem/user/status/verdict filter, pagination, challenge link, 결과/기록 확인 | 직접 page test는 재고상 별도 파일이 없다. backend submission/retention 테스트와 실제 브라우저 E를 조합하며 제출 기록을 읽는다 |
| Leaderboard `/leaderboard` | 전체 랭킹, rating/tier/solved count 표시 | [`routes.test.tsx`](../frontend/src/app/routes.test.tsx), backend [`test_leaderboard.py`](../backend/tests/test_leaderboard.py) 후보. 실제 점수 반영은 제출 또는 score mutation이 필요하다 |
| Community `/community` | notice/problem/free 탭, problem counts, pagination/load more, 로그인 사용자 post 작성·수정·삭제 | 직접 page test는 재고상 별도 파일이 없다. backend [`test_community_counts.py`](../backend/tests/test_community_counts.py)와 실제 browser E를 조합하며 작성/수정/삭제 DB mutation 및 user/admin credential이 필요하다 |
| 인증·프로필 UI (Header/AuthModal) | register/login/logout, token refresh, 현재 사용자와 profile/avatar 표시·수정 | [`Header.auth.test.tsx`](../frontend/src/app/components/Header.auth.test.tsx), backend auth/profile 후보. 실제 credential·브라우저 storage·profile mutation이 필요한 E와 reset M을 별도로 한다 |
| Password Reset `/reset-password` | identity 입력, reset 안내, URL token으로 AuthModal confirm, 성공 후 profile/navigation | [`PasswordReset.test.tsx`](../frontend/src/app/pages/PasswordReset.test.tsx). local debug token은 L, 실제 링크 클릭·메일 수신은 M이며 비밀번호/세션이 변경된다 |
| Admin `/admin` | admin gate, problem CRUD/editor, user 검색·pagination·role/profile 관리 | [`Admin.access.test.tsx`](../frontend/src/app/pages/Admin.access.test.tsx)와 backend admin tests는 gate/계약 후보다. 전체 CRUD는 admin credential과 임시 problem/user/audit DB mutation을 포함한 E가 필요하다 |
| Contests `/contests`, `/new`, `/:contestId`, `/edit`, `/problems/:contestProblemId` | 목록 상태 filter/search, admin editor/library, join/countdown/server time, scoreboard, contest IDE submit | [`ContestPages.test.tsx`](../frontend/src/app/pages/ContestPages.test.tsx), backend [`test_contests.py`](../backend/tests/test_contests.py), [`test_e2e_contest_flow.py`](../backend/tests/test_e2e_contest_flow.py). 실제 publish/join/submit/finalize는 시간·queue·계정·DB/cache mutation을 필요로 한다 |

## 기능별 실제 검증에 필요한 준비

### 계정·프로필·메일

1. 격리 L에서는 일반 사용자 두 명, admin 한 명, 비밀번호가 다른 fixture를 만들고
   각 token의 `auth_version`, owner와 role을 기록한다. register/profile/admin
   mutation은 해당 임시 DB 안에서만 수행한다.
2. E에서는 재사용 가능한 운영 계정을 사용하지 말고 disposable 일반 계정과
   disposable admin 계정을 별도로 준비한다. profile email/nickname/avatar,
   password와 role을 변경한 뒤 원상 복구 또는 계정 폐기를 기록한다.
3. password-reset request의 unknown identity 응답만으로 이메일 기능을 PASS라
   하지 않는다. 알려진 계정의 실제 메일은 SMTP sandbox/mail sink와 수신 확인이
   필요하다. 링크의 token으로 confirm하고, 이전 token/기존 JWT가 거부되는지와
   새 비밀번호 로그인이 되는지를 확인해야 한다. SMTP secret과 reset token은
   로그·문서에 남기지 않는다.

### 문제·채점·프로젝트·커뮤니티·대회

- 문제/대회 생성, 제출, 점수, 게시글, 프로젝트 저장은 모두 상태 변경이다.
  운영 endpoint에서는 기본 데이터를 재사용하지 말고 검증용 namespace/계정과
  정리 가능한 record ID를 먼저 확보한다.
- practice/contest grading은 HTTP 202 receipt만 확인해서 끝내지 않는다. worker가
  완료한 verdict, 독립적으로 조회한 submission/history/scoreboard, 소유자 격리와
  idempotency를 확인한다. 완료 전에는 queue·lease·sandbox가 남아 있을 수 있다.
- project save는 계정 A와 B의 동일 scope, 두 탭의 `expectedRevision`, 삭제 후
  재생성을 각각 확인한다. client localStorage만 읽어 성공으로 보지 말고 GET/PUT
  응답과 서버 revision을 대조한다.
- community/admin/contest 쓰기는 권한 없는 계정, 다른 author/participant,
  private/hidden 데이터에 대한 negative check도 함께 실행한다.

### IDE·컴파일러·터미널

- B++는 compile 응답의 AST/SSA graph node·edge와 IR/ASM source range가 실제
  코드에 대응하는지 확인한다. 일반 run의 stdout만으로 analysis 기능을 PASS라
  하지 않는다.
- six-language smoke는 실제 worker image/toolchain에서 같은 fixture의 exit code,
  stdout/stderr, timeout·compile error를 확인한다. parser/service unit test와
  frontend graph component test는 이 runtime 증거를 대신하지 않는다.
- terminal은 browser의 허용 Origin, WebSocket handshake, start payload, UTF-8
  byte budget, lease/renew/close, idle timeout, sandbox 종료까지 확인한다. Redis
  broker와 Docker sandbox가 없는 mock test는 실제 연결·자원 정리 증거가 아니다.

### LB·장애·배포 경로

- 두 API가 같은 Postgres/Redis와 runtime identity를 보는지, readiness가 실제
  worker 상태를 반영하는지 먼저 확인한다. 그 뒤 한 API를 의도적으로 내려도
  새 login/queue/grading 요청이 살아 있는 API로 처리되는지 확인한다. 이는
  컨테이너 중지와 DB/queue mutation을 포함하므로 E/P 범위다.
- `deploy_server.sh`와 edge/deployment 검증은 기능 테스트와 분리한다. 실제
  production smoke/rollback은 immutable image, SSH/registry/Docker 권한, 백업과
  복구 승인 없이는 실행하지 않는다. 정적 wiring test나 local fixture는 운영
  rollback 성공을 증명하지 않는다.

## 실행 기록에 남겨야 할 것

각 기능의 완료 판정에는 테스트 파일명만 적지 말고 다음을 함께 남긴다.

- 실행 시각, commit/release SHA, 대상 URL 또는 격리 fixture 식별자
- 정확한 명령과 선택된 테스트 수/skip/실패 수
- 사용한 서비스(Postgres/Redis/worker/SMTP/browser)와 외부 자격증명 종류
  (값 자체는 기록하지 않음)
- mutation이 만든 user/problem/post/project/contest/job ID와 정리·복구 결과
- negative/security check의 HTTP/WS 상태와 응답·로그에 비밀이 없다는 관찰
- 실제 메일 수신, 실제 6언어 실행, API 중지 후 신규 요청, rollback처럼 단위
  테스트로 대체할 수 없는 증거의 원본 로그 위치

이 파일 자체는 위 검증을 실행하지 않았고, 어떤 기능의 통과를 선언하지 않는다.
