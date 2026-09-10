# 기능 검증 커버리지 갭 메모 — 2026-09-10

시점 주의: 아래 표는 새 격리 통합 실행 **직전**의 점검 메모다. 이후 실제 10개 API 기능 묶음, 6언어/터미널/자원 한도/채점/LB 및 추가 F06/F07의 결과는 [현재 수정 대장](functional-remediation-ledger-2026-09-10.md)의 최신 기록을 우선한다. 이 과거 갭 목록을 현재 미실행 목록으로 그대로 인용하지 않는다.

이 메모는 [기능 수정 대장](functional-remediation-ledger-2026-09-10.md)의
13개 기능 행을 [historical 기능 검증 결과](functional-verification-results-2026-09-10.md),
현재 회귀 집계와 대조한 잔여 목록이다. **테스트 수나 과거 실제 실행을 현재
릴리스의 전체 PASS로 승격하지 않는다.** 현재 상태는 새 backend/sandbox/frontend
격리 통합 검증이 진행 중이며, 실제 SMTP 외부 조건은 아직 완료되지 않았다.

## 증거를 읽는 기준

- `과거 actual`은 결과 문서에 기록된 별도 복제 환경·이전 이미지/배포의 증거다.
  현재 릴리스에 자동 전이하지 않는다.
- `현재 local/mock`은 현재 작업 트리의 단위·ASGI fixture·mock 또는 정적 검사다.
  실제 외부 서비스·브라우저·메일 전달을 증명하지 않는다.
- 현재 회귀 집계는 backend **1997 passed, 362 skipped, 8 subtests**와 frontend
  **73 passed, typecheck/build 완료**다. 이는 회귀 건강성 집계이지 아래 13개
  기능의 전수 PASS 표가 아니다.
- 프로필은 별도 현재 local browser **1/1 actual PASS**가 기록되어 있지만,
  전체 계정/권한 조합과 운영 배포 증거로 확대하지 않는다. SMTP 외부 전달은
  미완료다.

## 13개 기능별 잔여 갭

| 기능 행 | 확인된 증거의 종류 | 아직 증명하지 못한 시나리오 |
| --- | --- | --- |
| 홈·메뉴·페이지 이동 | 현재 frontend 회귀·typecheck/build 및 route/page 일부 local/mock, 과거 화면 확인 일부 | 모든 공개·보호 route의 새로고침/뒤로가기/base path, 비콘테스트 390px 화면, 실제 배포 asset/CSP와 링크 전수. route 테스트 존재만으로 브라우저 PASS가 아님 |
| 계정·프로필·권한 | 과거 복제 API에서 가입·로그인·프로필·일반 사용자 admin 거부, 현재 auth 회귀와 프로필 local browser 1/1 | 현재 릴리스에서 username/email/nickname 각각의 가입·로그인, logout 후 token/storage 무효화, 만료·role 철회·타 계정 격리, 프로필 영속화와 오류 UI의 전 조합. 실제 운영 계정 변경은 별도 승인 필요 |
| 비밀번호 재설정 | local schema/service/reset-token 회귀와 설정 전달 검사, 과거/운영 결과에서 reset request 503 확인 | SMTP host/from/auth/TLS로 실제 발송, 수신 URL 클릭, 만료·single-use·이전 JWT 폐기까지. 실제 SMTP 자격증명·수신함/mail sink가 필요하며 현재 외부 조건은 미완료 |
| IDE 6언어 실행 | 과거 복제 Docker에서 B++/C/C++/Python/Java/JavaScript 출력·stdin 일부 actual, 현재 local compiler/phase 회귀 | 현재 backend+sandbox 이미지와 frontend의 compile→queue→poll→output 전주기, 언어별 오류/timeout/OOM/중단·재연결·저장. 과거 이미지와 launcher 검증은 새 통합 배포를 대신하지 않음 |
| B++ 분석 | 과거 실제 compiler에서 AST·SSA·IR·ASM 및 진단 생성, 현재 parser/service/graph local 테스트 | 현재 이미지의 UI에서 최적화별 graph/source range/IR·ASM 표시, 분석 실패와 큰/잘못된 입력의 오류 화면, backend 응답과 화면 모델의 일치 |
| 대화형 터미널 | 과거 운영/복제 WSS에서 Python 입력·출력·exit 확인, 현재 broker/admission/phase local 및 일부 fixture | 현재 새 backend+sandbox/frontend의 실제 WebSocket handshake, 각 언어 입력·출력·close/reconnect, idle/start deadline, 1013/503, byte/CPU/PID 제한과 sandbox 정리. 브라우저 UI 전체는 별도 |
| 클라우드 프로젝트 | 과거 복제 API에서 저장/조회/수정/목록/삭제·타 사용자 거부, 현재 CAS/identity local 및 CodeEditor 회귀 | 현재 브라우저에서 생성→재로드→삭제, 동일 scope의 A/B 격리, 두 탭 CAS 충돌, 문제/대회 scope와 localStorage revision. 실제 서버 DB 영속화 재검증 필요 |
| 문제 관리·검색 | 과거 복제 API에서 admin CRUD·검색·hidden test 비노출, 현재 문제/무결성/페이지 local 테스트 | 현재 화면의 tag/difficulty/search/page, public/private/system/deleted 경계, admin editor 오류·중복·삭제 후 조회, 실제 새 release의 권한과 DB 상태 |
| 채점·큐·제출·점수·랭킹 | 과거 복제 Docker/API에서 B++ 정답·중복 award·submission/ranking 및 일부 오류, 현재 durable/retention/worker local 회귀 | 현재 두 API와 새 worker에서 CE/WA/RE/TLE/OOM, 202 receipt/410 retention, owner·idempotency·재시도·queue filter/page, 첫 정답만 award와 cache 일관성. 모든 verdict·경쟁 조건의 실제 실행은 남음 |
| 커뮤니티 | 과거 복제 API에서 자유글·공지 CRUD/counts와 권한 확인, 현재 counts/권한 local 테스트 | 현재 브라우저의 notice/problem/free 탭, pagination/load-more, author/admin edit/delete, 타 사용자/private/deleted 거부 및 새 배포 DB. fixture CRUD는 실제 UI/배포 증거가 아님 |
| 관리자 | 과거 복제 API에서 user search·승격·강등·접근 차단, 현재 admin gate/audit local 및 frontend access test | 현재 `/admin` 전체 문제 CRUD·사용자 profile/role 수정, 중복/자기 권한 제거/감사 실패·복구 UI, 새 release에서 admin credential과 영속 결과 대조 |
| 대회 전체 | 과거 복제 API/Docker에서 비공개→공개→참가→제출→종료 일부 actual, 현재 local browser 1/1은 fixture/fake 경로와 구분 | 현재 실제 worker에서 publish/lock/start/deadline, private leak, join, contest 제출·idempotency, 동점/패널티/pending/finalization, 종료 후 일반 점수와 UI 모바일 전수. local fixture PASS는 실제 grading을 대신하지 않음 |
| 공유 실행/분산 경로 | 과거 basic-LB/복제 보고서의 2 API·공유 상태·API 하나 중지 smoke 일부, 현재 lifecycle/readiness/queue local 회귀 | 현재 release에서 두 API가 같은 Postgres/Redis/runtime identity를 사용하고 한 API 중지 중 login/queue/grading/receipt가 계속 처리되는지, drain/restart/lease/복구·혼합 버전/HA 경쟁. 외부 multi-service 장애 주입 필요 |

## 오류 대장과 남은 확인의 연결

- **F01**: 설정 전달 회귀는 local 검증됐지만, 결과 문서의 운영 503은 여전히
  유효하다. 실제 SMTP 수신·링크·토큰 소비·세션 무효화 전에는 비밀번호 재설정
  기능을 완료로 표시하지 않는다.
- **F02**: C++ 실행 오류 분류 수정과 phase 회귀는 현재 local/격리 증거로만
  확인한다. 새 backend와 새 sandbox를 함께 올린 현재 통합에서 `/compile`·`/run`·
  grading의 compile/runtime 분류를 재현해야 한다.
- **F03**: STARTTLS 기본 context와 인증 실패 차단은 local 회귀 대상이다. 실제
  인증서·hostname 검증 실패와 성공 발송은 SMTP 외부 조건이므로 별도다.
- **F04**: 명시적 null 프로필 저장 수정과 현재 프로필 browser 1/1은 진전이다.
  생략 필드 보존, SQLite/실 DB 영속화, 계정/관리자 편집 충돌과 현재 릴리스
  브라우저 전수는 남아 있다.
- **T02/T03/T04/T05**: runner·fixture·CSP·대회 화면 관련 대장 항목은 기능
  증거와 테스트 harness 증거를 분리해야 한다. fake sandbox/preview/local mock의
  성공을 실제 터미널·grading·운영 CSP의 성공으로 적지 않는다.

## 다음 판정에 필요한 최소 증거

1. 현재 release SHA와 새 backend/frontend/sandbox 이미지가 같은 격리 namespace에서
   기동된 기록.
2. 일반 사용자·admin·두 계정의 auth/profile/project/community/contest mutation과
   정리 결과, receipt/job/lease가 0으로 수렴한 기록.
3. 실제 6언어·B++ 분석·terminal의 HTTP/WS 결과와 오류 분류, 두 API 공유 상태 및
   API 하나 중지 후 신규 요청 결과.
4. SMTP sandbox의 실제 수신 message와 token expiry/single-use/old-session
   rejection 결과. 비밀 값과 token은 기록하지 않는다.
5. 위 증거와 별도로 frontend 브라우저의 route/refresh/mobile/error 화면 결과.

그 전까지 이 파일은 검증 누락 메모이며, 기능 전체 또는 A01-A25의 완료 선언이
아니다.
