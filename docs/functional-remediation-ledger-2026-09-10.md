# 기능 전수 점검·수정 대장

범위: 기존 기능 인벤토리의 모든 화면/API. 이전 검증 통과는 출발점이며 새 수정 후 재검증을 대체하지 않는다. 운영 설정/데이터 변경·배포·main push는 별도 승인 필요. 메일 실전송 같은 외부 조건은 미완료로 남긴다.

## 최신 판정

**최종 후속 결과:** F13 일반 제출 언어 고정, F14 초기화 중 언어 선택 덮어쓰기를 추가로 수정했다. 현재 등록된 F02~F14는 수정 및 명시된 회귀/실제 검증을 마쳤고, **F01 실제 SMTP 메일 재설정은 외부 설정이 없어 미완료**다. 아래 진행 중 표현은 중간 이력이며 이 판정과 [실제 화면 최종 보고서](functional-runtime-closure-2026-09-10.md)가 우선한다.

- 최종 프런트 **25파일122PASS**, 타입 검사 PASS, subpath 빌드15.15초. 이전 backend2001PASS/362skip/8subtests는 이번 backend 제품 변경이 없어 유지한다.
- 최종 F13+F14 격리 frontend에서 브라우저 **12/12PASS**: 대회1(174.523초), 계정3(19.516초), 일반 제출/큐/이력/랭킹1(전체16.063초), 6언어터미널+stdin/재연결7(73.335초).
- 49 namespace의 컨테이너9개/데이터볼륨2개/네트워크/이미지를 소유권·미처리 작업0 확인 후 삭제했다. 테스트 데이터는 복구본 없이 삭제했다. 터널/일회용 로컬 계정 파일도 제거했다. 비밀 없는 결과는 `.deploy/contest-runtime-evidence-49/`와 `.deploy/test-results/*-runtime/`에 보존했다.
- 후속 조회에서 시험 리소스 잔여 없음, 기존 운영7서비스 healthy 확인. 운영 변경/배포/main push 없음. Goal active 유지; 모든 조합 무결함 또는 전체 인프라 심화 검증 완료를 뜻하지 않는다.

### 중간 재현·수정 이력

추가 F14: 실제 6언어 화면 검사에서 Monaco 준비 전에 언어 선택이 가능하고, 초기화가 이후 저장 언어/기본 B++로 덮는 현상을 확인했다(C/C++/Java/JS 화면에 소인수분해 기본 코드, Python stdin 시험 화면은 B++ 선택 및 컴파일 실패). Header 선택/저장/컴파일/실행을 현재 editor hydration 완료 전 비활성화하고 unmount 때 readiness를 해제했다. readiness red1→green1와 editor lifecycle1을 추가했다. 전체 **25파일122PASS**, 타입 검사 PASS, subpath 빌드15.15초. 초기 B++ 데모를 보존하므로 B++ 기본 템플릿 시험은 다른 언어를 거쳐 B++를 명시적으로 다시 선택한다.

F13+F14 격리 프런트 `sha256:0c2bf9cfd47e60d9ad55628245308d7863355797ffee7570db0fbbddb3085bf3`, 자산 아카이브 `ad5d42532f3360dd415dcd2800033fb781e7416d2f87c345c5be45b38e069ad6`로 frontend 서비스만 교체했고 다른 컨테이너 ID는 동일함을 검증했다. F13 이전 실제 UI 시도는 테스트 locator에서 중단되어 잘못된 POST 증거를 얻지 못했고, 코드/단위 red6이 재현 근거다. 수정 이미지에서 `language: python` 요청과 실제 정답을 관찰했으며 큐/이력/랭킹까지 전체 실행 중이다.

후속 실제 화면 감사에서 **F13 일반 문제 제출 언어 고정**을 추가 발견했다. `JudgePanel`이 IDE 선택과 무관하게 `bpp`를 전달했다. 선택 언어 store 구독으로 수정했고 7개 회귀 중 수정 전 6개 실패 → 수정 후 7개 통과했다. 프런트 전체 24파일120개 통과, 타입 검사 통과, subpath 빌드5.72초. 새 테스트의 Testing Library 옵션 타입 오류는 테스트 코드에서 바로잡은 뒤 타입 검사를 다시 통과했다. 아래 F02~F12 완료 설명은 기존 결과이며 F13 실제 이미지 검증은 진행 중이다.

현재 `/home/vulpo/webcompiler-contest-browser-49L0gmmL`에 별도 빈 PostgreSQL/Redis/2 API/worker/프런트를 구성해 최종 브라우저 검증을 추가한다. 기존 f78 정리 기록과 구분한다. 운영 복사 데이터 없이 임시 계정만 사용한다. 대회 첫 시도는 Monaco가 `print(`에 `)`를 자동 추가해 실제 저장 코드가 `print()`였으므로 WA가 정확했고, CE 시험 입력을 `if :`로 변경하고 실제 POST code 일치를 검증했다. 두 번째 시도는 실제 WA/CE/AC/중복 AC·점수·마감·17점 지급·공개 처리까지 통과했지만 마지막 모바일 IDE의 비활성 코드 탭을 바로 검사해 실패했다. 코드 탭을 명시적으로 선택하도록 고쳤으며 **전체 PASS로 세지 않고** 재실행한다.

기록된 제품 오류 F01~F12 중 **F02~F12는 코드 수정과 해당 회귀 검증을 마쳤다**. F09~F12는 후속 경계 검사에서 추가로 발견했다. F01 실제 메일 재설정은 SMTP 제공자·발신 주소·서버 설정 경로가 없어 미완료다. 운영 배포/main push는 하지 않았으며 goal은 active로 유지한다. 전체 기능의 모든 입력/경쟁/외부 장애 조합에 오류가 없다는 보증은 아니다.

- 최신 로컬: backend **2001 passed, 362 skipped, 8 subtests / 89.98초**; frontend **23파일113 passed**, 타입 검사와 subpath 빌드 통과(6.25초). Skip은 통과로 세지 않는다. backend 제품 코드는 후속 경계 검사에서 변경하지 않았고4개 권한 검증을 추가했다.
- 실제 격리 서버: API 10개 기능 묶음, 터미널 9사례와 닫기/재연결, 자원 한도 5사례, 채점 6사례, 2 API 공유 상태/한 API 중지 중 신규 실행 통과.
- 실제 Edge: 데스크톱/390px 탐색·가입·프로필/경쟁 4개, 커뮤니티 1개, 관리자 1개, 최종 IDE 3개 통과. 응답 완료 동기화를 강화한 프로필 경쟁 단독 재실행도 통과. 같은 테스트의 재실행 수를 독립 시나리오 수에 더하지 않는다.
- 시험용 컨테이너 9개·데이터 볼륨 2개·네트워크·파생 이미지·builder를 소유권과 미처리 작업/lease/operation 0 확인 뒤 제거했다. 테스트 DB 데이터는 삭제되어 복구 대상으로 보관하지 않았다. 로컬 SSH 터널과 일회용 계정 파일도 정리했다. 비밀 없는 결과 JSON/소스 아카이브는 보존했다.
- 별도 읽기 검사에서 시험용 리소스 잔여 없음과 기존 운영 7서비스 healthy를 확인했다. 운영 DB/설정/배포 이미지는 변경하지 않았다.

## 오류 대장

| ID | 재현/영향 | 담당·현재 상태 | 수정 후 필요한 증거 |
| --- | --- | --- | --- |
| F14 | IDE 초기 로딩 중 선택한 언어/코드가 늦은 Monaco 초기화로 B++/저장 코드로 덮임 | Root 실제 초기화 경합 발견·readiness flag/버튼 gate, 준비 완료·unmount 회귀2개 | 최신 격리 이미지 6언어 템플릿/실행 및 Python stdin/재연결7PASS; 미배포 |
| F13 | 일반 문제 IDE에서 Python 등 선택 후 제출해도 JudgePanel이 `bpp` 고정 전송 | Root 선택 언어 구독 수정; 6언어와 열린 패널 언어 변경 회귀7PASS | Terra 최신 실제 UI Python POST/정답/큐/이력/137점랭킹1PASS; old 이미지 POST는 harness중단으로 미관찰; 미배포 |
| F01 | 운영 reset request503, SMTP 미설정 | 설정 전달 회귀6PASS, 코드상 누락 미발견 / 사용자 발신 설정 필요 | 실제 SMTP 수신·토큰 소비·세션 무효화 미완료 |
| F02 | IDE C++ 컴파일 오류→runtime_error | Root 수정·현재 backend/sandbox 실제 HTTP/WS·채점 검증 완료, 미배포 | nonce phase·실제 DB verdict·제어 프레임 비노출·자원 한도 근거 확인; 아래 파생 이미지 범위 참조 |
| F03 | SMTP STARTTLS 기본 context가 서버 인증서를 검증하지 않음 | Root red 재현 후 create_default_context 적용 | context의 CERT_REQUIRED/check_hostname 및 인증 실패 시 로그인/전송 차단 회귀; 실 SMTP 조건 별도 |
| F04 | 프로필 빈칸 저장이 무시됨(자기 프로필·관리자 편집), UI가 기본 표시값을 편집값으로 복원 | 명시적 null/생략 구분 및 raw avatar 분리, 브라우저1/1PASS | SQLite 영속화·생략 보존·UI 전체 삭제·캐시 제거 후 재로드 검증; 운영 미반영 |
| F05 | 관리자 이메일/닉네임 동시 중복 commit 오류가 처리되지 않음 | 사전 조회 이후 unique 충돌 주입 red 재현, rollback+HTTP409 추가 | 기존 값 보존·감사 트랜잭션·충돌 응답 회귀; 실 동시 요청은 별도 |
| F06 | 인증 모달의 표시 label과 입력칸이 연결되지 않음 | 실제 Edge getByLabel 실패→useId/htmlFor 수정, 전용5PASS | v2 이미지 label 기반 가입·로그인 회귀 통과 |
| F07 | 프로필을 연 직후 입력하면 늦은 GET이 draft를 덮고, 저장 뒤 도착하면 캐시도 이전 값으로 복원 | 실제 PATCH payload부터 옛 이메일임을 확인, Root red2실패→draft 보호/readVersion+token guard 수정 | 전체 frontend80PASS/typecheck/build, 실제 응답 지연 브라우저 통과 |
| F08 | 좁은 desktop 분석 패널에서 ASM 탭을 선택하면 패널 전체가 가로로 밀려 본문·탭이 잘림 | 실제 screenshot과 panel.scrollLeft=98 red 재현; 탭 띠 내부만 스크롤하도록 min-width/overflow 수정 | frontend80PASS/typecheck/build; v3 실제 Edge scrollLeft=0·본문 경계·스크린샷 직접 확인 통과 |
| F09 | 다른 탭 계정 변경 뒤 이전 프로필 초안이 남아 새 계정 토큰으로 PATCH; 늦은 로그인 응답도 새 세션/프로필을 덮음 | Root 6개 red 경계 재현→Header identity 구독·editor/user token 일치 및 AuthModal 로그인/GET 응답 guard | focused10PASS; 실제 local SQLite/두 탭 로그인·로그아웃·새 계정/두 프로필 보존 및 F04 회귀2/2PASS7.7초 |
| F10 | submissions/queue page=Infinity 등 invalid offset, 범위 밖 페이지·늦은 응답으로 잘못된 페이지/목록 | Terra 숫자 안전성·current query 기반 URL replace/재조회·singleflight 수정, Root 느린 polling/중복 새로고침 검토 | 목록3파일25PASS; actual invalid offset0/200·390px page99→1·필터 보존 통과, 전체113/typecheck/buildPASS |
| F11 | Challenges 더 보기 중 검색 변경 후 이전 페이지가 뒤늦게 새 목록/total/error를 덮음 | Terra red 재현, Root request abort+success/error/finally 가드·debounce 시작 즉시 loading | focused3PASS; 실제25문제/보류한실제응답/검색25→1/release뒤1 유지, invalid페이지와 합쳐 browser2/2PASS3.9초 |
| F12 | 서버가 지원하는 두 글자 닉네임 로그인을 화면이 거부하고 긴 이메일은64자로 잘라 전송 | Root API schema/lookup과 비교, UI red2실패→가입용 최소길이와 로그인 조건 분리·입력 자르기 제거 | AuthModal/Header focused12PASS; 실제 가입 계정의2자 닉네임/64자초과 이메일 로그인200·원문payload 확인, profile browser3/3PASS11.5초 |
| T01 | 카드 fixture mock이 query URL을 놓침 | collection/query 정규식 수정, Edge2/2PASS | 상세 API mock 보존, 카드→상세/모바일 확인 |
| T02 | 브라우저 실행기 없음/잘못된 option locator로 terminal UI 미도달 | 공식 Edge runner5/5PASS39.4초 | 실제 운영 Python stdin/stdout/exit0; 새 오류분류 backend 배포 검증과는 구분 |
| T03 | 로컬 대회 fixture 제출이 대기 상태에 머묾 | fakepool/runner_factory·durable clock 수정, 전체 브라우저 1/1 통과(17.9초) | 실제 Docker 채점은 별도 이미지 통합 필요; 이 UI fixture는 fake sandbox |
| T05 | Windows에서 Playwright 시작 전 hang | 서버 로그와 outputDir 분리 후 즉시 실행·통과 | 새 로그/결과 경로 유지, 테스트 정리가 열린 서버 로그를 삭제하지 않아야 함 |
| T04 | Vite dev CSP 실패와 built preview 검증 혼동 | dev4/4·built root/subpath10/10PASS | strict CSP는 preview 전용으로 분리, 공개 suite에서 오실행 방지 |

## 기능/검증 범위

각 행은 정상 흐름뿐 아니라 미인증/타 사용자/관리자 권한, 잘못된 입력·중복/경계, 영속 데이터 및 데스크톱·모바일 화면을 확인한다. 실서버 부하/장애/보안 검증은 기존 승인 범위의 격리 환경에서만 수행한다.

| 기능 | 이번 수정 후 상태 | 필수 확인 |
| --- | --- | --- |
| 홈·메뉴·페이지 이동 | 새 파생 이미지 desktop/390px 9개 route·refresh·메뉴 통과, 보고서 보관 | 공개/보호 route, base path, 좁은 화면; 모든 브라우저/뒤로가기 조합을 증명한 것은 아님 |
| 계정·프로필·권한 | 새 PG/API 가입·3가지 identity 로그인·부분 변경/null·권한 철회 및 F06/F07 실제 UI 회귀 통과 | 가입·로그인·로그아웃·변경·토큰 만료/무효화·권한 철회; 각 근거의 실제/단위 범위를 구분 |
| 비밀번호 재설정 | F01 외부 조건 | 발송 실패·만료·재사용·실제 수신·새 비밀번호·이전 세션 |
| IDE 6언어 실행 | 새 실제 HTTP 6언어/입력/CE/RE, 자원 한도5사례 통과 | 기본 예제·stdin·오류·출력 제한·중단·언어별 저장 |
| B++ 분석 | 새 실제 최적화·진단 API와 v3 AST/SSA 노드·IR/ASM 결과·실행·잘못된 코드 진단 UI 통과 | 모든 최적화/source-range/큰 입력 조합의 실제 UI 전수 증명은 별도 |
| 대화형 터미널 | 새 실제 WS9사례·잘못된 Origin 거부·닫기 취소/자원 정리·재연결 통과 | 언어별 실행·입력·출력·종료·닫기/재연결·권한/제한 |
| 클라우드 프로젝트 | 새 PG/API CRUD·revision 충돌·타 사용자 격리, 실제 독립 두 브라우저 저장 충돌/코드 보존/해결/재로드 통과 | 생성·수정·재로드·삭제·동시 탭 충돌·사용자/문제/대회별 격리 |
| 문제 관리·검색 | 새 PG/API admin CRUD·검색·숨긴 테스트·soft delete 통과 | 작성/편집/삭제·태그·난이도·페이지·비공개/숨겨진 테스트 |
| 채점·큐·제출·점수·랭킹 | 새 실제 연습/내역·랭킹 및 WA/CE/RE/TLE/정답23/중복0 추가6사례 통과 | accepted/WA/CE/RE/TLE·영수증·재요청·중복 점수·필터/페이지 |
| 커뮤니티 | 새 PG/API 자유 CRUD·개수·관리자만 공지 및 실제 UI CRUD/새로고침·공지쓰기 제한 통과 | 공지/자유/문제 탭·CRUD·타 사용자 거부·목록/개수/페이지 |
| 관리자 | 새 PG/API 검색·승격/철회·프로필 null, 실제 문제 editor CRUD/역할변경/selfdemote 제한 UI 통과 | 문제·계정 CRUD·검색·중복 입력·자기 권한 제거 제한 |
| 대회 전체 | 새 실제 생성/공개/참가/접수 재시도/채점500/종료 일반17·공개·숨긴 테스트 통과 | 생성/편집/공개/잠금·참가·시각 경계·비공개·제출·동점/패널티·종료/일반 점수 |
| 공유 실행/분산 경로 | 새 실제 2 API 사용자/영수증 공유, 익명 결과404·다른 payload409·API 하나 중지 중 새 로그인/실행 통과·둘 다 복구 | 2 API에서 로그인·큐·결과 소유권·재시도 일관성, 격리 복구 검증 |

실제 완료 증거와 실패 로그 경로를 행별로 추가한다. 테스트를 약화하거나 mock 성공을 실제 메일·Docker·브라우저 성공으로 치환하지 않는다.

## 1차 수정 증거

- F02: launcher가 요청별 nonce로 compile/run 전환을 알리고, backend가 bounded 스트림에서 제어 프레임을 제거한다. 프로그램 실행 후에는 같은 모양의 출력도 그대로 사용자 출력으로 취급한다. 기존 sandbox 이미지는 호환 fallback이 있으므로 **새 backend와 새 sandbox를 함께 검증/반영해야 한다**.
- 비대화형 실행과 IDE 대화형 터미널 모두 같은 판정 함수를 사용한다. 터미널 PTY의 CRLF·빠른 입력 echo·분할 UTF-8을 보존한다. 출력 제한 계산에서 제어 프레임은 제외한다. 시간 제한은 호스트 deadline, 메모리 제한은 Docker OOMKilled를 근거로 한다.
- 격리 실제 sandbox 17개 사례 통과: 6언어 정상/문법 오류, C/C++/Python/Java/JavaScript 런타임 오류. C의 정상적인 exit124·C++의 exit137도 실행 단계로 구분된다. 추가 PTY 3개(문법 오류/정상/Python 예외) 통과, 제어 프레임 비노출 확인.
- 실제 증거는 기존 배포 sandbox 이미지에 변경된 launcher만 read-only bind한 **프로토콜 검증**이며 새 이미지 전체 빌드·HTTP/WS 통합 성공이라고 주장하지 않는다. 서버 `/home/vulpo/webcompiler-phase-fgCGkjI0/phase-results.json`, `phase-terminal-results.json`. 네트워크 none, 256MiB/no-extra-swap/1CPU/64PID, 케이스별 컨테이너 제거 및 소유 라벨 잔여 0 확인. 운영 DB/서비스는 변경하지 않았다.
- 최초 terminal 확장 직전 전체 backend: 1968 passed,357 skipped,8 subtests/76.67초. terminal 확장 후 focused 34 passed,5 skipped/1.56초. 최종 전체 회귀는 다시 실행해야 한다.
- Luna 동적 Bash 테스트의 초기 전역 /tmp 파일 덮어쓰기 방식은 루트 검토에서 거부했다. 실제 실행 전에 fixture-owned 임시 경로 adapter로 고쳤다. Windows skip은 Bash 미설치가 아니라 POSIX 테스트 전용 조건으로 명시했다.
- 최종 1차 backend 전체: **1986 passed,362 skipped,8 subtests/88.48초**. terminal phase/TLS 수정까지 포함하며 이후 추가 수정은 별도 재검증 대상이다.
- T03 브라우저: `contests.local.spec.ts` 1/1,17.9초. 관리자 생성/참가/6언어 템플릿/정답/코드 저장 재로드/점수판/390px 모바일/종료 후 공개 및 점수/연습 코드 격리까지 통과. 루트가 모바일 스크린샷을 직접 확인했고 헤더/일정/참가/탭 영역의 잘림·겹침이 없었다. `frontend/playwright-report/contests-local/artifacts`와 `frontend/test-results/contest-*.png`.
- T05 원인 근거: Playwright runner는 시작 시 outputDir 전체를 정리한다(`node_modules/playwright/lib/runner/tasks.js`). 기존 outputDir 아래에 실행 중인 fixture/Vite 로그가 열려 있었다. 두 서버 정리 후 같은 명령은 2.21초 만에 첫 API 요청까지 도달했고, outputDir 분리 후 서버를 켠 상태에서도 전체 시나리오가 통과했다. 앞선 pre-request hang은 제품 채점 실패가 아니었다.
- F03: Python 표준 smtplib의 기본 STARTTLS context가 `_create_unverified_context`를 사용함을 확인했다. 명시적인 기본 신뢰 저장소/hostname 검증을 적용하고 인증서 검증 실패 뒤 login/send가 호출되지 않도록 검증했다. 회귀 red 1실패→수정 후 관련8PASS. 실제 SMTP 접속은 수행하지 않았다.
- 프런트 공식 공개 Edge 보고서: `frontend/playwright-report/public-edge/results.json`, 5/5/39.4초. 코드 실행 버튼의 현재 terminal queue 등록→출력→exit0 계약을 검증한다. 로컬 fixture/preview 포트4175/18001/15189/15190 정리 확인. 향후 contest artifact 위치는 Vite 감시 밖 `.deploy/test-results/contests-local/artifacts`로 옮겼으며, 앞선 실제 통과 실행의 기존 경로와 구분한다.
- 최신 전체 회귀: backend **1997 passed,362 skipped,8 subtests/87.66초**(F04/F05 포함), frontend **18파일73테스트 통과**, 타입 검사 통과, `/webcompiler/` production build **15.23초 통과**. Skip은 외부/플랫폼 검증 완료가 아니며 큰 번들 경고는 남아 있다.
- F04 브라우저 `profile.local.spec.ts`: **1/1PASS4.9초**. 메일/닉네임/아바타 입력→부분 PATCH의 생략 필드 보존→UI 전체 삭제→서버 null→캐시 제거 및 재로드 후 빈칸 유지까지 확인. 실제 로컬 API/SQLite 사용. `.deploy/test-results/profile-local/results.json` 및 trace. fixture/Vite 종료와 18001/4175 포트 해제 확인.

## 현재 코드의 격리 실제 연동 검증

- 환경 `/home/vulpo/webcompiler-remediation-f78fGnSm`, project `webcompiler-remediation-f78fgnsm`. 빈 PostgreSQL, 별도 Redis/network/임의 테스트 계정·비밀, API2/worker/proxy/frontend. 운영 데이터는 복제·변경하지 않았다. loopback 18011/15181, 실제 inspect로 memory/no-extra-swap caps 확인. 최종 검증 뒤 소유 리소스를 정리했다.
- 고정 앱 소스 archive SHA256 `de11a79ac6c37107bba9d1bc7c55660de8ba7cf7d5d6232d922eb2d7dccc408e`. backend `1f908f88f62a8e384125b5f0e6706fe2fb0687a6f2a6e7664868e8c867a5a5f2`, sandbox `01abfd32835fd57db8761b401c75a81273867d3dd30e3830b46a25869bd9cfb1`, frontend 초기 `31ee300bd2e8be844e12569ec06d08b0973e65fb5f14498fccb9b8e3683eeae4`.
- 이 이미지는 기존 배포 의존성 레이어에 현재 앱/launcher/로컬 빌드 자산을 COPY한 **파생 런타임 이미지**다. requirements.lock 일치와 삭제된 Python 모듈이 남지 않음을 확인했다. Dockerfile 전체 clean build·이미지 취약점 스캔·CI attestation의 대체물이 아니다. 최초 BuildKit은 Engine-local 이미지 ID를 remote repository로 해석해 실패, 앱 기동 전에 COPY-only 로컬 builder로 변경했다. Compose resource 값 decimal-string 파서도 기동 전에 수정했다.
- `functional-api-results.json`: 계정/프로필/권한, 프로젝트, 커뮤니티, 관리자, 문제, 연습 채점·기록, 대회 전체, B++ 분석, 6언어, 큐·제출·랭킹의 **10개 실제 기능 묶음 통과**. reset 항목의 PASS는 예상된 SMTP503을 재현했다는 뜻이며 메일 기능 통과가 아니다.
- `terminal-results.json`: 6언어 stdout42/exit0, C++ compile_error, Python runtime_error, Python 입력42→GOT:42의 **9사례 통과**. 실제 DB의 execution_phase 및 verdict, 제어 프레임 비노출·lease/operation 정리 확인. `terminal-close-results.json`: 잘못된 Origin403, 실행 중 소켓 닫기→canceled/정리→새 세션 정상 실행 통과.
- `limits-results.json`: 실제 무한루프 TLE/124, 512MiB 할당 OOM/137, 2MiB 출력 제한, C exit124/C++ exit137의 runtime_error 구분 **5사례 통과**. 공개 CodeResponse가 private phase/reason을 제거하는 정상 계약을 처음 테스트가 놓쳐 실패했다. 기대를 공개 verdict와 별도 private DB 근거로 나눠 재검증했다. 최초 일회용 가입 누락 email422도 harness 수정 후 재실행했다.
- `grading-results.json`: WA/CE/RE/TLE는 점수0, 첫 정답23, 재정답0의 **6사례 통과**. 최종 계정 점수와 제출별 내역 합계 일치. 최초 harness가 submission ID와 executionId를 혼동해404였으며, 실제 receipt 계약과 history award 필드로 수정 후 전체 재실행했다.
- `lb-results.json`: 두 API 직접 주소에서 같은 사용자 JWT/같은 요청 ID 영수증/완료 결과 일치, 미소유 조회404와 다른 코드 재요청409. 격리 API2 중지 후 proxy를 통한 로그인·새 실제 실행 정상, 두 API healthy 복구. 초기 harness의 short/full container ID 비교를 full inspect ID로 정규화한 후 수행했으며 그 실패에서는 API를 중지하지 않았다.
- F06/F07 포함 최신 frontend: **19파일80테스트 통과**, 타입 검사 통과, production subpath build5.90초 통과. 격리 frontend만 v2 `1da4538b250974bda0675d3d329d5291216d45ed5df5d1a7752c217000c99125`로 교체했다. 추가 source/assets archive `e027dea4b1b31218da0f2d99a255437207778712a9d36a65ea86a573ab0e87b0`. backend/sandbox는 위 고정 이미지 그대로다. 운영은 변경하지 않았다.
- 비밀을 제외한 runtime caps/이미지 증거와 API/WS/자원/채점/LB JSON을 로컬 `.deploy/remediation-evidence-f78/`에 보관했다. fixture-state.json/운영 자격증명은 가져오지 않았다.
- F06/F07 v2 실제 Edge **4/4PASS42.8초**. F07는 실제 GET body를 유지하고 전달만 지연했다. 응답 finished+double rAF 및 handler 완료를 기다리도록 루트 리뷰 후 강화한 race 단독 재실행 **1/1PASS3.9초**. 전체 보고서는 `.deploy/test-results/remediation-browser/results.full-v2-4pass.json`로 보존했다.
- 실제 community UI **1/1PASS4.8초**: 일반 사용자 로그인, 공지 작성 제한, 자유 글 작성/수정/재조회/삭제. 실제 admin UI **1/1PASS5.8초**: 문제 작성/재조회/수정/삭제, other 계정 프로필 변경 후 관리자 검색 반영, 역할 승격/철회, 자기 권한 제거 disabled. 관리자 화면에는 타인 프로필 편집 컨트롤 자체가 없으며, API 계약 검증과 혼동하지 않는다.
- IDE 최초 UI run은 graph4종/실행 뒤 진단 확인에서 실패: 터미널 탭을 둔 채 출력 콘솔 메시지를 기대한 harness 실수였다. 서버 compile_error는 완료됐고 실제 오류 메시지 탭으로 전환하도록 고쳤다. 같은 run에서 독립 두 브라우저 기기의 실제 저장→409 충돌→local draft 보존→서버 버전 불러오기/재조회는 **1/1PASS6.4초**. 이때 screenshot 직접 검사로 별도 실제 F08을 발견했다.
- v3 frontend archive의 4096-byte SCP 전송이 connection reset으로 중단됐고 tar EOF가 발생했다. 새 v3 경로 일부만 풀렸으며 이미지 갱신 명령은 실행되지 않았다. 기존 v2 서비스 유지, 앞서 성공한 1024-byte 설정으로 재전송하고 checksum 확인 후 다시 진행한다.
- v3 재전송 SHA256 `58a5a02b91e791ac2c0ad22a9d8d5c8170413a758f6ed6fe4bcb099ef967da0c` 양측 일치 확인 뒤 교체 성공. 최종 frontend `8ce1beea36e86983045c03e233bb992563362d1025b2317e2e891b43f4624258`. 실제 IDE **3/3PASS 74.45초**: AST/SSA 실제 노드, IR/ASM 비어 있지 않은 결과, B++ stdout/exit0, 잘못된 코드 진단; F08 panel.scrollLeft=0 및 본문 경계; 독립 두 브라우저 실제 409와 local draft 보존/서버 코드 불러오기/재로드. `.deploy/test-results/ide-remediation/results.json`, `results.f08-red.json`, `artifacts/ide-remediation.local-grap-b63e3-ip-the-whole-analysis-panel/analysis-panel-fixed.png`. Root가 성공 스크린샷의 본문 경계를 직접 확인했다. 탭 띠 자체의 가로 스크롤은 의도된 동작이다.
- 최종 `runtime-evidence.json`과 `cleanup-results.json`은 `.deploy/remediation-evidence-f78/`에 보관. 정리 보고서 containers9/data_volumes2/unsettled_jobs0/builder_removed=true. 독립 Docker selector도 빈 결과, 기존 운영 backend2/worker/frontend/PgBouncer/proxy/Redis 모두 healthy. tunnel session37225는 소유 PID 확인 후 종료, 로컬15181 listener 없음. 일회용 로컬 자격증명 파일 삭제; 테스트 재실행은 새 격리 fixture/계정 생성이 필요하다.

## 남은 조건과 증거 한계

### 계속 점검한 경계 증거

- 직전 goal turn은 F08 실제 검증과 소유 리소스 정리를 마친 **progress**다. SMTP 미응답을 이유로 검사를 중단하지 않고 auth 계정 전환·목록 경쟁·비공개/삭제 경계를 추가 검사했다.
- `test_visibility_boundaries.py` 현재4PASS, 인접9PASS: 예정/진행 비공개 문제가 일반 목록·커뮤니티·counts·내역에 나타나지 않음, 대회 participant/admin 구분, 종료 후 공개와 hidden 비공개. 초기3실패는 삭제 이력까지 숨겨야 한다는 신규 테스트의 잘못된 정책과 global total/filteredTotal 혼동이었다. A05의 기존 soft-delete 이력·점수 보존을 유지하며, 제출 메타데이터에 코드/문제 본문/테스트가 없는지 강화했다. 제품 권한 정책은 바꾸지 않았다.
- F09 실제 브라우저는 별도 일회용 SQLite/API와 Vite를 썼다. 첫 실행은 잘못된 환경 변수 `VITE_API_BASE_URL` 때문에 API에 도달하지 못했다. 실제 `apiBase.ts`의 `VITE_API_URL=http://127.0.0.1:18001`로 수정 후2/2 통과. 실제 탭 간 storage event를 사용했고 응답/서버 프로필을 검증했다. sandbox는 fixture fake이며 이 실행은 언어 채점 증거가 아니다.
- F11 브라우저는 local API로25문제를 생성하고 실제 offset24 응답 전달만 지연했다. 필터 변경 뒤1문제가 유지됐으며 생성 ID들은 finally에서 soft-delete했다. 로컬 테스트 DB 외 데이터 변경 없음. `.deploy/test-results/profile-local/results.json`, `.deploy/test-results/list-boundaries/results.json`에 결과 보관.
- 최종 후속 검증: Node24 `vitest run` **23파일113PASS/3.85초**, `tsc --noEmit` PASS, `VITE_APP_BASE_PATH=/webcompiler/ VITE_API_URL='' vite build --outDir ../.deploy/remediation-frontend-boundaries` **6.25초 PASS**. 새 경로를 사용했으며 기존 산출물을 비우지 않았다. 큰 chunk 경고는 유지한다.
- 마지막 실제 local Edge: `playwright.profile.config.ts` **3/3PASS11.183초**(두 글자 닉네임/긴 메일, 탭 간 계정 변경, 프로필 전체 삭제), `playwright.list-boundaries.config.ts` **3/3PASS4.284초**(invalid page, 390px 범위 밖 페이지/필터 보존/문서 가로 overflow 없음, 실제 응답 보류 검색 경쟁). 계정·문제는 local fixture DB에서만 생성했다. build 산출물과 달리 이 UI 실행은 Vite dev/SQLite임을 명시하며, 운영 이미지/실메일/실채점 증거로 확대하지 않는다.
- Root는 Terra의 순수 요청별 generation이 느린3초 polling을 영원히 폐기할 수 있음을 검토에서 지적했다. 최종 코드는 query generation + same-query singleflight이며6초 대기→응답 수용→다음poll 재개를 검증했다. Submissions 중복 새로고침도 red(3호출)→초기 포함2호출/disabled 회귀. API client는 AbortSignal을 받지 않으므로 두 페이지는 오래된 응답을 무시한다; Challenges는 실제 abort와 응답 가드를 함께 사용한다.
- 로컬 fixture queued/running0 확인 후 소유 PID111512(API)/98788(Vite)만 종료했고18001/4175 listener 없음. 서버 시험 환경은 재생성하지 않았으며 이번 continuation은 운영에 접속/배포/변경하지 않았다. 테스트용 임시 SQLite와 비밀 없는 보고서는 보존했다.

1. **F01 미완료:** 실제 SMTP 서비스·발신 주소·서버 설정 파일 경로와 테스트 수신함이 필요하다. 비밀번호는 채팅에 받지 않는다. 실제 수신→링크→비밀번호 변경→single-use/이전 세션 무효화를 끝내야 메일 기능을 정상 판정할 수 있다. F03의 TLS 단위 회귀도 실제 메일 전달을 대신하지 않는다.
2. **운영 미반영:** 이번 수정은 로컬/격리 이미지에서 검증했다. 배포 승인을 받은 뒤 backend와 sandbox를 함께 반영하고 실제 HTTPS/WSS 회귀를 해야 한다. 기존 운영 healthy는 수정본 운영 검증이 아니다.
3. **검증 수준:** 대회 deadline/동점/패널티/채점 순서 역전, 토큰 만료, 관리자 commit uniqueness 경쟁 등은 회귀 테스트 근거와 실제 통합 happy/error 흐름을 결합한다. 모든 경쟁을 실제 PG 동시 요청으로 재현했다고 주장하지 않는다. 대회 전체 브라우저 흐름은 fake sandbox fixture, 실제 대회 채점은 별도 실제 API/worker에서 검증했다.
4. **외부/확장 범위:** canonical clean image build·CI provenance/security scan, SMTP, 다중 호스트 HA/DB·Redis 장애, 대규모 혼합 봇 부하, 모든 UI 입력·페이지·권한 조합은 이번 기능 검증으로 완료 선언하지 않는다. A01~A25/5.4의 과거 잔여 조건도 이 기록으로 소거하지 않는다. 기존 갭 메모는 검사 전 스냅샷이며, 현재 통과와 여전히 낮은 수준의 증거를 구분해서 읽는다.
