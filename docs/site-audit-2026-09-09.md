# B++ 웹 컴파일러 사이트·아키텍처 점검 보고서

점검일: 2026-09-09 (KST)  
대상: <https://cuha.cju.ac.kr/webcompiler/>  
운영 및 로컬 HEAD: `e5cf76429803a4bad9cb98a01fb999cb85094c06`  
범위: 웹 서비스, 인증·권한, IDE·저장, 실행기, 일반 채점, 콘테스트, 커뮤니티, 데이터베이스, 큐, 배포·복구, 의존성

## 1. 결론

주요 페이지는 열리고 기존 회귀 테스트도 통과한다. 그러나 **서비스에 문제가 없다고 판단할 수는 없다.** 실행 자원 통제, 계정별 초안 분리, 점수 원장, 다중 서버 큐 상태, 비밀번호 재설정에서 보완이 필요하다.

먼저 처리할 항목은 다음과 같다.

1. 웹 터미널까지 포함하는 전체 실행 수·요청량·출력량 제한.
2. 계정을 바꿀 때 다른 사용자의 로컬 코드가 업로드되는 동작 차단.
3. 비밀번호 재설정 메일 설정 및 기존 로그인 세션 무효화.
4. 테스트 없는 문제의 정답 처리와 문제 삭제 시 점수 원장 불일치 수정.
5. 큐 조회가 다른 서버의 실행 중 기록을 실패로 바꾸는 동작 제거.
6. 컨테이너 재시작 정책, 의존성 상태 확인, 백업·복구 절차 마련.

Redis는 도움이 되지만 이 문제들을 한꺼번에 해결하지는 않는다. **PostgreSQL을 제출·점수의 기준 데이터로 유지하고, Redis는 공통 요청 제한과 공개 결과 캐시부터 적용**하는 것이 현재 규모에 적합하다. 실행 작업자는 API 프로세스에서 분리하는 편이 우선이다.

추가 확정 목표: **선행 결함을 수정한 뒤, 복수 API 인스턴스가 실제 운영 요청을 분산 처리하는 로드밸런싱까지 구현한다.** 단순히 blue/green 컨테이너 두 개를 실행하거나 배포 대상을 전환하는 것으로 완료 처리하지 않는다. 아직 구현·배포된 상태가 아니며 구체적인 구성과 검증 기준은 5.4절에 정리했다.

이번 작업에서는 조사용 문서·스크립트만 작성했다. 제품 코드 수정, 운영 계정·대회·제출 생성, 비밀번호 변경, 배포, main 푸시는 하지 않았다.

## 2. 조사 방법과 판정 기준

| 표기 | 의미 |
|---|---|
| 운영 확인 | 현재 HTTP 응답, 브라우저 화면, SSH 설정 또는 읽기 전용 DB 집계로 확인 |
| 격리 재현 | 운영과 같은 Git 커밋을 별도 디렉터리에 추출하고 새 SQLite 또는 브라우저 응답 대역으로 재현 |
| 소스 확인 | 해당 분기·설정이 코드에 존재함. 실제 장애·공격 발생을 뜻하지 않음 |
| 추가 검증 | 위험 조건은 있으나 동시성·부하·외부 설정 등의 확인이 더 필요 |

P1은 데이터·계정·실행 서비스의 신뢰성 때문에 우선 수정할 항목, P2는 다음 안정화 묶음, P3는 품질·운영 편의 개선이다. CVSS 등급이나 실제 침해 판정이 아니다. P0에 해당하는 현재 서비스 전체 중단이나 확인된 침해는 발견하지 못했다.

운영에서는 부하·파괴·경계값 공격을 하지 않았다. 큐 조회 API는 기록을 수정하는 부작용을 발견해 운영 브라우저에서 차단했다. 브라우저의 쓰기 요청도 차단했다. 권한·점수 변경 재현은 새 임시 DB에서만 수행했다. 운영 DB 조사에는 `SET TRANSACTION READ ONLY`를 사용했고 개인별 코드·이메일·비밀값은 보고서에 수집하지 않았다.

아래 코드 위치는 별도 표시가 없으면 위 운영 커밋 기준이다. 로컬 미커밋 파일은 줄 번호가 다를 수 있다.

## 3. 실제 운영 구조와 규모

| 구성 | 확인 결과 | 해석 |
|---|---|---|
| 웹 | React·Vite 정적 파일, Nginx 프록시 | 홈 HTTP 200, 배포 workflow 성공 |
| API | FastAPI, blue/green backend 둘 다 실행 중 | 각 프로세스에서 대회 작업자·종료 작업이 시작됨 |
| DB | 공유 PostgreSQL, `webcompiler-postgres` 직접 연결 | 운영 PgBouncer 연결 아님 |
| Redis | 두 backend의 `REDIS_URL` 미설정 | 설치된 Python redis 패키지나 로컬 코드 존재와 실제 사용은 다름 |
| 실행 | Docker 소켓을 가진 API가 실행 컨테이너 생성 | 일반 실행·채점 큐와 웹 터미널 경로가 다름 |
| 실행 격리 | 네트워크 차단, 읽기 전용 루트, capability 제거, no-new-privileges, 메모리 256MB·CPU·PID 제한 | 기본 방어는 존재. 총 실행 수·출력량 제한과는 별개 |
| API/프런트 컨테이너 | restart `no`, healthcheck 없음, 메모리·PID 상한 없음 | 프로세스 종료·호스트 재시작 복구 보장 부족 |
| 로그 | `json-file`, 회전 옵션 없음 | 장기 운영·많은 출력에서 디스크 증가 위험 |
| 메일 | SMTP host/from 없음, reset URL은 설정 | 운영 비밀번호 찾기 기능을 완료할 수 없음 |
| 백업 | 관련 systemd timer 없음, 사용자 crontab 조회 불가 | 루트·외부 백업 존재 여부는 미확인 |

읽기 전용 DB 집계는 사용자 9명, 문제 26개(시스템 게시판 포함), 일반 제출 24개, 대회 제출 12개, 저장 프로젝트 1개, 커뮤니티 글 3개였다. 익명 일반 제출은 1개, 미완료 대회 제출은 0개였다. **현재 `total_score`와 해결 원장 합계가 다른 사용자는 0명**이다. 아래 점수 결함은 격리 재현 결과이며 운영 데이터가 이미 손상됐다는 뜻이 아니다.

한 차례 유휴 자원 표본에서 backend 각각 약 77/80MiB, CPU 약 0.5%였다. 이 수치로 동시 참가자 수나 대회 수용량을 추정할 수는 없다. 공유 DB 외에 예전 색상별 PostgreSQL 두 개도 살아 있다. 활성 연결 대상을 확인한 뒤 보존·복구 목적을 확인해야 하며 임의로 삭제하면 안 된다.

## 4. 우선순위별 발견 사항

| ID | 우선순위 | 항목 | 근거 수준 |
|---|---|---|---|
| A01 | P1 | 웹 터미널이 공유 실행 제한을 우회하고 연결·입출력 상한이 부족함 | 소스·운영 설정 |
| A02 | P1 | 계정 전환 시 이전 로컬 초안을 다른 계정으로 업로드 | 브라우저 격리 재현 |
| A03 | P1 | 비밀번호 재설정 뒤 기존 JWT 유효, 운영 메일 미설정 | 격리 재현·운영 설정 |
| A04 | P1 | 테스트 0개 문제를 잘못된 코드로 풀어도 점수 지급 | 격리 재현 |
| A05 | P1 | 문제 삭제 뒤 총점만 남고 해결 원장이 사라짐 | 격리 재현 |
| A06 | P1 | 큐 조회가 다른 프로세스의 실행 기록을 실패 처리 | 격리 재현·두 backend 실행 확인 |
| A07 | P1 | 실행 출력·Docker 로그 크기 무제한 | 소스·운영 설정, 부하 미실시 |
| A08 | P1 | 웹 API에 Docker 제어권과 프로젝트 전체 쓰기 마운트 | 운영 설정, 침해 재현 아님 |
| A09 | P1 | 재시작·의존성 readiness·복구 검증 부족 | 운영 설정·소스 |
| A10 | P2 | 일반 제출이 긴 HTTP 요청에 묶이고 접수 원장이 늦게 저장됨 | 소스 |
| A11 | P2 | 대회 점수판이 매번 제출 코드까지 전량 로드 | 소스, 부하 미실시 |
| A12 | P2 | 미배포 Redis 큐에도 대기열 정체·카운터 경쟁 위험 | 로컬 미커밋 소스, 별도 구분 |
| A13 | P2 | 초안 자동저장 손실·충돌·시각 처리 개선 필요 | 소스, 일부 추가 검증 |
| A14 | P2 | 모바일 IDE 패널과 문제 목록 가독성 부족 | 운영 화면 시각 검수 |
| A15 | P2 | 잠깐의 인증 조회 실패도 로그아웃 처리 | 브라우저 격리 재현 |
| A16 | P2 | 요청 제한·관리 작업 감사·경쟁 요청 처리 보강 | 소스 |
| A17 | P2 | 취약 의존성 경고와 재현 가능한 빌드 관리 필요 | npm audit·소스 |
| A18 | P2 | CI가 검사한 SHA와 서버가 가져오는 브랜치가 다를 수 있음 | 소스, 실제 오배포 확인 아님 |
| A19 | P2 | 백업 및 재해 복구 증거 부족 | 저장소·운영 일부 확인 |
| A20 | P2 | 보호 응답 헤더·같은 origin의 신뢰 경계 보강 | 운영 HTTP·소스 |
| A21 | P3 | 일반 제출 보관 수 한 개 초과, 익명 제출 무기한 증가 | 격리 재현·소스 |
| A22 | P3 | Docker 연결 실패 시 임시 코드 디렉터리 잔존 | 격리 재현 |
| A23 | P3 | 페이지 분할·코드 분할·외부 리소스 의존 개선 | 빌드·브라우저·소스 |
| A24 | P3 | 안내·관리 진입·접근성 및 정책 명확화 | 화면·소스 |
| A25 | P2 | 실제 요청 로드밸런싱 미구성: 단일 활성 backend로 전달 | 운영 프록시 설정, 최종 구현 목표로 추가 |

### A01·A07·A08. 공개 실행 서비스의 자원·권한 경계

`backend/app/api/routes/terminal.py:22,45`에서 WebSocket을 바로 수락하고 시작 메시지를 기다린다. Origin 검증, 연결 수 제한, 초기 메시지 제한시간, 코드 바이트 검증, 컴파일 큐 예약이 없다. 이후 컨테이너를 직접 생성한다. 익명 실행 자체는 제품 요구사항이므로 로그인 강제만으로 해결할 사안은 아니다.

HTTP compile/run도 익명 실행을 허용하며, `models/schemas.py:26,52`의 코드·stdin 필드에는 제출 API와 같은 바이트 상한이 없다. 애플리케이션 외부 프록시 기본 한계가 일부 있을 수 있으나 계정/IP/전체 실행 예산을 대신하지 않는다.

`services/compiler.py:295` 부근은 stdout/stderr 로그 전체를 메모리로 읽는다. 터미널은 출력 수신을 계속 누적한다. 컨테이너 메모리 256MB 제한이 Docker 호스트 로그나 API·브라우저 메모리까지 제한하지는 않는다. 무한 출력·다중 연결을 운영에서 시험하지 않았다.

권장 조치:

- 컴파일·일반 실행·일반 채점·대회 채점·터미널 모두 같은 전역 실행 슬롯을 예약한다. 대회와 익명 연습의 대기열도 분리해 굶주림을 방지한다.
- 코드/입력 바이트, 출력 바이트, 총 대기열 길이, IP·사용자별 실행 빈도, 연결당 시작/유휴/최대 시간을 명시한다. 거부 시 413/429와 재시도 안내를 제공한다.
- 출력은 잘라서 읽는 것만이 아니라 상한 초과 시 실행을 종료하고 `output_limit_exceeded`처럼 명확히 분류한다. Docker 로그 회전도 함께 적용한다.
- 공개 API에서 Docker 소켓을 제거하고 별도 작업자만 제어하도록 한다. 프로젝트 전체 대신 실행용 임시 디렉터리만 마운트한다. 가능하면 채점 호스트를 서비스 DB·API와 분리한다.

현재 실행 이미지에는 `sandboxuser`가 지정되어 있고 소스는 읽기 전용 마운트다. 제출 코드가 곧바로 호스트 명령으로 실행된다는 증거는 없다. 다만 Docker 제어권을 탈취한 웹 프로세스의 피해 범위는 크다. [Docker 보안 문서](https://docs.docker.com/engine/security/), [OWASP WebSocket 지침](https://cheatsheetseries.owasp.org/cheatsheets/WebSocket_Security_Cheat_Sheet.html), [Docker 로그 관리](https://docs.docker.com/engine/logging/configure/).

수용 기준: 격리 부하 환경에서 HTTP+WebSocket 혼합 요청에도 설정한 전체 슬롯을 넘지 않고, 제한 초과 출력이 API/호스트 디스크를 계속 늘리지 않아야 한다. 작업자 강제 종료 뒤 남은 컨테이너·임시 파일도 회수되어야 한다.

### A02·A13·A15. 코드 저장과 로그인 상태

`frontend/src/app/store/compilerStore.ts:132`의 로컬 키는 `b-compiler-editor-code:<scope>`이다. 사용자 ID가 없다. `components/CodeEditor.tsx:186–227`은 로컬 초안이 더 최신이면 현재 로그인 계정으로 업로드한다. 브라우저에서 A의 로컬 초안과 B의 서버 초안 응답을 준비하자 **B 프로젝트를 A 코드로 덮는 PUT 시도**가 발생했다. 모든 API 요청을 가로챘으므로 운영 저장은 0건이다. B의 서버 초안이 없는 경우에도 A 코드가 화면에 나타나는 계정 간 경계 문제는 남는다.

조치: 저장 키를 `userId/scope`와 `anonymous/scope`로 분리한다. 로그인 시 익명 초안을 가져올지 묻고 자동 병합하지 않는다. 로그아웃 시 사용자 메모리·편집 모델을 분리하고, 기존 키 이관은 사용자 확인을 거친다. 서버의 사용자별 소유권 검사는 이미 존재하므로 이를 유지한다.

추가로 자동저장은 2초 debounce 후 실행되며 effect 정리 시 타이머를 취소한다(`CodeEditor.tsx:255`). 빠른 이동·종료 때 마지막 편집을 보존하는 경로를 보강해야 한다. 서버에는 revision/If-Match가 없으므로 여러 탭의 늦은 저장이 최신 코드를 덮을 수 있다. `CodeProject.updated_at`은 timezone 없는 DB 컬럼이고 프런트는 `Date.parse`로 비교한다. UTC를 `Z` 포함 형식으로 통일하고 타임스탬프 대신 서버 revision 기반 충돌 검사를 권장한다. 대회 API의 명시적 UTC 직렬화와 일반 프로젝트 API를 혼동하지 않아야 한다.

`Header.tsx:64–78`은 `/auth/me`의 모든 오류에서 토큰을 지운다. 503만 돌려주는 브라우저 대역에서도 토큰이 제거됐다. 401/403과 네트워크/5xx를 구분하고 후자는 재시도·연결 상태로 처리한다.

수용 기준: A→로그아웃→B 로그인 및 여러 탭에서 코드가 섞이지 않고, 저장 충돌을 사용자에게 알리며, 일시적인 503이 세션을 지우지 않아야 한다. 마지막 키 입력 직후 경로 이동·창 닫기 테스트도 추가한다.

### A03·A16. 인증과 관리자 작업

`api/routes/auth.py:241`은 비밀번호와 재설정 토큰만 갱신한다. `get_current_user:116`은 JWT 서명·만료·사용자 존재만 확인한다. 새 비밀번호로 변경한 뒤 이전 토큰으로 `/auth/me`를 호출해도 200이었다. 비밀번호를 잊은 경우뿐 아니라 세션 탈취 대응에서도 중요하다. 사용자 `auth_version` 또는 `password_changed_at`을 검증하고 비밀번호 변경 시 기존 세션을 폐기해야 한다. [OWASP 비밀번호 재설정 지침](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html).

운영에는 SMTP host/from이 없어 재설정 요청 코드가 503을 반환하는 구성이다. 메일 계정·발신 도메인·재설정 URL을 설정한 뒤 전용 테스트 계정으로 수신 및 1회 사용을 검증해야 한다. 이번 감사에서는 메일을 보내지 않았다.

토큰은 난수 생성 후 해시로 저장하고 만료시간도 있으나, 사용 여부 조회 후 갱신에 잠금/CAS가 없어 동시 확인 요청의 단일 사용 보장은 추가 검증이 필요하다. 원자적으로 미사용→사용 전환하고 비밀번호 변경을 같은 트랜잭션에서 완료한다.

인증 제한 키는 IP+identity다(`auth.py:25`). identity를 바꾸는 시도를 묶는 총 IP 예산은 없고 운영 제한 상태는 프로세스별이다. 프록시 뒤 실제 IP 전달·신뢰 설정도 검증해야 한다. IP 단독 제한만 두면 학교 NAT 사용자가 함께 차단될 수 있으므로 계정·IP·전역 제한을 조합한다. 회원가입·이메일/닉네임 변경의 check-then-insert/update는 유일 제약 충돌을 500이 아닌 409 등으로 처리한다. 관리자 권한 변경·문제 삭제·대회 편집에는 누가 무엇을 바꿨는지 감사 로그를 남긴다.

### A04·A05·A21. 일반 문제와 점수 원장

격리된 운영 커밋에서 다음 결과를 확인했다.

| 입력/행동 | 실제 결과 | 기대 결과 |
|---|---|---|
| 관리자가 sample/hidden 모두 빈 문제 생성 | 200 | 공개 가능한 문제는 유효 테스트 필수 |
| 해당 문제에 `not valid code` 제출 | Accepted, 100점, 실행기 호출 0회 | 무효 문제 거부, 점수 없음 |
| 문제 삭제 | 총점 100, 해결 원장 합계 0 | 정책에 맞는 일관된 기록 |
| 보관 상한을 2로 설정 후 반복 제출 | 3행 보관 | 정의된 상한과 실제 개수 일치 |

근거: `models/schemas.py:218`의 빈 테스트 허용, `api/routes/problems.py:499`의 0/0 통과 계산, `delete_problem:285`의 원장 삭제, `_prune_old_submissions:26` 및 새 제출 flush 전 정리 호출.

점수 정책은 먼저 선택해야 한다. 권장은 문제를 논리 삭제하고 이미 얻은 점수와 감사 원장을 유지하는 것이다. 점수를 취소해야 한다면 삭제와 함께 원장·총점·레이팅을 한 트랜잭션에서 조정하고 취소 사유를 남긴다. 임의 총점 수정이나 원장 없는 보정은 피한다.

일반 익명 제출은 사용자별 보관 정리가 적용되지 않는다. 별도 기간·전역 용량·개인정보 보관 정책을 정하고 대회 제출 원장과 구분한다. 이미 대회 제출은 별도 테이블로 일반 보관 제한에서 보호된다.

### A06·A10·A11. 큐, 채점, 점수판

배포 코드의 `CompileQueue.snapshot()`은 해당 프로세스가 모르는 queued/running 행을 재시작 중단으로 판정한다(`services/compile_queue.py:173,396`). 같은 DB를 쓰는 큐 A에 실행 중 작업을 놓고 큐 B가 조회하자, 작업은 계속 실행 중인데 DB 상태가 `running → failed`로 바뀌었다. 운영에는 두 backend가 살아 있고 양쪽에서 대회 작업자가 실행되므로 이 조건이 현실적이다. **점수 중복이나 실제 작업 취소를 재현한 것은 아니며, 상태 기록 오판을 확인한 것이다.**

GET은 읽기 전용으로 만들고, 복구는 작업자 ID·lease·heartbeat에 근거한 별도 작업으로 수행한다. 프로세스별 concurrency=2는 서비스 전체 2개를 뜻하지 않는다. B++ 분석도 내부적으로 여러 dump 실행을 병렬 호출한다.

일반 문제 제출은 테스트를 모두 실행한 뒤 `Submission`을 저장한다(`problems.py:499–636`). 긴 요청·연결 단절·API 재시작에 취약하고 코드/접수 시각/재시도 ID를 채점 전에 보존하지 않는다. DB 세션도 실행 대기 전 조회 후 오래 유지된다. 대회에 이미 구현된 접수 저장→ID 반환→lease 기반 작업→결과 저장을 일반 제출에도 적용한다. 프록시 timeout만 늘리는 것은 근본 해결이 아니다. 검사한 저장소 HTTP 프록시에는 장기 일반 채점을 위한 명시적 read timeout이 없고 WebSocket에만 3600초가 있다. 운영 전체 프록시 체인의 최종 제한은 추가 확인해야 한다.

대회 점수판은 `services/contests.py:82`에서 소스 코드까지 포함한 모든 제출 ORM 행을 읽고 매번 계산한다. 5초마다 방문자마다 반복된다. 소스 코드를 응답으로 노출하는 결함은 아니지만 DB 전송·메모리 비용이 불필요하다. 필요한 열만 조회하고 `(contest, user, problem)` 결과 요약을 계산한 뒤 공개 점수판을 revision 기반으로 캐시한다. 늦게 완료된 이전 제출이 들어오면 **접수 순서 기준으로 재계산**해야 한다.

대회 작업자·종료 루프는 API lifespan의 asyncio task이며 동기 SQLAlchemy 작업을 직접 수행한다. 작업자 분리와 짧은 DB 트랜잭션이 우선이다. 종료·재처리의 유일키와 lease token 검증은 유지한다.

### A09·A18·A19. 배포·운영 복구

- 현재 API/프런트 컨테이너의 restart 정책은 `no`다. 적절한 재시작 정책과 명시적 운영 중지 절차를 마련한다. blue/green 비활성 색상을 무조건 자동 재시작시키기보다 트래픽·작업자 drain 상태를 구분해야 한다. [Docker 재시작 정책](https://docs.docker.com/engine/containers/start-containers-automatically/).
- `/health`는 고정 JSON을 반환한다(`backend/app/main.py:52`). 프로세스 liveness와 DB/작업자/실행기 readiness를 분리한다. 실제 실행 점검은 무해한 짧은 코드로 제한된 주기·예산에서 수행하고 외부 요청마다 Docker를 생성하지 않는다.
- 배포 workflow는 CI head SHA를 checkout하지만 서버 동기화는 `DEPLOY_BRANCH`의 최신 FETCH_HEAD를 사용한다(`.github/workflows/deploy-webcompiler.yml`, `scripts/sync_remote_repo.sh:24`). 빠른 연속 push에서 검사 SHA와 배포 SHA가 달라질 수 있다. 검증된 SHA 또는 이미지 digest를 끝까지 전달하고 `/version`에 표시한다.
- workflow가 접속 직전에 `ssh-keyscan` 결과를 그대로 신뢰한다. 서버 지문을 별도 검증 후 고정해야 한다. 이번 로컬 SSH 점검은 기존 known_hosts와 StrictHostKeyChecking을 유지했다.
- `deploy_server.sh`의 pg_dump는 초기 색상 DB를 공유 DB로 옮기는 절차이며 정기 백업 근거가 아니다. 외부 백업이 있을 수 있으므로 담당자·위치·보관 주기·최근 복원 결과를 확인해야 한다.
- 백업은 DB뿐 아니라 이미지 digest, 문제/테스트 스냅샷, 설정 및 암호화된 비밀 복구 절차를 포함한다. 별도 환경에서 실제 복원해 제출 수·점수 원장·대회 상태를 대조한다. RPO/RTO는 운영자와 합의해야 하며 현재 달성값은 측정하지 않았다.
- 스키마 변경은 API import 중 수행된다. 전용 마이그레이션 단계와 expand/contract 절차로 옮기고 구버전/신버전 동시 실행 중 호환성을 검사한다. rollback은 이미지 교체만으로 DB 스키마까지 되돌리는 행위가 아니다.

### A14·A23·A24. 화면·성능·안내

390px IDE에서 오른쪽 그래프가 약 90px 폭으로 남아 글자와 탭이 잘리고 콘솔 조작 버튼이 세로로 접힌다. 문서 가로 overflow가 없다는 자동 검사 결과만으로 사용성이 정상이라고 볼 수 없다. 모바일에서는 코드/실행 결과/그래프를 탭 또는 전체 화면 패널로 전환하는 편이 낫다. 문제 목록도 고정 폭 열 때문에 제목을 보기 위해 가로 이동해야 한다. 모바일 카드나 우선 열 표시가 적합하다.

홈과 콘테스트 카드의 기본 배치는 양호하다. 익명 사용자가 대회 생성·편집 URL에 직접 들어가면 권한 API는 차단하지만 화면에 영문 `Not authenticated`만 남는다. 로그인 안내와 돌아가기 동선을 제공한다. 재설정 토큰 없는 `/reset-password`는 로그인 모달로 열리고 배경에 준비 중 문구가 남아 목적이 모호하다.

로컬 빌드의 메인 JS는 약 1,644kB, gzip 약 485kB다. 라우트를 정적으로 import해 IDE·그래프·관리 기능의 의존성이 초기 번들에 묶인다. route lazy loading 및 그래프/수식 모듈 분리를 권장한다. 운영 브라우저에서 jsDelivr(Monaco)와 DiceBear(아바타) 요청이 관찰됐다. 에디터 자산 자체 호스팅과 아바타 대체 표시를 검토한다. 이는 코드가 외부로 전송됐다는 증거가 아니다.

문제/대회 목록의 전량 조회, 리더보드의 전체 사용자 Python 정렬, 커뮤니티 댓글 수의 행 전체 조회도 데이터 증가 후 병목 후보다. 서버 pagination·집계 SQL·필요 열만 조회를 먼저 적용하고 실행계획으로 확인한다. 지금 데이터가 작으므로 대규모 샤딩·검색 클러스터 도입 근거는 없다.

추가 UX 검증: 키보드만으로 패널·모달 이동, focus 복귀, 아이콘 버튼 접근 가능한 이름, 200% 확대, 스크린리더, iOS 실제 브라우저. 이번 기본 화면 검사를 접근성 인증으로 해석하면 안 된다.

### A17·A20. 의존성과 브라우저 보안

2026-09-09 lockfile 기준 `npm audit --json` 결과는 영향 패키지 13개(critical 2, high 6, moderate 4, low 1)다. `--omit=dev`는 3개(DOMPurify·Monaco moderate, React Router high)다. 이것은 13개의 독립적으로 악용 가능한 운영 취약점이라는 뜻이 아니다.

Vitest 경고는 UI 서버 노출 조건, React Router의 일부 경고는 SSR/RSC 등 사용 모드가 중요하다. 현재 프런트는 정적 SPA이며 운영 Nginx가 Vite/Vitest 개발 서버는 아니다. 직접·간접 패키지와 실제 사용 경로를 구분해 업데이트하고 회귀 테스트한다. `npm audit fix --force`는 실행하지 않았다. [Vitest 유지관리자 권고](https://github.com/vitest-dev/vitest/security/advisories/GHSA-5xrq-8626-4rwp), [React Router 유지관리자 권고](https://github.com/remix-run/react-router/security/advisories/GHSA-49rj-9fvp-4h2h).

백엔드 requirements는 대부분 버전이 고정되어 있지 않다. 운영 패키지 버전은 읽어 확인했지만 전체 Python/OS/컨테이너 CVE 스캔은 실시하지 않았다. 잠금 파일, 이미지 digest, SBOM과 CI 의존성 검사를 추가해 같은 커밋의 재빌드가 다른 결과가 되는 일을 줄인다.

홈 HTTP 응답에서 CSP, HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy가 확인되지 않았다. CSP는 Monaco worker·외부 이미지·스타일을 고려해 Report-Only부터 검증한다. HSTS는 같은 호스트의 다른 서비스와 함께 결정하며 곧바로 includeSubDomains/preload를 켜지 않는다.

인증 토큰은 localStorage에 있다. `/webcompiler/`와 같은 호스트의 다른 경로는 서로 다른 보안 origin이 아니다. HttpOnly·Secure 쿠키 전환 시 CSRF 방어도 함께 설계하거나 전용 origin 분리를 검토한다. 커뮤니티 Markdown은 점검한 렌더러에서 raw HTML 플러그인을 사용하지 않지만 모든 저장형 XSS가 없다고 보증하지는 않는다. [OWASP HTML5 저장소 지침](https://cheatsheetseries.owasp.org/cheatsheets/HTML5_Security_Cheat_Sheet.html), [보호 응답 헤더 지침](https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Headers_Cheat_Sheet.html).

### A22. Docker 초기화 실패 때 임시 파일

`services/compiler.py:248–260`에서 임시 소스 디렉터리를 만든 뒤 `_get_client()`를 호출하고, 그 뒤에 정리용 try/finally가 시작된다. Docker 연결 실패를 모의하자 `job-*` 디렉터리가 하나 남았다. 클라이언트 초기화·파일 작성부터 정리 범위에 포함하고 실패 경로마다 소스·stdin을 지우는지 검사한다. 운영에서 Docker를 중지하지 않았다.

## 5. Redis 및 권장 아키텍처

### 5.1 현재 로컬 Redis 변경은 그대로 배포하지 말 것

로컬에는 DB pool, Redis rate limit, 분산 compile queue, Redis/PgBouncer compose, nginx/deploy 수정이 미커밋 상태로 존재한다. **운영에 적용된 변경이 아니다.** 이번 감사에서는 보존했다.

`backend/app/services/compile_queue.py` 로컬 변경은 pending 리스트의 맨 앞 ID를 그 요청의 프로세스가 시작하는 방식이다(`_redis_try_start_job:540`). heartbeat는 active에만 있다. pending 소유 프로세스가 죽으면 맨 앞 ID를 실행할 요청이 사라져 뒤 작업이 기다릴 위험이 있다. 복구 함수는 active만 검사한다(`646`). 또한 active set 크기를 별도 GET/SET 흐름으로 카운터에 반영하므로 원자적 claim/release와 경쟁할 수 있다(`675`). 실제 Redis crash 테스트는 하지 않았지만 배포 전 반드시 확인해야 하는 분기다.

### 5.2 단계별 권장안

| 역할 | 권장 저장/실행 위치 | 이유와 주의점 |
|---|---|---|
| 사용자·문제·대회·제출 코드·최종 판정·점수 원장 | PostgreSQL | 유일키·트랜잭션·감사·재계산 기준. Redis 캐시로 대체 금지 |
| 접수 | API에서 유효성·권한 검사 후 DB commit, 제출 ID 반환 | 요청 연결과 채점 수명을 분리 |
| 채점 | 별도 worker 프로세스/호스트 | API event loop·재배포와 실행 수명 분리 |
| 작업 예약 | 우선 PostgreSQL lease/CAS, 필요 시 SKIP LOCKED | 이미 있는 대회 구조 재사용. 짧은 예약 트랜잭션 뒤 잠금을 풀고 실행 |
| 공통 요청 제한 | Redis의 원자적 카운터/Lua | IP·계정·전역 제한 공유. Redis 장애 시 고비용 실행은 보수적으로 제한 |
| 공개 점수판·리더보드 | Redis 짧은 TTL+revision, DB에서 재생성 가능 | 비공개 문제·타인 코드가 캐시에 섞이지 않도록 분리 |
| 상태 알림 | 초기에는 조정된 polling, 이후 SSE | 알림 유실 시 DB 조회로 회복. WebSocket은 터미널 입력에 유지 |
| DB 연결 수 | 우선 짧은 transaction+명시적 pool, 필요 시 PgBouncer | pooler는 느린 쿼리·긴 transaction을 해결하지 않음 |

PostgreSQL의 `SKIP LOCKED`는 큐 형태의 다중 소비자 잠금 경합을 줄이는 용도로 적합하지만 일반 조회의 일관성을 대신하는 기능은 아니다. 현재 규모에서는 새 메시지 브로커 없이도 worker 분리와 내구성을 개선할 수 있다. [PostgreSQL 16 SELECT 문서](https://www.postgresql.org/docs/16/sql-select.html).

Redis Streams를 도입한다면 DB 제출·outbox를 같은 트랜잭션에 저장하고 relay가 ID만 전달하도록 한다. worker는 소비자 그룹에서 가져와 DB 결과를 멱등 commit한 뒤 ACK한다. 미확인 작업은 재할당하고 재시도 상한 초과는 별도 실패 상태에 둔다. 전달과 ACK 사이의 장애 때문에 중복 처리를 전제로 해야 하며, 점수는 DB 유일키로 한 번만 반영한다. 단순 Pub/Sub를 제출 보관소로 사용하지 않는다. [Redis Streams](https://redis.io/docs/latest/develop/data-types/streams/), [XAUTOCLAIM](https://redis.io/docs/latest/commands/xautoclaim/).

캐시 Redis와 작업/lease Redis는 만료·퇴출 요구가 다르다. 캐시는 지워도 되지만 작업 키가 메모리 압박으로 사라지면 안 된다. 별도 인스턴스 또는 명확한 noeviction/용량 정책을 사용하고 Redis를 인터넷에 공개하지 않는다. AOF/RDB와 복구 절차를 정하되, AOF 설정에 따라 최근 쓰기 손실 구간이 남을 수 있으므로 제출의 원본은 DB에 둔다. [Redis 지속성](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/), [키 퇴출 정책](https://redis.io/docs/latest/develop/reference/eviction/).

PgBouncer transaction pooling은 세션 기능과 호환성 제약이 있다. LISTEN이나 session-level advisory lock을 사용한다면 전용 연결이 필요하다. API·worker·blue/green 각각의 pool 상한 합계를 DB 최대 연결 수와 맞추고 관리자·마이그레이션용 여유를 남긴다. [PgBouncer 기능표](https://www.pgbouncer.org/features.html).

### 5.3 현재 도입하지 않아도 되는 것

Kubernetes, Kafka, DB 샤딩, 복잡한 마이크로서비스 전환은 현재 관측한 규모만으로 정당화되지 않는다. 우선 모듈 경계가 있는 하나의 API 서비스(복수 인스턴스로 실행), 별도 worker, PostgreSQL, Redis로 운영 복잡도를 제한한다. 여러 장비의 자동 복구가 실제 요구가 되면 그때 오케스트레이션을 검토한다. Redis 한 대를 추가하는 것 자체는 고가용성 구성이 아니다. 로드밸런싱 자체는 선택 사항이 아니라 아래 최종 구현 범위에 포함한다.

채점 이미지 digest·컴파일러 버전·실행 옵션도 제출/대회 실행 프로필에 기록해야 한다. 문제·테스트 스냅샷만 고정하고 실행 이미지가 바뀌면 재채점 결과가 달라질 수 있다. 실행 결과 캐시를 넣을 경우 소스뿐 아니라 언어·컴파일러 digest·옵션·테스트 버전까지 키에 포함해야 하며, 비신뢰 실행물 재사용은 별도 격리 검토 후 도입한다.

### 5.4 최종 목표: 실제 요청 로드밸런싱

현재 운영의 `.deploy/active-color`는 green이며, 읽어 확인한 frontend/backend edge 설정은 API·터미널 요청을 모두 `127.0.0.1:18002`로 전달한다. 프런트는 `15175`로 전달한다. 즉 blue/green은 배포 전환 구조이고 현재 요청을 둘에 분산하는 구조가 아니다. A25는 이 차이를 별도 추적하기 위한 항목이다.

최종 구성 요건:

- Nginx upstream에 실제 서비스 중인 API 인스턴스를 최소 2개 등록한다. 초기에는 round-robin 또는 least-connections를 선택하고 부하 결과에 따라 조정한다. 알고리즘 이름만 넣고 대상 서버가 하나이면 완료가 아니다. [Nginx 로드밸런싱 문서](https://nginx.org/en/docs/http/load_balancing.html).
- API 인스턴스는 같은 제출 원장·인증 정책·요청 제한 상태를 사용한다. 어느 인스턴스에 요청이 도착해도 조회·권한·점수가 같아야 한다. sticky session으로 프로세스별 큐 결함을 가리지 않는다.
- HTTP 트래픽 분산과 채점 작업 분배를 분리한다. Nginx는 요청을 나누고, 공유 큐/lease와 worker는 실행을 분담한다. 전체 실행 슬롯과 대기열 상한은 API/worker 개수가 늘어도 같은 정책으로 유지한다.
- WebSocket은 연결을 맺을 때 대상을 선택하고 기존 연결은 해당 인스턴스에서 처리한다. Upgrade 전달, 유휴·최대 시간, ping 및 연결 종료 처리를 검증한다. 연결이 끊겼을 때 다른 인스턴스로 기존 터미널 프로세스가 자동 이전된다고 가정하지 않는다. 재연결 시 종료/복원 가능 여부를 안내하고 새 실행은 사용자 확인 없이 중복 생성하지 않는다. [Nginx WebSocket 문서](https://nginx.org/en/docs/http/websocket.html).
- readiness를 통과한 인스턴스만 투입한다. Nginx의 수동적 실패 감지와 별도 readiness 확인/대상 제외 절차를 구분해 구성한다. 배포 시 신규 요청을 끊고 진행 중 요청·연결을 마무리하는 drain 절차를 둔다. 제출 POST를 프록시가 임의 재전송하지 않도록 하고, 클라이언트 재시도는 동일 제출 ID/멱등 키로 처리한다.
- 배포 색상과 실행 복제본을 구분한다. 정상 운영에는 같은 검증 버전의 복제본들이 요청을 분담하고, 버전 교체 중에는 스키마 호환성과 drain을 확인한다. 종료 처리·복구 작업은 여러 인스턴스에서 실행되더라도 DB lease/멱등성으로 한 번만 반영되게 한다.
- 같은 호스트의 컨테이너 두 개는 호스트 장애까지 견디는 고가용성이 아니다. Nginx·DB·Redis·호스트의 단일 장애점은 별도 기록하고, 다중 호스트 고가용성 범위는 운영 요구와 예산에 따라 추가 결정한다.

선행 수정: A01/A07의 봇 요청·연결·출력 제한, A06의 큐 조회 오판 및 전역 슬롯, A10의 접수 선저장·복구, A12의 Redis 대기열 정체, A09/A18의 readiness·배포 일관성을 먼저 해결한다. 로그인·저장·점수 원장 문제도 기존 A02–A05/A13/A15의 수정 범위에서 제외하지 않는다. 로드밸런싱은 공격 요청을 차단하는 기능이 아니므로, Redis 공통 제한과 제한 초과 시 429/대기열 거부가 계속 적용돼야 한다. 회선 자체를 채우는 대규모 공격은 애플리케이션 제한과 별개로 상위 네트워크 방어 검토가 필요하다.

완료 검증은 운영 공격 실험이 아니라 격리 staging에서 먼저 수행한다.

1. 인스턴스 식별자가 포함된 내부 로그로 정상 요청이 최소 2개 API에 실제 배분되는지 확인한다. 비밀값이나 내부 주소를 공개 응답에 넣지 않는다.
2. 한 인스턴스를 중지해도 건강한 인스턴스가 신규 요청을 처리하고, 마감 전에 접수된 제출의 유실·중복 지급·큐 상태 오판이 없어야 한다.
3. 봇성 반복 HTTP 실행과 WebSocket 연결을 섞어도 공유 제한을 우회하지 못하고, 설정한 대기열/실행/출력 상한을 넘지 않아야 한다. 정상 사용자의 처리 지연 목표를 정해 함께 측정한다.
4. API/worker 수를 늘리거나 줄여도 대기 작업이 정체되지 않고 전역 실행 예산·점수·권한이 유지되어야 한다.
5. 배포 drain, WebSocket 중단 안내, 재연결, 동일 멱등 키 재시도, worker 재시작을 포함하는 회귀 테스트를 통과해야 한다.

검증 후 운영 반영은 사용자의 별도 배포 지시를 받은 뒤 수행한다. 이 문서 수정은 구현·배포 승인이 아니다.

## 6. 수정 순서와 완료 기준

| 단계 | 범위 | 완료 기준 |
|---|---|---|
| 1. 안전성·무결성 | A01–A09, 계정 초안 분리, SMTP | 아래 재현 검사가 기대 결과로 바뀜. 무제한 출력·연결 방어는 staging에서 검증 |
| 2. 제출 경로 통합 | 일반 제출 durable 저장, worker 분리, 큐 읽기/복구 분리 | API/worker 강제 종료 후 접수 건 유실 0, 중복 점수 0, 잘못된 실패 표시 0 |
| 3. 조회·연결 개선 | 필요한 열만 조회, pagination, 점수판 캐시, pool | 합의한 부하에서 API·점수판 지연, DB pool wait·메모리·오류율 측정 및 목표 충족 |
| 4. 운영 체계 | 백업·복원, SHA 고정 배포, 마이그레이션, 의존성, 알림 | 새 환경 복원 검증, blue/green drain/rollback 리허설, 경고가 담당자에게 전달 |
| 5. 화면·품질 | 모바일 IDE/목록, 저장 상태·인증 오류, lazy loading, 접근성 | 390/768/1440px 및 키보드·확대 검사, 주요 흐름 E2E |
| 6. 최종 로드밸런싱 | A25, 복수 API upstream·공유 제한/큐·readiness·drain | 5.4절의 실제 분산·인스턴스 장애·봇 반복 요청·증감·배포 검증 통과. 별도 승인 후 운영 반영 |

성능 목표 숫자는 부하 테스트 없이 단정하지 않는다. 초기 검증 시나리오는 동시 사용자 10→50→100으로 증가시키되 읽기/일반 제출/대회 제출/터미널 혼합 비율을 정하고 staging에서 실행한다. 관측 항목은 접수 지연 p50/p95/p99, queue wait, 언어별 실행 시간, DB 연결 대기·잠금, worker lease 만료, 재시도, 출력 제한, 호스트 디스크, 종료 처리 지연이다. 수용 인원은 이 결과와 자원 예산으로 결정한다.

## 7. 검증 결과와 범위

| 영역 | 이번 근거 | 판정 및 한계 |
|---|---|---|
| 운영 버전·접속 | SSH HEAD, GitHub Deploy `34338372941` success, 홈200 | 확인 |
| 전체 프런트 기본 진입 | 운영 Edge 15개 경로 × 1440/390px, 공개/권한 거부 화면 | 30회 모두 문서 가로 overflow·JS 예외 없음. 로그인 후 모든 조작을 뜻하지 않음 |
| 홈·IDE·챌린지·대회·커뮤니티 | 코드 및 일부 스크린샷 시각 검수 | 모바일 IDE/목록 개선 필요 |
| 인증·프로젝트·권한 | 기존 테스트 및 격리 재현 | 기존 JWT·초안 경계·503 로그아웃 결함 확인 |
| 일반 채점·점수 | 새 SQLite API 재현 | 0테스트·삭제 원장·보관 개수 결함 확인 |
| 콘테스트 | 소스 및 배포 커밋 backend 테스트 포함 | 접수 시간 경계·미참가·중복·순서 역전·공동 순위·비공개·복구·종료 재실행 검증 범위 확인 |
| 큐 | 두 인스턴스+같은 임시 DB | 다중 프로세스 상태 오판 확인. 운영 queue GET 미호출 |
| 실행기 | 소스·운영 Docker 설정·연결 실패 대역 | 이번에는 실제 제출/악성 실행/무한 출력 실행 안 함 |
| 서버·데이터 | docker inspect, 읽기 전용 집계 | 현재 원장 불일치0. 재시작·실제 복원 시험 안 함 |
| 커뮤니티·관리 API | 작성/수정/삭제 소유권 및 require_admin 소스·기존 테스트 | 운영 게시물·권한 변경 안 함 |
| 테스트 | 운영 HEAD snapshot backend **57 passed**, 프런트 **19 passed**, typecheck/build 성공 | 2개 backend deprecation, 큰 JS chunk 경고. 통과해도 위 미포함 결함 존재 |
| 의존성 | npm audit 전체/production 분리, 운영 Python 버전 읽기 | Python/OS 전체 CVE·컨테이너 스캔은 미실시 |

브라우저 경로: 홈, IDE, 문제 목록/상세, 리더보드, 제출 내역, 커뮤니티, 대회 목록/진행 상세/종료 상세/종료 문제, 대회 생성/편집 권한 거부, 관리자 로그인, 비밀번호 재설정. 큐는 소스·격리 검사로 대체했다. 생성→참가→6언어 채점→종료 공개의 실제 운영 검증은 **이전 배포 검증 기록**에 있으며 이번 감사에서 새로 제출하지 않았다. 기존 CI의 장기 Docker/browser E2E는 `RUN_LONG_E2E` 설정에 따라 생략될 수 있다.

남은 추가 검증은 숨기지 않는다: PostgreSQL 실제 동시성·잠금 경합, Redis 장애/분할/메모리 부족, Docker·API·호스트 강제 종료, 백업 복원, 프록시 신뢰 IP, 실메일, 브라우저별 접근성, 커널·실행 이미지 탈출 방어는 staging 또는 별도 권한·운영 합의가 필요하다. 이번 문서는 이러한 시험을 완료했다고 주장하지 않는다.

## 8. 재현 자료

로컬 조사 스크립트는 Git에서 무시되는 `.deploy/`에 보관했다. 비밀값 없이 새 임시 DB/별도 브라우저 컨텍스트를 사용한다. 정상 동작 기대 테스트가 아니라 **결함 관측용**이므로 출력 자체를 확인해야 한다.

| 파일 | 용도 |
|---|---|
| `.deploy/audit-head/` | `git archive e5cf7642`로 분리한 운영 소스 |
| `.deploy/audit_repro.py` | JWT, 0테스트, 점수 원장, 보관 상한, 큐 조회, 임시 파일 재현 |
| `.deploy/audit_frontend_repro.cjs` | 계정 초안 혼합·503 로그아웃, API 전부 응답 대역 |
| `.deploy/audit_browser_readonly.cjs` | 운영 기본 화면, POST/PUT 등 차단·큐 조회 차단 |
| `.deploy/audit_runtime_readonly.py` | 설정 유무·컨테이너 정보·DB 집계, 비밀값 출력 안 함 |
| `.deploy/audit-ide-390.png` 등 | 운영 화면 캡처 |

제품 변경으로 옮길 때는 재현을 정식 regression test로 변환하고 정상 기대값을 assert해야 한다. 조사용 snapshot·임시 DB를 운영 DB와 혼동하지 않는다. 본 문서는 현재 관측 시점의 감사 결과이며 수정 후에는 해당 ID별 증거를 다시 수집해야 한다.

### 고정 버전 소스 참조

- [배포 커밋](https://github.com/2026CJUCapstone/project/tree/e5cf76429803a4bad9cb98a01fb999cb85094c06)
- [터미널 시작·실행 경로](https://github.com/2026CJUCapstone/project/blob/e5cf76429803a4bad9cb98a01fb999cb85094c06/backend/app/api/routes/terminal.py#L22)
- [프로세스별 큐 조회](https://github.com/2026CJUCapstone/project/blob/e5cf76429803a4bad9cb98a01fb999cb85094c06/backend/app/services/compile_queue.py#L173)
- [일반 문제 삭제](https://github.com/2026CJUCapstone/project/blob/e5cf76429803a4bad9cb98a01fb999cb85094c06/backend/app/api/routes/problems.py#L285), [일반 제출](https://github.com/2026CJUCapstone/project/blob/e5cf76429803a4bad9cb98a01fb999cb85094c06/backend/app/api/routes/problems.py#L499)
- [비밀번호 재설정](https://github.com/2026CJUCapstone/project/blob/e5cf76429803a4bad9cb98a01fb999cb85094c06/backend/app/api/routes/auth.py#L241)
- [초안 동기화](https://github.com/2026CJUCapstone/project/blob/e5cf76429803a4bad9cb98a01fb999cb85094c06/frontend/src/app/components/CodeEditor.tsx#L186)
- [대회 점수판](https://github.com/2026CJUCapstone/project/blob/e5cf76429803a4bad9cb98a01fb999cb85094c06/backend/app/services/contests.py#L82)
- [대회 경계·점수·복구 테스트](https://github.com/2026CJUCapstone/project/blob/e5cf76429803a4bad9cb98a01fb999cb85094c06/backend/tests/test_contests.py)
