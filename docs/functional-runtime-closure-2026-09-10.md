# 실제 화면 후속 검증 — 2026-09-10

## 최종 결과와 범위

최종 격리 이미지에서 브라우저 **12개 테스트 모두 통과**했다. 이번에 발견한 F13·F14를 수정했고 기존 F09~F12와 실제 대회·실행·제출 경로를 함께 검증했다. **F01 실제 SMTP 메일 재설정은 미완료**다. 모든 입력·장애·브라우저 조합의 무결함 보증이나 운영 배포 승인을 뜻하지 않는다.

| 검증 | 실제 결과 | 증거 |
| --- | --- | --- |
| 대회 관리자 작성→공개→참가→문제 IDE→실제 채점→점수판→실제 종료→일반 공개/점수 | 1/1, 174.523초 | [contest-runtime/results.json](../.deploy/test-results/contest-runtime/results.json), `contest-runtime.local.spec.ts` |
| 닉네임/긴 이메일 로그인·두 탭 계정 전환·프로필 null/생략/재로드 | 3/3, 19.516초 | [identity-runtime/results.json](../.deploy/test-results/identity-runtime/results.json), `identity-runtime.local.spec.ts` |
| 일반 문제 Python 제출→실제 정답→큐 필터→내 제출→문제 이동→137점 랭킹 | 1/1, 전체16.063초(테스트 본문14.6초) | [history-runtime/results.json](../.deploy/test-results/history-runtime/results.json), `history-runtime.local.spec.ts` |
| B++·C·C++·Python·Java·JavaScript 기본 템플릿의 실제 브라우저 WebSocket 실행, Python stdin/재연결 | 7/7, 73.335초 | [languages-runtime/results.json](../.deploy/test-results/languages-runtime/results.json), `languages-runtime.local.spec.ts` |

각 결과의 skipped/unexpected/flaky는0이다. 재시도 중 통과한 일부 검증을 별도 성공 수로 더하지 않았다. 테스트 서버의 빈 PostgreSQL/Redis와 실제 worker/Docker를 사용했다. 가짜 채점 결과, 가짜 서버 시각, 운영 DB 복사본은 사용하지 않았다.

프런트 회귀는 **25파일122 passed**, 실패0([JSON](../.deploy/frontend-regression-f14.json)); 타입 검사 통과, `/webcompiler/` 빌드15.15초. 빌드의 큰 청크 경고와 기존 테스트 act 경고는 남아 있으며 오류 없는 로그라고 주장하지 않는다. 백엔드 제품 변경은 이번 후속 작업에 없고 직전 전체 결과 **2001 passed / 362 skipped / 8 subtests**를 유지한다. 362 skip을 실행 통과로 세지 않는다.

## 추가 수정

### F13 — 일반 제출 언어 고정

`JudgePanel`의 `submitProblem(challengeId, code, 'bpp')`가 IDE 언어 선택과 분리되어 있었다. 실제 선택 언어를 store에서 구독해 전달하도록 수정했다. 6언어와 패널을 연 채 언어/코드를 변경하는 회귀7개를 추가했다. 수정 전 B++를 제외한5언어 및 변경 사례6개 실패 → 수정 후7개 통과.

이전 이미지의 브라우저 시도는 잘못된 label/로그인 대기/패널 locator에서 멈춰, 잘못된 실제 POST 증거는 얻지 못했다. 코드와 단위 red가 오류 재현 근거다. 최종 실제 이미지에서는 원문 `print(42)`와 `language: python` POST, 실제 정답, 137점과 큐/이력/랭킹 일치를 모두 확인했다.

### F14 — 초기 편집기 로딩이 언어 선택을 덮음

Header의 언어 선택은 Monaco 초기화 전에 가능했다. 이후 `CodeEditor`가 저장 언어 또는 기본 B++를 불러오며 앞선 선택과 템플릿을 덮었다. 실제 C/C++/Java/JS 시험에서 B++ 소인수분해 예제가 나타났고, Python stdin 시험은 B++ 선택 상태로 컴파일에 실패했다.

공유 readiness를 추가했다. 현재 editor가 local saved code를 hydrate하기 전에는 언어 선택·저장·컴파일·실행을 비활성화하고, editor unmount 시 다시 잠근다. 원격 프로젝트 GET의 기존 편집 보호는 그대로 유지한다. Header gate red1→green1, CodeEditor hydration/unmount lifecycle1 및 기존 identity8개를 검증했다. 새 이미지에서 미리 선택을 시도하는 6언어 브라우저 경로가 모두 정상 템플릿·출력·종료를 보였다.

초기 B++ 데모를 Hello World로 바꾸지는 않았다. 기본 B++ 템플릿 시험은 다른 언어를 거쳐 B++를 다시 선택하여 명시적 언어 선택 경로를 사용한다.

## 대회 증거

- 대회 `8205a0d1-9380-4fe5-be43-472687f76acf`, 원본 문제 `7ff03b89-43e2-4c86-994c-f8805e19422a`.
- 실제 UTC 시작 `2026-09-10T11:21:00Z`, 종료 `11:23:00Z`. UI에는 KST를 입력하고 API UTC 값을 대조했다.
- 순서대로 WA `11:21:05.852330`, CE `11:21:09.818940`, AC `11:21:13.799539`, 중복 AC `11:21:18.693108` 접수. 각 POST 코드·202 receipt·해당 ID의 최종 판정·다른 참가자의 소스404를 검사했다.
- 총500점, 패널티313.799539초 = 첫 AC 경과13.799539 + WA1회300초. CE는 제외되고 중복 AC는 점수를 늘리지 않았다.
- 종료 전 일반 점수 변화0; 실제 종료 후 일반17점만 지급. 마감 후 제출403, 문제 일반 공개 및 숨긴 입력 비노출, 대회 초안과 일반 IDE 초안 분리 확인.
- 390px 본문 overflow 검사 및 모바일 점수판 스크린샷을 직접 확인했다. 점수판 가로 스크롤 안내와 실제500점/패널티가 표시됐다. 랭킹도 표 내부 가로 스크롤을 유지하며 본문이 넘치지 않았다.

## 시험 오류와 제품 오류 구분

- 첫 대회 CE 입력 `print(`에 Monaco가 `)`를 자동 추가했다. 저장된 실제 코드는 `print()`여서 WA가 정확했다. `if :`로 바꾸고 POST 코드 원문 일치를 추가했다.
- 다음 대회 시험은 마지막 모바일 IDE에서 비활성 코드 패널을 검사해 실패했다. 코드 탭을 명시적으로 선택한 최종 전체 실행이 통과했다.
- 터미널 stdin은 큐 안내·입력 echo·stdout이 별도 요소로 나뉘었다. 출력 요소 전체를 단일 locator로 가정한 strict 오류를 고쳐 `GOT42`/`GOT43` 출력 행과 정상 종료·재연결을 검사했다.
- 실패 보고서 일부는 `results.harness-*.json`, `results.pre-f14-failure.json`, `results.six-pass-stdin-locator-failure.json`에 보존했다. 초기에 보존 명령의 작업 경로가 틀린 경우 최종 증거처럼 취급하지 않았다.

## 이미지·운영 경계·정리

소유 namespace: `/home/vulpo/webcompiler-contest-browser-49L0gmmL`, Compose project `webcompiler-contest-browser-49l0gmml`, loopback15181/18011. 이미지 빌드는 정확한 기존 dependency image 위 COPY-only이며 **정식 clean dependency build/CI provenance 검증은 아니다**.

- backend: `sha256:508387ed0c163ebff052d6519c0afc53007a994bedec1c936425546954f89377`
- sandbox: `sha256:2e9b852f0d933a5a26d19e6c285f89f6f13e407a027da7ccf401629528673958`
- 최종 frontend: `sha256:0c2bf9cfd47e60d9ad55628245308d7863355797ffee7570db0fbbddb3085bf3`
- 최종 자산 archive SHA256: `ad5d42532f3360dd415dcd2800033fb781e7416d2f87c345c5be45b38e069ad6`
- backend source archive SHA256: `de11a79ac6c37107bba9d1bc7c55660de8ba7cf7d5d6232d922eb2d7dccc408e`; 현재 Python/launcher 파일 manifest를 실제 추출 파일과 대조했다.

[runtime-evidence.json](../.deploy/contest-runtime-evidence-49/runtime-evidence.json)은 서비스 image와 CPU/메모리/swap 제한을 기록한다. frontend만 교체했으며 다른 container ID는 변경하지 않았다. 기존 health 응답 deployment SHA는 상속된 설정값이므로 현재 dirty worktree 전체의 증명으로 사용하지 않는다.

[cleanup-results.json](../.deploy/contest-runtime-evidence-49/cleanup-results.json): 소유권을 검사하고 컨테이너9개·데이터 볼륨2개·네트워크·파생 이미지들을 제거했다. 미완료 작업/lease/operation0, draining 완료, sandbox 잔여 없음. BuildKit builder는 만들지 않았다. 독립 후속 조회에서 namespace별 컨테이너/볼륨/네트워크/이미지 잔여가 없었고 기존 운영7서비스는 healthy였다. 로컬15181 SSH 터널과 일회용 계정 파일도 제거했다. 시험 DB/Redis 데이터는 복구용으로 보관하지 않았으며 비밀 없는 결과와 소스/빌드 자료는 남겼다.

운영 데이터·설정·이미지·배포·main push는 변경하지 않았다. F01 실 메일 제공자/발신 주소/설정 경로/수신함 검증과 별도 승인된 배포 검증은 여전히 필요하다. 목표는 완료로 표시하지 않았다.
