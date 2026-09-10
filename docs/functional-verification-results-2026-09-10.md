# 전체 기능 검증 결과 — 2026-09-10

## 결론

**전체 정상은 아니다.** 주요 실행·채점·계정·게시판·대회 경로는 아래 범위에서 통과했지만, 비밀번호 재설정 메일 미설정과 IDE 실행 오류 분류 문제가 실제로 확인됐다. 테스트 통과 수를 모든 화면·예외 상황의 보증으로 해석하면 안 된다.

이번 요청은 검증이므로 제품 코드 수정, 재배포, main push는 하지 않았다. 운영 계정·게시글·점수를 변경하는 테스트는 운영 DB가 아닌 별도 복제 환경에서 실행했다.

## 검증 환경

- 운영: `https://cuha.cju.ac.kr/webcompiler/`.
- 배포 소스: `eef08f2486926bbf5eb1017886d0b88634eddb45`.
- 실제 통합 환경: 배포 서버의 `/home/vulpo/webcompiler-functions-F7mMREBf`, Compose 프로젝트 `webcompiler-functions-f7mmrebf`. 배포와 동일한 backend/frontend/sandbox 이미지, API 2개, 별도 PostgreSQL·Redis·네트워크·런타임 ID·서명 키를 사용했다. 포트는 loopback 15180/18010만 열었다.
- 실제 사용자 데이터의 변경을 피하기 위해 배포 전 백업을 별도 DB에 복원했다. 미처리 작업이 없음을 확인한 뒤 초기화·워커를 시작했다. 계정·문제·대회 등 변경은 이 복제 DB에서만 수행했다.
- 로컬 회귀 검증은 현재 작업 트리 기준이다. 실제 이미지 통합 결과와 구분한다. 기능 목록과 후보 테스트는 [검증 인벤토리](functional-verification-inventory-2026-09-10.md)에 있다.

## 실제로 확인한 기능

| 기능 | 실행한 검증 | 결과/환경 |
| --- | --- | --- |
| 회원·프로필·권한 | 회원가입, 정상/틀린 비밀번호 로그인, 중복 가입 거부, 프로필 변경/조회, 일반 사용자 관리자 API 거부 | 통과 / 복제 실제 API |
| 관리자 | 사용자 검색, 테스트 계정 승격·관리자 접근·강등 후 접근 차단 | 통과 / 복제 실제 API |
| 코드 저장 | 서버 저장/조회/수정/목록/삭제, 다른 사용자 접근 거부, stale revision 충돌 | 통과 / 복제 실제 API |
| 커뮤니티 | 자유 게시글 작성/조회/수정/삭제/개수, 관리자 공지 작성·삭제, 일반 사용자 공지 거부 | 통과 / 복제 실제 API |
| 문제 관리 | 관리자 생성/수정/검색/삭제, 일반 사용자 생성 거부, 숨겨진 테스트 비노출 | 통과 / 복제 실제 API |
| 일반 문제 채점 | 실제 B++ 정답 제출, 첫 점수 20·중복 정답 0, 제출 기록·해결 기록·계정 점수 대조 | 통과 / 복제 실제 Docker 채점 |
| 채점 오류 | 잘못된 C++ 코드는 compile_error, Python 예외는 runtime_error | 통과 / 복제 실제 Docker 채점 |
| 대회 | 비공개 문제 생성·공개 설정·시작 전 비노출·참가·시작·실제 정답 제출·재요청 동일 ID·스코어보드·종료 | 통과 / 복제 실제 API·Docker |
| 대회 종료 | 대회 점수 500, 일반 점수 17 반영, 문제 일반 공개, 숨겨진 테스트 계속 비공개 | 통과 / 복제 실제 API·Docker |
| 6개 언어 | B++, C, C++, Python, Java, JavaScript 각각 실제 출력 42/exit 0 | 통과 / 복제 실제 Docker 실행 |
| 입력·런타임 오류 | Python stdin 전달, Python 예외 stderr/비정상 종료 | 통과 / 복제 실제 Docker 실행 |
| B++ 분석 | 최적화 포함 AST·SSA·IR·ASM 결과 생성, 문법 오류 진단 | 통과 / 복제 실제 컴파일러 |
| 큐·제출·랭킹 | 공개 목록, 내 제출, 정답 사용자 랭킹 반영, 푼 문제 삭제 후 총점 유지 | 통과 / 복제 실제 API |
| 운영 조회 | health·문제·랭킹·대회·큐·제출·공지·자유게시판 API | 모두 HTTP 200 / 운영 |
| 운영 터미널 | 실제 WSS 연결 → Python READY → 입력 42 → GOT:42 → exit 0 | 통과 / 운영 |
| 비밀번호 재설정 | 요청 및 잘못된 토큰 거부 | **요청 503, 기능 이용 불가** / 운영·복제 |
| IDE 컴파일 오류 | C++ 문법 오류를 /compiler/run으로 실행 | **runtime_error 오분류** / 배포와 동일한 복제 이미지 |

대회 경계·공동 순위·패널티·채점 역전 등 전체 규칙은 회귀 테스트의 범위이며, 이번 실제 1분 대회 시나리오가 모든 규칙을 실서버에서 재현했다는 뜻은 아니다.

## 확인된 문제

### F01. 운영 비밀번호 재설정 사용 불가

`POST /api/v1/auth/password-reset/request`에 유효한 형식의 identity를 보내면 HTTP 503과 `비밀번호 재설정 메일 설정이 필요합니다.`가 반환된다. 실제 발송 설정이 없어 메일 전달·링크 클릭·비밀번호 변경 전체 흐름을 검증할 수 없다. 가짜 메일 서버로 대체해 완료 처리하지 않았다.

운영 SMTP 발송 계정·발신 주소 설정 후 실제 수신, 만료·일회용 토큰, 이전 세션 무효화까지 확인해야 한다. 비밀 값은 로그·문서에 기록하지 않았다.

### F02. IDE C++ 컴파일 오류가 런타임 오류로 분류됨

재현: `POST /api/v1/compiler/run`에 `language=cpp`, `code=not valid C++`를 제출하고 반환된 작업 ID의 결과를 조회한다. stderr는 `expected unqualified-id before 'not' token`, exit_code는 1인데 verdict는 `runtime_error`다.

`backend/app/services/compile_queue.py`의 `_classify_nonzero_execution`은 stderr에 `compiler pipeline`·`compilation`·`compile` 등이 있는지로 컴파일 실패를 추정한다. 실제 g++ 진단에는 그 단어가 없어 잘못 분류된다. 실행 결과에 컴파일/실행 실패 단계를 명시적으로 전달하는 방식이 필요하다.

**일반 문제 채점의 동일 입력은 실제 compile_error로 정상 판정됐다.** 채점은 `judging.py`에서 사전 컴파일 단계를 따로 검사한다. 따라서 이번 증거로 대회 패널티까지 잘못된다고 단정하지 않는다. 대회에서 해당 오류·패널티를 실제 재현하는 추가 검증은 별도다.

## 회귀·브라우저 검증

- 백엔드 전체: `1944 passed, 357 skipped, 8 subtests passed` (87.75초). skip은 외부 서비스/플랫폼 조건이 필요한 항목으로, 통과에 포함하지 않는다.
- 프런트엔드: Node 24 타입 검사 통과, Vitest 17개 파일/70개 테스트 통과. React act 경고 2건.
- 로컬 브라우저: 홈 2/2, durable receipt UI mock 2/2, 프로젝트 저장 충돌 mock 1/1 통과. 이 mock 결과는 실제 서버 큐/저장 성공의 증거와 구분한다.
- Monaco production-preview 빌드: root/subpath 두 배치에서 10/10 통과. 에디터 로딩·언어 템플릿·worker·CSP 검증이며 실제 Docker 채점은 위 통합 결과를 따른다.
- 운영 Edge: 기존 `webcompiler.spec.ts`의 흐름을 격리 브라우저 컨텍스트에서 실행한 검사 중 홈/기본 IDE/B++ 실제 실행/리더보드 4개 통과. 이 네 경로에서 pageerror 및 비정상 중단을 제외한 script/style/font/image 로드 실패는 0건. 기본 Chromium 실행기는 로컬에 없어 Edge를 사용했으며 원본 spec 그대로의 5/5 통과로 표기하지 않는다.
- 운영 Python 터미널 **UI** 검사는 테스트 선택자가 숨겨진 `<option>`을 클릭하려 해 언어 선택 단계에서 timeout됐다. 실행/입력 단계에 도달하지 못해 UI 통과도 제품 실패도 확정하지 않는다. 별도의 실제 운영 WSS 입력/출력 검증은 통과했다.
- 로컬 대회 브라우저 fixture: 0/1. 생성·참가·문제 열기·6개 템플릿 변경·제출까지 진행했지만 `contests.local.spec.ts:55`의 정답 기대값이 20초 동안 `대기`여서 실패했다. 이후 저장 재로딩·스코어보드·모바일·종료 UI 검사는 실행되지 않았다. 이 실패를 통과로 덮지 않는다. fixture 프로세스 2개 및 loopback 4175/18001 listener 종료를 확인했다.

## 테스트 자체의 실패와 제품 실패 구분

- 최초 계정 harness가 13자 토큰을 보내면서 HTTP 400을 기대했다. 스키마 최소 길이 32에 의해 422가 맞다. 후속 실행에서 짧은 토큰 422, 길이 64의 알 수 없는 토큰 400, 관리자 접근 거부 403을 확인했다. 원본 실패 로그를 보존했고 제품 결함으로 세지 않았다.
- 최초 언어 그룹의 빈 AssertionError는 분리 실행으로 F02임을 확정했다. 6개 언어 정상 실행 및 stdin은 모두 통과했다.
- 로컬 contest 카드 mock 검사는 query-bearing 목록 URL과 `**/api/v1/contests` 패턴이 맞지 않아 예상 4개 fixture 대신 실제 1개 목록을 받았다. 해당 mock 검사 1건은 제품 카드 결함의 증거가 아니다.
- Vite 개발 서버의 엄격 CSP 검사 1건은 React-refresh inline preamble이 차단되어 실패했다. 동일 목적의 production-preview 검사는 통과했다. 최초 운영 수동 검사에서 NBSP/locator로 실패한 항목도 정규화된 기대값을 쓰는 후속 검사와 구분해 보존한다.
- 로컬 대회 fixture의 정적 검토: `contest_browser_server.py`는 기존 `compiler_instance` 메서드만 fake로 바꾸지만, 현재 durable worker는 `runner_factory`로 별도 `DockerCompilerRunner`를 생성한다. 따라서 이 fixture는 현재 채점 실행기를 제대로 대체하지 않는다. 실제 실패 시점의 워커 로그는 별도 보존되지 않아 이것만을 유일한 원인으로 확정하지 않는다. 실제 이미지 기반 대회 API 전주기 통과와 로컬 브라우저 fixture 실패를 함께 기록한다. 실패 trace는 남아 있다면 `frontend/test-results/`에 위치한다.
- `functional-api-results.json`의 `password_reset_configuration: PASS`는 **503 차단을 기대한 진단의 성공**이다. 비밀번호 재설정 기능의 성공이 아니다.

## 정리·증거

복제 환경의 HTTP 진입·API·워커를 정상 종료하고 미완료 작업·sandbox 작업 의도·lease·미배출 워커가 0임을 확인했다. 소유 ID·라벨·경로를 대조한 뒤 테스트 컨테이너 9개, 테스트 볼륨 2개와 전용 네트워크를 제거했다. 공유 배포 이미지는 지우지 않았다. 복제 테스트 DB는 폐기했으며 다시 실행하려면 원본 백업에서 새로 복원해야 한다. 원본 운영 DB·백업은 유지했다.

정리 후 운영 API 2개·워커·프런트·PgBouncer·API proxy·Redis 7개 서비스가 모두 healthy였다. 테스트 스크립트와 비밀을 제외한 결과는 로컬 `.deploy/` 및 서버 검증 경로에 남겼다:

- `functional-api-results.json`
- `functional-account-followup.json`
- `functional-languages-followup.json`
- `functional-grading-followup.json`
- `functional-cleanup-results.json`
- 로컬 `public-function-results.json`

## 미검증·별도 조건

모든 화면의 모든 조합·브라우저·모바일 기기, 운영 관리자 CRUD 전체 클릭 흐름, 운영 터미널의 브라우저 입력 흐름, 실제 메일 수신, 장시간/악성 혼합 부하, 전면 보안 검증, DB/Redis 장애복구·다중 호스트 HA는 이번 확인으로 보증하지 않는다. 이전의 2 API 분산·한 API 중지 smoke는 [기본 배포 보고서](basic-load-balancing-release-2026-09-10.md)의 별도 증거다. 기능 정상 여부 확인을 상업용 운영 적합성 또는 A01~A25/5.4절 전체 완료로 바꾸어 주장하지 않는다.
