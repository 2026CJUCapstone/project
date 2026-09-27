# 최종 준비 상태와 외부 수락 조건 — 2026-09-27

## 결론

제품 코드 기준선 `a17b3b24261333d95887c555844e4110edc4cafa`와 최종 격리 검증 후보 `1829ac023ad7b59f8cb4b2bd82a3d61d54a0620e`는 SMTP를 제외한 로컬 회귀와 별도 PostgreSQL·Redis 통합 검사를 통과했다. `a17b3b2` 이후 두 커밋은 실제 로드밸런서 시험의 관측·대기 로직만 보강한다. 이 결과는 운영 배포, 상업 서비스 규모의 장시간 부하 수락, A–J 대회의 공개 승인을 뜻하지 않는다. 운영은 여전히 `ebd7e367f396dfab20a3a1f1f6ce96a4fdd4c79e`이고, 이 작업에서 push, main 병합, 배포, 운영 DB 변경, 대회 등록은 하지 않았다.

## 이번 최종 검증

| 범위 | 결과 | 해석 |
|---|---:|---|
| 새 LF checkout의 corpus manifest·runtime harness·재채점 집중 회귀 | 149 PASS, 5 SKIP | frozen manifest `sha256:e5213ca9d1aaf3691c91db22aa021870b532b653c015c58c4bf90fff8a8539fc`; skip은 외부 staged archive와 전용 runtime이 없는 명시적 조건이다. |
| 사용자의 원본 작업 폴더에 동기화한 동일 변경 | 151 PASS, 1 SKIP | 원본의 기존 변경을 보존한 채 최신 세 파일을 반영했다. 원본 폴더에 이미 있던 staged archive 때문에 fresh checkout보다 두 검사가 더 실행됐다. |
| 백엔드 전체 | 3,152 PASS, 455 SKIP, 10 subtests PASS, 0 FAIL, 545.71초 | 제품 기준선 `a17b3b2`의 새 LF worktree 결과다. skip은 PostgreSQL·Redis·POSIX·Docker/cgroup·외부 런타임 등 명시적 환경 조건이며 성공으로 세지 않는다. 이후 최종 후보는 실제 LB 시험 코드만 바뀌었고 해당 파일을 포함한 집중 회귀는 43 PASS, 2 SKIP이다. |
| 프런트 전체 | 58 files, 322 PASS | TypeScript 검사와 production build도 PASS. `npm ci` 감사 결과 알려진 취약점 0건. |
| 서버 격리 PostgreSQL·Redis | 48 PASS, 3 SKIP, 0 FAIL, 147.03초 | 운영 DB·Redis와 분리된 기존 audit Compose를 재사용했다. 세 skip은 PostgreSQL 전용 process test의 SQLite 매개변수 변형이다. |
| Linux A–J private package·bundle | 152 PASS, 4 SKIP, 0 FAIL, 263.92초 | owner-only 출력, blob closure, 부분 생성 실패 정리, symlink 거부, 동일 bundle replay, import transport를 비권한 UID·read-only·network-none container에서 확인했다. skip은 POSIX에서 불필요한 Windows 음성 테스트 1개, image의 Git 부재 1개, 별도 staged archive 부재 2개다. |
| PostgreSQL private import 흐름 | 3 PASS, 0 FAIL, 21.86초 | 실제 C 최대 stored data package의 미검수 비공개 차단과 검수·재시도 흐름을 고유 임시 PostgreSQL schema에서 실행했다. 종료 후 `audit_contest_*`·`audit_queue_*` 잔여 schema는 0개다. |
| 실제 격리 PostgreSQL 삭제·제출 경쟁 | 1 PASS, 0 FAIL, 5.16초 | 삭제와 제출이 같은 문제 행 잠금을 사용한다. 삭제 선점은 404와 무접수, 제출 선점은 보존된 receipt/job과 논리 삭제로 직렬화됐다. |
| 실제 격리 LB·failover·부하 | 1 PASS, 0 FAIL, 100.18초 | 두 API 분산, 접수 API 강제 종료 뒤 다른 API의 receipt 조회·완료, 활성 terminal WebSocket의 정확한 upstream 강제 종료와 취소 1회, 서로 다른 인증 계정의 고유 receipt 7건과 terminal 1건의 전역 한도, 누적 10→50→100 공유 rate window, 2→3→2 증감, worker readiness 503을 외부 port 없이 실행했다. 누락 sandbox image는 세 번 재시도 뒤 system error가 되고 journal·작업 폴더가 남지 않았다. |
| readiness·controller fail-closed | 1 PASS, 0 FAIL, 182.65초 | 실제 Nginx/frontend/API/worker/controller를 만들고 release·pool·runtime identity 충돌, membership reload와 잘못된 peer 거부를 확인했다. |
| API·worker lifecycle·runtime inventory | 14 PASS, 0 FAIL, 221.21초 | held HTTP·WebSocket drain, worker fencing·재시작, runtime restart·replace·graceful retirement·stateful 보존, namespace 위조 거부를 확인했다. |
| 운영 read-only probe | `/health` 200, release marker 200 | 둘 다 운영 SHA `ebd7e367...`를 반환했다. `/webcompiler/ready`는 200 HTML SPA fallback을 반환해 운영 host include가 아직 고쳐지지 않았음을 재확인했다. |

서버 검증 중 재채점 shard의 부모 행보다 item이 먼저 INSERT되어 PostgreSQL FK가 7건 실패하는 오류를 재현했다. `contest_rejudge.py`가 각 bounded shard 부모를 먼저 flush하도록 고쳤고 동일 묶음이 48 PASS로 바뀌었다. SQLite만으로는 드러나지 않던 실제 dialect 차이다.

runtime matrix controller가 `capture_output=True`로 출력을 전부 메모리에 모은 뒤 128 KiB를 검사하던 문제도 고쳤다. stdout·stderr를 동시에 제한해 합계 128 KiB에서 프로세스를 종료하고, timeout·overflow·truncation·실제 보관 byte 수를 영수증에 남긴다. 실제 subprocess overflow와 timeout 회귀를 추가했다.

CPU가 제한된 audit host에서 충돌 API는 identity mismatch를 기록했지만 Docker SDK의 streaming `wait` 응답이 15초 안에 끝나지 않아 readiness 검사가 실패하는 문제도 재현했다. 실제 PID 1 상태를 최대 30초 동안 inspect polling하고 종료 코드를 확인하도록 바꿨다. 수정 후 readiness/controller 시험이 182.65초에 통과했으며, 단순히 timeout을 성공으로 바꾸지 않는다.

## A01–A25 판정

판정 의미:

- `완료-로컬`: 요구한 코드 경계와 자동 회귀가 현재 후보에서 닫혔다.
- `현재증거`: 기능 회귀는 있으나 실제 브라우저·경쟁·대규모 자료 수락이 남았다.
- `외부검증필요`: 코드만으로 운영 인프라·정책·부하 수락을 대신할 수 없다.

| 항목 | 판정 | 현재 근거 | 남은 정확한 조건 |
|---|---|---|---|
| A01 공개 실행 제한 | 현재증거 | terminal admission, execution resource budget 회귀와 격리 10→50→100 shared-rate ramp | 장시간 동시 WebSocket을 포함한 더 긴 soak와 익명·대회 간 starvation |
| A02 계정 초안 | 완료-로컬 | `CodeEditor.identity.test.tsx` | 없음 |
| A03 비밀번호·메일 | 외부검증필요 | session-version, reset configuration 회귀 | SMTP는 이번 목표에서 제외. 실제 공급자·발송·수신·reset URL은 별도 수락 |
| A04 테스트 0개 문제 | 완료-로컬 | problem integrity 회귀 | 없음 |
| A05 삭제와 점수 원장 | 완료-로컬 | problem integrity 회귀와 실제 PostgreSQL 삭제·제출 경쟁 1 PASS | 없음 |
| A06 다중 프로세스 큐 | 현재증거 | 실제 격리 Nginx·두 API·worker·WebSocket의 정확한 upstream/API/worker 강제 종료·receipt 복구와 exact-once 완료 | 더 긴 soak와 운영과 동급인 별도 staging host 장애 |
| A07 실행 출력·로그 상한 | 외부검증필요 | runner output budget과 controller 물리 128 KiB cap | 느린 소비자와 혼합 부하에서 API·프록시·디스크 상한 |
| A08 Docker 권한 분리 | 외부검증필요 | runtime binding·worker 격리 회귀 | 전용 non-default daemon 또는 VM의 전체 Compose 권한·mount 수명주기 |
| A09 재시작·readiness | 현재증거 | 실제 격리 readiness/controller, API·worker drain, restart·replace·retirement 15 PASS | cold 전체 Compose와 host 손실 수락 |
| A10 일반 제출 내구성 | 외부검증필요 | durable submission 회귀, PostgreSQL rejudge shard 통합 PASS | 실제 배포 이관·장애·혼합 부하 |
| A11 점수판 조회 | 외부검증필요 | projection·cache concurrency 회귀 | 대용량 대회 자료와 혼합 조회 성능 |
| A12 Redis 큐 정체 | 현재증거 | 실제 격리 shared Redis admission, 서로 다른 계정의 고유 receipt 전역 한도, worker fencing·재시작, API loss와 100-request ramp | 장시간 backlog·Redis process 장애·전체 rollout |
| A13 저장 충돌·유실 | 현재증거 | project revision·editor identity 회귀 | 전체 브라우저와 운영 흐름 수락 |
| A14 모바일 IDE·목록 | 현재증거 | IDE mobile 회귀 | 실제 데이터가 많은 모바일 목록 검수 |
| A15 503 시 로그아웃 | 완료-로컬 | header auth 회귀 | 없음 |
| A16 요청 제한·관리 감사 | 외부검증필요 | admin audit transaction·trusted ingress 회귀 | 운영 ingress 신뢰 설정과 감사 조회·보관 정책 |
| A17 의존성·빌드 | 외부검증필요 | lock·SBOM·CI 회귀, 현재 npm audit 0 | 실제 GitHub job, 전체 image scan, artifact 결속 |
| A18 SHA 배포 | 외부검증필요 | deploy sync·release metadata 회귀 | 실제 GitHub 권한·known-hosts·drain 배포 |
| A19 백업·복구 | 외부검증필요 | backup live 회귀 | 정기 일정, 외부 보관, RPO·RTO 승인 |
| A20 보안 header·origin | 외부검증필요 | frontend security·trusted ingress 회귀 | TLS 종료단 HSTS와 운영 ingress |
| A21 보관 정책 | 외부검증필요 | submission retention 회귀 | 기간 승인, 장기 receipt 상한, 대규모 정리 지연 |
| A22 임시 파일 정리 | 외부검증필요 | runner cleanup·sandbox reconciliation 회귀와 실제 typed ImageNotFound 3회 재시도 뒤 journal/workdir 0 | daemon 장애와 전송 단절처럼 결과가 불확실한 RPC 복구 |
| A23 조회·번들 | 외부검증필요 | compile history filter·browser 회귀 | 대용량 조회와 bundle 성능 |
| A24 안내·접근성 | 현재증거 | auth modal 접근성·모바일 tab 회귀 | 전체 화면 키보드·확대·보조기기 검수 |
| A25 로드밸런싱 | 현재증거 | 실제 두 upstream, API loss, receipt 연속성, 활성 WebSocket upstream loss, 고유 인증 receipt의 exact-once, 10→50→100, 2→3→2, drain·controller fail-closed | 별도 daemon/host의 cold deploy, 장시간 soak, Redis process loss, multi-host HA |

## 5.4 최종 로드밸런싱 목표

코드에는 두 API peer, 공유 상태, generation·drain, idempotent receipt, worker fencing, proxy promotion 경계가 있다. 운영의 read-only 요청 12건이 두 API에 7/5로 분배된 과거 smoke도 있다. 최신 후보는 운영과 분리된 audit PostgreSQL·Redis와 실제 Docker/Nginx/API/worker를 사용해 다음 단일-host 시나리오까지 통과했다.

- 두 upstream 분산과 접수 API 강제 종료 후 다른 API의 동일 receipt 조회·완료.
- Python worker와 terminal WebSocket 입출력, 활성 socket의 실제 upstream API 강제 종료와 취소 1회, survivor의 새 terminal 접수, held HTTP·WebSocket drain.
- 공유 rate window의 실제 누적 10→50→100 요청과 서로 다른 인증 계정의 고유 제출: terminal 1건과 HTTP 7건만 허용되고 나머지 2건은 429, 생성된 job은 모두 정확히 한 번 완료.
- 2→3→2 membership 증감, runtime identity 충돌 fail-closed, worker restart·fencing, graceful retirement.
- 존재하지 않는 sandbox image의 typed 404는 동일 daemon/lease/operation에서만 no-effect로 확정하고 세 번 재시도 뒤 journal·작업 폴더를 제거. 연결 단절 등 모호한 실패는 그대로 조정 대상으로 보존.
- 매 실행 뒤 테스트 container·image·network·Redis key·DB audit schema·sandbox 잔여값 0.

이것은 현재 후보의 실제 single-host 격리 증거다. 테스트 controller가 기본 Docker daemon을 공유하고 host 자체를 잃지 않았으므로 독립 daemon/VM 또는 multi-host 최종 수락으로 확대하지 않는다.

다음은 staging에서 한 시나리오로 실행해야 한다.

남은 최종 수락은 장시간 WebSocket과 HTTP bot을 동시에 유지하는 더 긴 soak, Redis process 자체 장애, cold 전체 Compose, 운영과 동급인 독립 daemon/VM, 그리고 multi-host가 범위라면 host 한 대 손실이다. 단일 host의 여러 컨테이너는 HA가 아니다.

현재 서버에는 테스트용 PostgreSQL·Redis Compose는 있으나, runtime harness가 요구하는 별도 non-default Docker socket은 없다. 기본 `/var/run/docker.sock`을 독립 staging으로 가장하지 않고 harness가 fail-closed하도록 유지했다. 따라서 최신 v2 24-case mechanics, 여섯 언어×A–J cgroup 반복, OOM·PID·tmpfs·network·cleanup 수락은 외부 조건이다.

## A–J 비공개 대회 패키지

- frozen manifest: `sha256:e5213ca9d1aaf3691c91db22aa021870b532b653c015c58c4bf90fff8a8539fc`
- 문제별 candidate 수: A 5, B 12, C 7, D 5, E 7, F 6, G 7, H 7, I 11, J 12
- 공개 예제 26개, hidden 후보 53개, unique stored blob 89개(12,718,689 bytes), 여섯 언어 reference source 60개
- C, C++, Python, Java, JavaScript 기준 풀이는 현재 로컬 도구로 통과했다. B++ source inventory는 있으나 A–J 전체 실제 실행은 최종 설치 runtime이 없어 수락하지 않았다. 운영 B++ 단일 `42` smoke는 A–J 실행 증거가 아니다.
- private builder·blob receipt·단일 import·apply idempotency 계약은 mock transport와 fixture에서 통과했다. 상태는 의도적으로 `draft-unapproved`, `releaseReady=false`, `published=false`다.
- Linux에서 실제 owner-only bundle 작성·재작성 거부·동일 bundle replay와 PostgreSQL private-import 재시도를 확인했다. 이는 transport·DB 멱등 준비 증거이며 관리자 HTTPS endpoint에 실제 업로드했다는 뜻은 아니다.
- 운영자 승인 없이 package ID를 새로 만들거나 업로드·등록·공개하지 않는다.

반드시 사람이 결정하거나 외부 근거를 제공해야 하는 항목은 A–J 지문·예제와 J 수학 검수, 원문·번역·각색·테스트 재배포 권리, 최신 solved.ac tier 근거, 제목·KST 일정·배점·난이도·태그·참가 규칙, J 순위 반영, AI·외부 도움 규칙, 종료 후 공개 여부, 최종 여섯 언어 정책과 문제×runtime 최소 10회 실측이다.

## 증거 보존과 위생

`docs/evidence` 85개 중 84개는 기존 Markdown에 직접 연결돼 있다. 남은 [authoring validation 회귀 원시 기록](evidence/authoring-validation-regressions-2026-09-27.json)도 이 문서에서 연결해 미참조 상태를 해소한다. [첫 reference 측정 요약](evidence/freshman-reference-first-pass-summary-2026-09-26.json)에는 당시 Windows checkout 절대 경로가 다섯 곳 남아 있지만 사용자명·비밀은 없고, 원시 영수증을 사후 변조하지 않기 위해 보존한다. `/tmp`와 PostgreSQL container 경로는 격리 실행 경로다. 전체 evidence 검색에서 명백한 실제 토큰·비밀번호·운영 비밀은 발견되지 않았다.

서버에 이번 검증을 위해 만든 `/home/vulpo/webcompiler-audit-final-d000ec1e`, `/home/vulpo/webcompiler-audit-final-f18279e9`, `/home/vulpo/webcompiler-audit-lb-ws-O0UFNp`와 전송 archive는 각 경로의 소유권·권한·container mount 참조를 확인한 뒤 삭제했다. 마지막 경로는 read-only 소스 권한 때문에 첫 삭제가 거부됐고, 정확한 경로의 owner-write 권한만 복원한 뒤 다시 확인하고 삭제했다. 마지막 확인에서 이번 실행의 label을 가진 container·image·network와 audit DB schema·Redis key·sandbox entry가 모두 0개였다. 운영 컨테이너·운영 데이터·기존 audit PostgreSQL·Redis는 변경하지 않았다.

## 다음 실행의 필수 입력

남은 항목을 완료하려면 다음이 필요하다.

- 전용 Docker daemon/VM 또는 식별 가능한 staging host와 승인된 image digest·host class
- 운영과 분리된 최신 PostgreSQL·Redis·proxy·worker stack, bounded load window
- 운영 ingress/root 적용 권한: 현재 public `/webcompiler/ready` SPA fallback 수정
- A–J 권리와 운영 규칙 결정, 관리자 HTTPS endpoint·token, private import 명시 승인
- 보관 기간, RPO/RTO, audit 접근, TLS/HSTS, multi-host HA 범위 승인
- 별도 push/main 병합·배포 지시

이 입력 없이 남은 항목을 임의 값으로 완료 처리하지 않는다.
