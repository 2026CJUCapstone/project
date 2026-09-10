# 기능 수정 운영 배포 — 2026-09-10

## 결과

사용자의 서버 배포·Git push 승인에 따라 기능 수정본을 운영에 반영했다. 운영 코드 SHA는 `44b2af4ca104b1c343a577f75ce7880c928403f7`이다. 공개 health와 프런트 release marker 모두 이 SHA와 일치했다.

- 운영 주소: https://cuha.cju.ac.kr/webcompiler/
- Git 원격: `2026CJUCapstone/project`
- 푸시 브랜치: `codex/functional-remediation-release-20260910`
- 기능 수정 커밋: `9d49162c5a2139a8ced1d790c256a08a1028f02b`
- 실행 스크립트 패키징 수정: `44b2af4ca104b1c343a577f75ce7880c928403f7`
- 이 보고서 후속 커밋은 문서만 추가하며 운영 코드 SHA를 바꾸지 않는다.

`main`은 `e5cf76429803a4bad9cb98a01fb999cb85094c06` 그대로다. 현재 운영은 수동 basic 2-API pool이며 기존 main 자동 배포는 다른 관리형 배포 경로를 사용한다. 두 경로의 충돌을 피하기 위해 별도 release branch를 푸시하고 기존 basic pool을 직접 갱신했다. main CI 실행·통과나 main 병합을 주장하지 않는다.

## 실제 운영 검증

| 검사 | 결과 |
| --- | --- |
| 공개 전 loopback, 관리자 인증 실행 | B++·C·C++·Python·Java·JavaScript 모두 실제 stdout 42, exit 0 |
| 공개 HTTPS 비로그인 실행 | 같은 6개 언어 모두 실제 stdout 42, exit 0 |
| 오류 분류 | C++ 문법 오류 `compile_error`, Python 예외 `runtime_error` |
| 관리자 로그인·현재 계정 읽기 | 성공; 자격증명은 서버 안에서만 사용 |
| 대회·문제·컴파일 큐 공개 목록 | HTTP 200 |
| PC 1440px / 모바일 390px | 홈·IDE·챌린지·콘테스트·리더보드·큐·내 제출·커뮤니티·관리자 진입, 총18개 경로 통과 |
| 브라우저 | pageerror 0, 본문 가로 넘침 0, Python 선택 후 기본 템플릿 준비 확인 |
| 운영 서비스 | API 2개·worker·frontend·Redis·PgBouncer·API proxy 모두 healthy |
| 데이터 보존 | 보호 대상11개 테이블 전체 행 fingerprint 배포 전후 및 공개 검사 후 동일 |
| 작업 정리 | 최종 미완료 execution/lease/sandbox operation 0 |

관리자 화면의 비로그인 검사는 로그인 필요 안내와 홈 로그인 링크를 확인한 것이다. 운영에 예시 사용자·대회·문제·점수·게시글을 만들지 않았다. 대회 전체 작성/참가/채점/종료·점수 반영 검증은 앞선 실제 이미지 격리 시험의 증거이며, 이번 운영 검사에서 그 CRUD 전체를 반복했다고 주장하지 않는다. 상세 기능 증거는 [실제 화면 후속 검증](functional-runtime-closure-2026-09-10.md)을 참조한다.

안전한 원본 결과는 로컬 `.deploy/public-release-smoke-44b2af4c.json`, `.deploy/public-release-browser.json`과 서버 release root의 `public-smoke-results.json`에 보존했다. 비밀이나 운영 DB dump는 Git에 올리지 않았다.

## 첫 시도 실패와 실제 복구

첫 `9d49162c` 이미지의 health는 통과했지만 공개 B++ 실행에서 `exec /usr/local/bin/run.sh: no such file or directory`가 재현됐다. Windows `core.autocrlf` 설정이 적용된 `git archive`가 실행 스크립트의 shebang을 CRLF로 내보낸 것이 원인이었다. 이전 이미지로 실제 rollback하여 서비스와 이전 release marker를 확인했고, DB backup을 덮어쓰지 않았다.

`.gitattributes`에 `*.sh text eol=lf`를 추가했다. 임시 Git 저장소에서 autocrlf=true인 실제 archive의 LF bytes를 검증하는 회귀 테스트1개가 통과했고, 새 배포 archive의 runtime shell도 LF임을 직접 검사했다. 두 번째 rollout은 공개 전 6언어 실제 실행을 통과하도록 강화했고 모두 통과한 후 public route를 복구했다. 첫 실패를 최종 성공 결과에 포함하지 않는다.

브라우저 검사 중에는 Monaco NBSP, 비로그인 관리자 화면에 공통 header가 없다는 점, 콘테스트 페이지의 header가 둘이라는 점을 테스트가 잘못 가정했다. 테스트 locator를 고치고 전체18경로를 재실행했다. 이 과정에서 제품 코드를 추가 변경하지 않았다.

## 배포·보존 정보

- 현재 release root: `/home/vulpo/webcompiler-functional-44b2af4c`
- 기존 pool root: `/home/vulpo/webcompiler-basic-lb-EIXszgyU`
- Compose project: `webcompiler-basic-eixszgyu`
- backend/worker: `sha256:1c64eae4593ff9ea3af26fd8c16599391cd022236c1fb64b408a70334f16aebf`
- frontend: `sha256:1eee7c52a14981bb869c21132ffcd2db4f1bcb4c53dd09ec72cfb42c145eac35`
- sandbox: `sha256:869c2a796b7261f7603ba3ec920e9733a29daaf84e18c5050b505e7a6d647b74`
- source archive SHA256: `f820363fc92e9daae1905ef990b43776c568d217f1d0ee218fe5817bb2cb5eb1`

배포 lock을 잡고 edge를 일시503으로 전환한 뒤 신규 접수를 막고 기접수 작업을 drain했다. DB dump를 권한0600으로 보관하고 `pg_restore --list`가 통과한 후 application images만 교체했다. 이번 dump를 별도 DB에 복원하는 시험까지 수행한 것은 아니다. 원본 PostgreSQL 컨테이너·볼륨, Redis·PgBouncer·proxy 컨테이너 ID는 유지했다. 스키마·bootstrap·설정·dependency lock·Compose 계약이 기존 운영 소스와 동일함을 확인해 migration/initializer를 실행하지 않았다.

원본 사용자·문제·댓글·프로젝트·일반 제출·해결 기록·대회·대회 문제·참가·대회 제출·재설정 토큰은 전체 행 fingerprint로 보존을 검사했다. 실행 smoke가 만든 execution 기록은 이 보호 대상과 구분한다. 이전 이미지·소스·백업은 rollback을 위해 남겼다. 사용자 소유 미추적 보고서와 기존 보고서 삭제 변경은 release commit에 넣지 않았다.

## 검증 한계와 제외 조건

- SMTP 실메일 송수신은 사용자가 이번 완료 범위에서 제외했다. 설정하거나 성공 처리하지 않았다.
- 기존에 검증한 정확한 dependency image 위 COPY-only 빌드와 검증된 frontend assets를 사용했다. 새 clean dependency build/CI provenance를 증명하지 않는다.
- 이번 푸시 전 frontend 전체122 passed, 새 shell archive 회귀1 passed. 백엔드는 직전 전체2001 passed / 362 skipped / 8 subtests 결과이며, 새 테스트 추가 후 전체를 재실행한 숫자로 합산하지 않는다.
- 기존 단일 서버 2-API 로드밸런싱을 유지했다. 다중 호스트 HA, 대규모 봇/혼합 부하, 모든 장애·입력 조합의 무결함이나 상업 운영 보증을 뜻하지 않는다.
