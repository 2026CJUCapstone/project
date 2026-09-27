# 신입생 콘테스트 구현·수락 매트릭스

2026-09-27 B++ 범위 변경: 사용자가 A–J B++ 실행 검증은 완료하지 않아도 된다고 명시했다. B++ 소스와 inventory 4 PASS는 보존하지만, 중단된 Windows 실행을 PASS나 6언어 수락 증거로 계산하지 않는다. 중단 후 관련 잔류 프로세스는 없다.

2026-09-27 A–J 현재 패키지 재검증: 지문·oracle·validator·generator·오답·corpus **92 PASS**, 보충 stress **9 PASS**, 지문 26개 예제와 J 42개 변환 tiny case가 통과했다. 현재 Windows에 이미 있는 C/C++/Python/Java/JavaScript 실행기로 기준 풀이 **10 테스트 그룹 PASS**; B++는 source inventory **4 PASS**, 명시 `BPP_COMPILER` 미설정으로 실행 **4 SKIP**이다. 측정 archive **7 PASS/1 Windows symlink SKIP**, 비공개 draft builder **17 PASS/3 POSIX 권한 SKIP**, bundle 적용 preflight **16 PASS/1 POSIX SKIP**, import/transport **38 PASS**다. 이는 기능·패키지 일관성 증거이며 Linux/cgroup 자원 실측, 출처·이용 승인, 확정 일정·배점, 운영 등록을 대신하지 않는다. 추가 설치·서버 설정·업로드·배포는 없었다.

2026-09-27 최신 프런트 재검증: 현재 작업트리 전체 **58파일/322 PASS**, TypeScript 검사와 운영 빌드가 통과했다. 이는 로컬 프런트 코드와 모의 API 회귀 증거이며, 실제 backend/reverse proxy/Linux worker 수락을 대신하지 않는다. 서버 설정·배포·운영 데이터 변경은 없었다.

2026-09-27 C11 전송 경계 후속: 일반/private-package API의 512 KiB와 별도 `stored-v1` 업로드의 16 MiB 경계를 배포 Nginx 위치 블록과 직접 백엔드 스트림 양쪽에서 확인했다. 인증 후 본문을 읽기 전 단일 `application/json`/UTF-8 media type과 선언 크기를 검사하며 잘못된 media type은 415, 과대 크기는 413이다. 패키지 검증·CLI 전송은 compact camelCase canonical bytes 하나만 사용한다. 정확히 512 KiB인 요청은 한 번 import되고, 의미가 같은 JSON에 공백 1바이트를 붙인 요청은 413이며 추가 DB 행이 없다. 기존 관련 **67 PASS/2 명시적 PostgreSQL 환경 SKIP**, 추가 media-type 순수 회귀 **13 PASS**다. 현재 호스트에 `httpx`가 없어 추가 ASGI 통합 케이스는 실행 증거로 계산하지 않으며, 실제 배포 프록시 HTTP와 운영 blob 업로드는 수행하지 않았다.

2026-09-27 RG04/v24 후속: 출처 없는 과거 해결 점수가 재채점 차감을 막을 때 DB를 직접 고치지 않고 처리할 수 있도록 append-only legacy 해소 기록과 관리자 전용/no-store API·화면을 추가했다. 관리자는 출처 미확인 상태 유지 또는 같은 사용자·문제·배점의 기존 accepted 일반/대회 영수증 연결만 선택할 수 있다. 원래 legacy 근거를 수정하거나 출처를 새로 만들지 않으며, 미리보기/반영은 legacy·source 지문과 해소 provenance를 잠금 안에서 재확인한다. 백엔드 전체 **3,024 PASS/447 조건부 환경 SKIP/10 subtests/실패 0**, 프런트 **56파일/317 PASS**·타입·운영 빌드 PASS다. 실제 PostgreSQL 경쟁/rolling 재시작, 운영자의 실제 출처 판단·통지/이의 절차, Linux/cgroup/6언어 수락은 여전히 외부다. 운영 데이터·배포·push는 변경하지 않았다.

2026-09-27 C03/v23 독립 보안 검토 후속: 최초 증명 게이트를 별도 Terra xhigh 검토한 결과 세 우회가 확인됐다. (1) 출처 기록이 없는 신규 대회 문제는 호환 경로로 공개할 수 있었고, (2) 종료 대회의 재채점 정정 snapshot은 네 범주 수동 승인만으로 live snapshot을 바꿀 수 있었으며, (3) 이전 runtime marker를 `schema_migrations`에 남겨 rolling 중 구버전 API가 계속 ready가 될 수 있었다. 신규 비공개 문제는 출처·네 범주 승인·필수 언어별 accepted 증명을 모두 요구한다. 재채점 후보는 별도 관리자 POST/GET 검증 경로와 화면에서 후보 snapshot 자체를 실행하며, 반영 트랜잭션이 같은 contest/problem/snapshot/fingerprint/reference/policy/test 증명을 다시 확인한다. runtime v23 초기화는 `_vN` 활성 표식을 별도 `runtime_schema_history`로 원자 이동하고 현재 표식 하나만 남겨 구버전 readiness를 내린다. V19에는 같은 워커의 TLE→MLE→AC와 매 작업 reservation/claim/cleanup 해제를 추가했다. 최종 로컬 백엔드 전수 **3,017 PASS/446 조건부 환경 SKIP/10 subtests/실패 0**, 프런트 **55파일/304 PASS**·타입·운영 빌드 PASS다. 실제 PostgreSQL rolling 경쟁, Redis, Linux/cgroup/6언어와 외부 문제·일정·정책 승인은 아직 완료하지 않았고 운영 변경·배포·push는 하지 않았다.

2026-09-27 C03 공개 증명 게이트 후속: 관리자 기준 풀이의 `accepted` 완료를 코드·숨김 테스트·raw report가 없는 append-only 증명으로 같은 트랜잭션에 저장하고, 추적 문제 공개 시 현재 문제/대회/snapshot/출제/기준 풀이/정책/테스트 hash와 필수 언어 전체가 일치하는지 검사한다. 수동 검수만 한 경우, WA, 일부 언어 누락, 옛 snapshot은 공개되지 않으며 동일 문제 콘텐츠의 일정·배점 재저장은 허용한다. 민감 실행 payload/result 만료 뒤에도 증명은 유지된다. 집중 24 PASS/2 환경 SKIP, 관련 192 PASS/48 환경 SKIP, 현재 소스 백엔드 전수 **3,012 PASS/445 조건부 환경 SKIP/10 subtests/실패 0**, 프런트 **55파일/302 PASS**·타입·빌드 PASS. 실제 Linux/cgroup/PostgreSQL/Redis 실행과 외부 승인 조건은 여전히 미완료이며 운영 변경은 하지 않았다.

2026-09-27 R03/V01/V13 측정 합산 후속: 합산기가 종료 코드와 AC 이름만 믿지 않고, hardened host envelope(언어·모드별 감시 예산·경과 시간·정리 후 잔여 0·용량 증거)를 요구한다. 모든 compile/run AC 단계는 frozen contract의 CPU/wall 미만, memory/output 이하이고, 케이스 수로 계산한 job deadline과 최대 memory reservation이 계약과 일치해야 한다. 합성 경계 회귀 44 PASS; 기존 v2 다섯 언어 445단계는 자원 대조 PASS지만 새 cleanup envelope가 없어 최종 10회 자료에는 재사용하지 않는다. 설치 B++는 G/J 실패, 후보는 `imageAccepted=false`이므로 동일 승인 이미지의 여섯 언어×10회는 여전히 미완료다.

2026-09-27 실제 런타임 감시기 후속: 고정 240초가 순차 내부 마감 합계보다 짧던 문제를 고쳤다. 당시 mechanics/all 23개는 750초였고 PID 진단을 더한 현재 24개는 780초다. B++ 단독 150초, descriptor A–J 520초, 79-case 초안 842초, slow 비교 198초, B++ 진단 168초의 고정 상한을 사용한다. descriptor/초안/진단 아카이브도 정확한 SHA-256으로 묶었다. 동일 기존 이미지의 [원시 결과](evidence/judge-runtime-matrix-watchdog-r1-2026-09-27.json) SHA-256 `8c4ddc33f2d0dd1f544f9270274d526b1ffe9c347838dc9fb23af9316aebf94c`: 역사적 6언어 mechanics **23/23 PASS**, 46단계, 47.5초, timeout 없음, 정리 후 잔여 컨테이너 0개. 현재 harness는 별도 non-default Docker socket·daemon ID hash·outer harness hash와 모든 controller 입력의 사전 고정, owner-only workspace, exact child-create key allowlist가 없으면 Docker 실행 전에 실패한다. 로컬 관련 회귀 88 PASS. 후속 점검에서는 preflight가 모든 reference suite에 draft-v2 archive를 잘못 요구하던 회귀를 고쳐 `freshman`/`freshman-candidate`/`bpp-diagnostic`은 v1, draft/candidate는 draft-v2, slow는 slow-v2로 고정했다. 후보 소스/압축 ELF도 Docker 접촉 전에 고정하고 daemon ID 실패 때 이전 endpoint를 복원했다. mechanics에만 적용됐던 private/empty/exact workspace gate도 reference/draft/candidate/slow/diagnostic 전체가 compiler import 전에 공유한다. 이 후속 묶음의 독립 회귀는 46 PASS/2 Windows capability SKIP다. 이는 실행기 mechanics 재검증이며 A–J 여섯 언어 반복 성능, 최종 제한 승인, 실제 PG/Redis 워커 재시작, 전용 Docker daemon 격리를 완료한 증거는 아니다. 사용자는 별도 환경을 설정하지 않았고 운영 설정·데이터·배포·push도 없다.

2026-09-27 C11 미검수 차단 PostgreSQL 후속: 실제 C 최대 입력이 든 별도 PG-only 비공개 패키지 검사를 추가했다. 이 검사는 승인 메타데이터나 검수 이벤트를 만들지 않는다. 따라서 공개·일반 사용자 조회·참가·직접 제출이 모두 차단되고, 검수·참가자·대회 제출·실행 작업·점수 행이 0으로 남는지를 확인한다. 최대 입력은 정확히 3,000,019바이트이며 512 KiB 초과·16 MiB 미만으로 고정했다. [원시 결과](evidence/isolated-c11-private-package-negative-postgres-r9-2026-09-27.json) SHA-256 `6d3cb78d5be881650131d550f1279ae7cb017c3756ecee769dc06d06a9cb9785`, 소스 `287697c46b765452e4387c823fc121c4044a92b7932c201b929fbd9dadb4a627`, 하네스 `71cf5fa412d32a47eeecf5b89fe3a1f4dd0803badfbde94bba4433513ec649e5`, **380 PASS/1 Java 도구 SKIP**. 이는 실제 권리 근거 없이 성공 공개를 주장하지 않는 차단 증거다. 성공 흐름의 검수는 계속 테스트용 합성이며 실제 출처 허락·최종 A–J 승인, Redis·실제 Docker/cgroup 증거가 아니다. 잔여 스키마·컨테이너·임시 경로는 없고 운영 변경·배포·push 없음.

2026-09-27 C11 PostgreSQL 후속: 직전 C 최대 비공개 패키지 흐름을 SQLite와 명시적 임시 PostgreSQL 스키마에서 각각 실행하도록 확장했다. [원시 결과](evidence/isolated-c11-private-package-postgres-r8-2026-09-27.json) SHA-256 `820dda451bee7fa7401b608bb305c6794b0a5095a92332df9596d51a84fedfc0`, 소스 `dd92d30160d184cc74cb192b4064fd5ecff0f60134480e6699a291937cbea9f9`, 하네스 `71cf5fa412d32a47eeecf5b89fe3a1f4dd0803badfbde94bba4433513ec649e5`, **379 PASS/1 Java 도구 SKIP**. 새 변형만 실제 PostgreSQL 트랜잭션과 고유 `audit_contest_*` 스키마를 사용했고 실행 후 잔여 스키마·컨테이너는 없었다. 워커/채점은 합성이므로 Redis·실제 Docker/cgroup 증거가 아니며, 테스트용 검수는 실제 출처 허락·최종 A–J 승인이 아니다. 운영 데이터·설정·배포·push 변경 없음.

2026-09-27 C11 비공개 패키지 흐름 후속: C의 실제 3,000,019바이트 최대 입력을 별도 관리자 저장 데이터로 올리고, 그 참조가 든 비공개 패키지를 등록했다. 검수 전 공개 거절, 테스트용 정확한 내용 지문 검수, 공개, 멱등 재등록, 참가·제출·고정 접수·합성 워커 복원·점수판 500점까지 한 흐름으로 검사했다. 공개 응답에는 숨김 참조가 나오지 않았다. [원시 결과](evidence/isolated-c11-private-package-r7-2026-09-27.json) SHA-256 `652e749100b4cc728e5d259ff05564eeb4d7c815ff281e4aaa8bc17b37757322`, 소스 `ff51ae5949a008c6637664b463f35eedb193939b5f271813c3225271dd248564`, 하네스 `71cf5fa412d32a47eeecf5b89fe3a1f4dd0803badfbde94bba4433513ec649e5`, **378 PASS/1 Java 도구 SKIP**. 검수 근거는 테스트용 가상 자료라 실제 출처 이용 허락·최종 A–J 출제 승인을 뜻하지 않는다. SQLite fixture/합성 채점이므로 실제 PostgreSQL·Redis·Docker/cgroup·6언어 제한 수락도 별도다. 임시 경로·컨테이너는 확인 후 삭제했고 운영 설정·데이터·배포·push는 변경하지 않았다.

2026-09-27 C11 C/E/I 최대 입력 후속: C 3,000,019바이트, E 1,000,001바이트 2종, I 2,000,010바이트의 각색 입력 네 개를 지문 validator·기준 풀이로 확인하고 격리 HTTP 관리자 업로드→대회 생성→참가자 제출→고정 접수→합성 워커의 케이스별 복원→점수판까지 각각 검사했다. [원시 결과](evidence/isolated-c11-c-e-i-maximum-r6-2026-09-27.json) SHA-256 `6db8db520ad9df34032775349527130b6ce13a269182206dfa90edcd6d79d99c`, 소스 `738991aa1abf2a79af85ae3415fcfdddd11f3cb000360f93fb4a0e1352eff631`, 하네스 `71cf5fa412d32a47eeecf5b89fe3a1f4dd0803badfbde94bba4433513ec649e5`, **377 PASS/1 Java 도구 SKIP**. 이는 SQLite fixture/합성 채점으로, 최종 비공개 패키지 import·출처 승인이나 실제 PostgreSQL/Redis/Docker·6언어·자원 한도 수락이 아니다. 운영 데이터·설정·배포·push는 바꾸지 않았고 임시 자원은 검증 후 삭제했다.

2026-09-27 C11 C 최대 입력 통합 후속: 각색한 C 문제의 실제 3,000,019바이트 최대 입력을 오프라인 validator·기준 풀이로 다시 대조한 뒤, 격리 HTTP 관리자 업로드→대회 생성→참가자 제출→고정 접수→케이스별 저장 데이터 복원→점수판 500점까지 검사했다. 접수 뒤 원본 문제 테스트를 변경해도 접수의 참조가 유지됐고 공개 문제·점수판 응답에는 참조가 나오지 않았다. [원시 결과](evidence/isolated-c11-c-maximum-r5-2026-09-27.json) SHA-256 `91bb92f93f306f33c67a6f0babe9b7f1833ec69588769eb054c5a9823fd187fc`, 소스 `ad404aa5444964cbf11d358945654fa790a1ddca34de9256bfe99a969938d0a2`, 하네스 `71cf5fa412d32a47eeecf5b89fe3a1f4dd0803badfbde94bba4433513ec649e5`, **374 PASS/1 Java 도구 SKIP**. 이 검사는 SQLite fixture와 합성 채점 실행기이며 실제 PG/Redis/도커 채점기나 E/I 최대 입력, 최종 비공개 패키지 등록·공개 승인을 증명하지 않는다. 임시 컨테이너·경로는 검증 후 삭제했고 운영 변경·배포·push 없음.

2026-09-27 C11 등록 전송 후속: 운영자 설정 추가 없이 비공개 패키지의 정규 JSON 한도를 일반 API의 512 KiB로 일치시켰다. 도구·서버가 같은 alias 정규화 바이트를 세고, 배포 Nginx include에도 일반 요청 512 KiB를 명시했으며, API 직접 접속의 Content-Length 및 청크 초과도 등록 전에 413으로 거절한다. C/E/I 최대 입력 4종(약 1–3 MB)은 별도 16 MiB 업로드의 `stored-v1` 참조로 표현 가능함을 검증했다. [최종 격리 원시 결과](evidence/isolated-c11-package-r4-2026-09-27.json) SHA-256 `d405e699b5d2cacf3528ac48995cc2e47ca177ea5abd64f96502bd7939883a79`, 소스 `b088dfb6d250b008629a8269c1a98ae5604f2657b03e5d577073d3407c06c011`, 하네스 `71cf5fa412d32a47eeecf5b89fe3a1f4dd0803badfbde94bba4433513ec649e5`, **373 PASS/1 Java 도구 SKIP**. 첫 실행은 생성기 파일 누락으로 수집 실패([r1](evidence/isolated-c11-package-r1-2026-09-27.json)), 다음 실행은 350 PASS/1 SKIP([r2](evidence/isolated-c11-package-r2-2026-09-27.json)), 설정 파일 누락 1 FAIL을 고친 최종 실행 전 [r3](evidence/isolated-c11-package-r3-2026-09-27.json)도 보존한다. 이 회귀는 격리 Linux의 SQLite fixture/합성 채점이고 PostgreSQL은 임시 서비스로만 기동했다. 실제 C/E/I 업로드→최종 패키지→공개→채점, PG/Redis/실제 Docker 및 제한 승인 증거는 아니다. 소유 임시 경로·컨테이너는 검증 후 삭제, 운영 설정·데이터·배포·push 변경 없음.

2026-09-27 V17 출력 수집 후속: 기존 `/control` stdout/stderr 읽기·출력량 대조·산출물 전달을 `measured-collection-v1` 파일 SHA-256 `3929e47342808b38aa9b73a8fae4af51a37cce2934ea97521b7deea923cdf87e`로 고정했다. [격리 회귀](evidence/receipt-collection-v1-r1-2026-09-27.json) SHA-256 `6faead29d6c0f2372c6ff54067ff19febe8b60d19c5f6c1183f5c7a615fff128`, 소스 `59954fa126256fd4902fcef4f8d09a71368bf57aef772e1b0ee7d48a8dc019cb`, **313 PASS/1 Java 도구 SKIP**. [실제 Docker Python 경로](evidence/receipt-measured-pipeline-v1-2026-09-27.md)도 최신 소스 `5e8f4845ca984a64951d0962ae4eaa84c4e162a5747b9c06c802194731b6b69f`로 컴파일 1회·독립 2케이스 AC 재확인했다. 비동기 복구, 실제 과거 이미지/워커·PG/Redis 큐 재시작과 6언어·A–J 전체 V/C 수락은 남았다. 운영 변경·배포·push 없음.

2026-09-27 V17 실제 Python 경로 후속: 현재 코드 아카이브 `683a13c6c50b0c70833032fa61dfc6c9b9f19354b93e256eadbd848ce2275c3e`와 기존 이미지 `sha256:d7ab3494aad02142fe7fc4abee8175283a2ce68e57cfc7bb24da034753065930`로 [격리된 실제 Docker 채점](evidence/receipt-measured-pipeline-v1-2026-09-27.md)을 실행했다. 컴파일 1회·각각 새 컨테이너에서 케이스 2개 AC, 산출물 쓰기 차단·이전 케이스 경로 부재·잔여 작업/컨테이너 0개였다. 이는 단일 Python 앱 어댑터 확인이며 실제 과거 접수의 PG/Redis 워커 재시작 재생, 여섯 언어·A–J·반복 성능·제한 승인과 전체 V/C 수락은 아니다. 임시 자원만 삭제했고 운영 설정·데이터·배포·push 없음.

2026-09-27 V17 보고서 parser 후속: supervisor-record-v1 해석을 별도 SHA-256 `fdd5f1506d994ea3fab5282d8f540324a19065837117969ca0e23fa2ce4500d9` 파일로 고정하고, 컨테이너 규격 스냅샷의 parser를 선점 전에 검증하도록 했다. [격리 원시 결과](evidence/receipt-record-v1-r1-2026-09-27.json) SHA-256 `c28162ff8e7db2cc29737d8ddb94e6cbc3e188aef896751f7ee7788dc6bc6de0`, 소스 `60aa802683a5348bfe31708478bc08beeccc3b05c8cae0cf7052426eb3608a76`, **311 PASS/1 Java 도구 SKIP**. 이는 SQLite fixture/합성 Docker·채점 회귀다. 수집·타임아웃 흐름, 과거 이미지·워커 레인, 실제 PG/Redis/Docker 재시작 재생과 전체 V/C 수락은 여전히 남았다. 사용자 설정·운영 데이터·배포·push 변경 없음.

2026-09-27 V17 컨테이너 규격 후속: 기존 Docker 생성 옵션과 tmpfs 배치를 소스 해시 `c9031e0b100ddfdf9a2d839f268fa13ee1ffb2b90b67a313ea408ee259281f01`의 v1 모듈로 옮기고, 접수 프로필에 연결된 규격을 선점 전에 검증·스냅샷했다. [격리 원시 결과](evidence/receipt-container-v1-r1-2026-09-27.json) SHA-256 `f35e9d719cb295a224a21305e00dc165a82f338757a0f0f0fa209e48b541ccad`, 소스 `eb27e3caf1fa3e3de2c38a3fa3e79116b259ed82a7362d3ad8c44393c91b5e3c`, **310 PASS/1 Java 도구 SKIP**. 테스트는 SQLite fixture/합성 Docker·채점이며 보고서 parser·수집 흐름, 과거 이미지/워커 레인, 실제 PG/Redis/Docker 재시작 재생과 전체 V/C 수락은 남았다. 사용자 설정·운영 데이터·배포·push 변경 없음.

2026-09-27 V17 산출물 계약 후속: 기존 `bounded-tar-v1` 수집·해제 구현을 별도 고정 소스 파일(LF SHA-256 `10ffee31249f320ec10e0391cd91963324f42a004b07cc2c40e04d28e9d1dc4a`)로 이동하고, 선점 전 해시·일반 파일 검증과 스냅샷 선택을 추가했다. [격리 원시 결과](evidence/receipt-artifact-v1-r2-2026-09-27.json) SHA-256 `53dc0f47ee25679c9f6f251e3a11b0ba68fb9f4f327a808efb0da131a38a169d`, 소스 `1c508b8a57eb277bda2cb2eff24d79907ce2a2ddb396d4aaa842534c1dab9d03`, **307 PASS/1 Java 도구 SKIP**. 첫 실행의 오래된 테스트 경로 1 FAIL도 [보존](evidence/receipt-artifact-v1-r1-2026-09-27.json)했다. 이는 SQLite fixture/합성 Docker·채점 회귀이며 컨테이너 생성 규격·보고서 parser, 실제 과거 이미지/워커·PG/Redis/Docker 재시작 재생과 전체 V/C 수락은 남았다. 사용자 설정을 요구하거나 바꾸지 않았고 운영 데이터·배포·push도 변경하지 않았다.

2026-09-27 V17 실행 레시피 후속: 현재 6개 언어의 `(언어, toolchainProfile)`별 소스명·고정 명령·scratch 배치·산출물 계약을 지문으로 고정해 선점 시 보관한다. v2 replay-only 항목의 과거 어댑터가 빠져도 해당 작업은 대기·시도 0회이고 현재 프로필의 작업은 처리된다. [격리 원시 결과](evidence/receipt-toolchain-catalog-r2-2026-09-27.json) SHA-256 `9a1a36af3f0eab940d949fbcc6119f47fe42393c8d96b7f019920b20759dfba8`, 소스 `50476906c23194aa37277e6ef3d405d36f759f905a47ef16dc9ccdbf4b18a517`, **306 PASS/1 Java 도구 SKIP**. 테스트의 과거 프로필은 합성 fixture다. 실제 과거 레시피·이미지/워커 레인 보존과 PG·Redis·Docker 재시작 재생은 미완료이며 사용자 설정·운영 데이터·배포·push 변경 없음.

2026-09-27 V17 이미지 선점 후속: 실제 워커에서 등록된 로컬 Docker 이미지 ID를 같은 데몬에서 **큐 선점 전에** 확인하고, 없거나 다르면 해당 계측 작업을 시도 횟수 0의 대기로 둔다. 워커 클래스도 생성 시 고정했다. [격리 원시 결과](evidence/receipt-image-preflight-r2-2026-09-27.json) SHA-256 `4ec72d448f8a6deac2444307ddb0e5c751a500be56c69359ea801e1278177926`, 현재 소스 `a0f0eff536a21fd349a5865c92e5258ede1894374bac88f56b68b410ca25d3bd`, 10개 모듈 **301 PASS/1 Java 도구 SKIP**. Docker 조회는 테스트에서 모의했고 큐는 SQLite fixture다. 실제 과거 이미지/툴체인 보존과 PG·Redis·Docker 재시작 재생 수락은 남아 있다. 사용자 설정·운영 데이터·배포·push 변경 없음.

2026-09-27 V17 재생 후속: 과거 접수 기록에 묶인 런처를 정확한 해시의 보관 파일에서 선택하고, 새 접수를 차단하는 replay-only 등록과 선점 전 가용성 검사를 구현했다. [범위와 원시 증거](judge-receipt-replay-2026-09-27.md): 격리 Linux 10개 모듈 **297 PASS/1 Java 도구 SKIP**, 실패한 첫 실행(294 PASS/3 FAIL/1 SKIP)도 보존했다. 보관본이 없으면 해당 작업은 시도 횟수 0의 대기 상태로 두고 다른 작업을 처리한다. 테스트는 SQLite fixture/합성 채점기이며 과거 Docker 이미지·툴체인·워커 레인, 실제 PG/Redis/Docker 재시작 재생은 미완료다. 사용자나 운영 설정·데이터·배포·push 변경 없음.

2026-09-27 V18 HTTP 후속: 대회·일반 문제 제출 각각에서 클라이언트가 CPU/wall/메모리/PID/정책 필드를 덧붙인 10개 요청은 **422**, 실행 작업·제출 행 증가 **0**이었다. 같은 경로의 정상 요청은 202로 접수되고 서버 확정 프로필이 저장된다. 이 테스트를 포함한 [최신 격리 Linux 원시 보고서](evidence/recent-regressions-http-linux-2026-09-27.json) SHA-256 `8bdead8633b6d52a534d247783fdd1d2398e77fef760cf989d2fc7f023156a3b`: 현재 소스 SHA-256 `aa3e7adaa7a5a59a41b1bd7fc3e7bf368cb65c11d2108b1da1771322bdf0150b`, 실행 도구 `b219cff99888795e850631dfaa766ae32a9c62b8565c0132dbaa83b457a6f4be`, 9개 모듈 **230 PASS/1 Java 도구 SKIP, 19.52초**. 테스트 DB는 SQLite fixture, 실행기는 합성이므로 실제 PostgreSQL/워커/Docker 실행 제한을 증명하지 않는다. 정확한 임시 경로·컨테이너는 해시/소유권 확인 후 삭제했다. 운영 데이터·설정·배포 없음.

2026-09-27 최근 변경 회귀 묶음: [격리 Linux 원시 보고서](evidence/recent-regressions-linux-2026-09-27.json) SHA-256 `4c5fc02fc96e5453350dd6e539feeb702327de5701914c05e1bdb474c2e59ca4`. 현재 소스 묶음 SHA-256 `6a7af8318535924189549b4be38b67eac4a5c59f3fa33fb08578e32dd8199ab4`, 실행 도구 SHA-256 `b219cff99888795e850631dfaa766ae32a9c62b8565c0132dbaa83b457a6f4be`. 대회 API·계측 실행기·큐 워커·정책·테스트 묶음 경계·보호된 계측 기록·대회/일반 제출 자원 필드 주입의 9개 모듈을 `-k` 없이 실행해 **220 PASS/1 SKIP, 16.81초**였다. SKIP은 기존 테스트 이미지에 Java 도구가 없어 실행하지 않은 Java artifact round-trip 검사다. 테스트 클라이언트는 SQLite fixture/합성 실행기를 쓰며 임시 PostgreSQL 컨테이너가 실제 이 9개 검사의 DB를 대신했다는 뜻은 아니다. 원시 보고서 해시를 서버/로컬에서 대조했고 테스트 컨테이너·정확히 소유한 임시 경로가 남지 않았음을 확인했다. 호스트 Docker 데몬 공유, 실제 Java artifact/운영 DB·Redis·Docker 채점 수락, 전체 V/C 게이트와 최종 대회 정책 승인은 별도다. 운영 설정·데이터·배포·push는 변경하지 않았다.

2026-09-27 C11/V17 격리 HTTP·워커 후속: [기존 문제 편입 HTTP 원시 보고서](evidence/contest-boundary-http-2026-09-27.json) SHA-256 `355e51ebeb3815918890e15f64c7237f1d676dd4eb062d4c12d5df857248dea1`에서 201개·개별 16 MiB 초과 거절과 200개 허용을 한 테스트로 확인했다(1 PASS/16 제외). `validate_receipt`가 기접수 `jobDeadlineMs`를 **현재** 서비스 상한과 재비교하던 V17 위반을 수정해 접수 당시 단계 한도와 deadline을 유지한다. [고정 접수/워커 원시 보고서](evidence/frozen-receipt-retry-2026-09-27.json) SHA-256 `0b532c1e9b1129bbd8ef07b06d0aed54d76a27a12b52b17b9b0d1fb9e1a88398`에서 7초 접수 후 설정 6초로 변경해도 워커가 고정 7초를 사용하며 실행 단계에 도달함을 확인했다(2 PASS/103 제외). 두 실행 모두 기존 이미지·네트워크 없음·임시 DB/소스만 사용했고 테스트 컨테이너·임시 경로는 확인 후 삭제했다. PostgreSQL 컨테이너는 테스트 하네스의 임시 서비스이고 **HTTP 검사는 SQLite fixture, 워커 검사는 모의 실행기**를 사용했으므로 실제 PG/Redis/Docker 재시작·cgroup 수락으로 해석하지 않는다. 호스트 Docker 데몬 공유 한계도 그대로다. 운영 설정·데이터·대회·배포 변경 없음.

2026-09-27 C11 기존 문제 편입 후속: 신규 `ProblemCreate` 검증을 우회하는 **기존 공개 문제 ID 선택** 경로도 대회 저장 전에 공통 `canonical_suite`로 검증하도록 연결했다. 문제/대회 원본은 수정하지 않고, 스냅샷의 200/201개 및 개별 16 MiB 초과를 검증하는 관리자 HTTP 회귀를 작성했다. 로컬에서는 경로·테스트 구문 검사와 종전 순수 집중 78 PASS를 확인했지만, Windows에 SQLAlchemy 등 백엔드 의존성이 없어 새 HTTP 회귀 자체는 아직 실행하지 못했다. 따라서 C11의 전체 API/DB 통과나 실제 Linux 실행을 완료 처리하지 않는다. 운영 데이터·설정·배포 없음.

2026-09-27 V06/V08/V18 로컬 후속: 보호된 단계 기록 파서를 실행기/Docker 의존성 밖의 순수 모듈로 분리해 기존 호출에서 그대로 사용한다. OOM kill 증가 없이 `memory_limit_exceeded`를 주장하는 기록은 거절하며, 정상·TLE·OLE·OOM 및 모순/누락 계측 로컬 계약 검사를 통과했다. 일반 문제와 대회 제출 모델은 클라이언트의 CPU/wall/메모리/PID/정책 필드를 **422 유효성 검사 단계에서 거절**하도록 고정했다. 유효한 대회 `requestId` 별칭은 유지된다. 새/기존 순수 로컬 집중 **78 PASS**, 구문 검사 PASS. 이는 실제 FastAPI→DB receipt→cgroup 경로 검증이나 Linux 커널 OOM 재현을 대신하지 않으며, 해당 V/C 게이트는 계속 미완료다. 운영 서버 설정이나 배포 변경 없음.

2026-09-27 로컬 경계 검증 후속: 문제 생성 모델과 채점 정책 해시가 동일한 1–200개/개별 데이터 16 MiB/전체 데이터 256 MiB 규칙을 사용하도록 연결했다. 빈 비공개 초안은 계속 허용한다. 순수 로컬 경계·정책 테스트 53 PASS. V06/V08의 보호된 보고서는 `memory_limit_exceeded`라고 하면서 OOM kill 증거가 0인 모순을 거절하도록 보강했다. 해당 회귀 테스트는 작성했으나 현재 Windows Python에 `pydantic_settings`가 없어 수집 전 차단됐으므로 실행 통과로 세지 않는다. 이는 C11의 등록 경계와 V06/V08의 일부 코드/로컬 증거일 뿐 실제 Linux·전체 API/DB/운영 수락은 아니다. 사용자 추가 설정이나 운영 변경 없이 수행했다.

2026-09-27 v2 B++ 후보 후속: [별도 후보 원시 결과](freshman-draft-measurements-2026-09-27.md)에서 수정 ELF·표준 라이브러리를 컴파일 단계에만 읽기 전용 적용해 A–J 10/10, 79/79 AC, 89단계/잔여 0이었다. 후보 산출물 해시를 실행 단계에 묶었지만 기존 이미지의 설치 컴파일러는 여전히 G CPU TLE/J CE다. 후보는 이미지에 설치되거나 운영 채점기에 등록되지 않았고, 다섯 언어 성공 합산과 합치지 않는다. 전송·격리 비교·임시 정리만 했으며 운영 설정·데이터·배포·push 없음. 최종 설치 이미지, 반복·부하/DB/프록시/외부 V/C 수락은 남아 있다.

2026-09-27 v2 여섯 언어 첫 실행 후속: [동일 도구 해시에 묶인 원시 증거](freshman-draft-measurements-2026-09-27.md)에서 Python·C·C++·Java·JavaScript 각각 A–J 10/10, 79/79 AC, 89단계/잔여 0이다. 성공 합산은 `recordCount=50`, `tenPassDatasetComplete=false`, `policyApproved=false`. **설치 B++은 8/10: G CPU TLE, J GC 심볼 CE**로 실패 원본을 별도 보존해 성공 합산에서 제외했다. 이전 Python 원본은 측정 스크립트 해시가 달라 엄격 합산이 거절되었고, 현재 스크립트로 새 Python 실행을 보존하여 합산했다. J 최대 긴 블록의 독립 기대값 오라클 1 PASS도 추가했다. 수정 B++ 후보 v2·최종 설치 이미지·모든 언어 2–10회 반복·최종 제한/출제 검수와 나머지 V/C는 아직 수락 전이다. 운영 설정/등록/배포 없음.

2026-09-27 출제 데이터 v2 후속: 첫 78개 [v1 초안](../tools/freshman_contest/corpus-manifest-draft-v1.json)은 이전 실측 재검증을 위해 그대로 보존하고, I의 최대 1000×1000 다중 시작점 사례를 추가한 [79개 v2 초안](../tools/freshman_contest/corpus-manifest-draft-v2.json) (`sha256:e5213ca9d1aaf3691c91db22aa021870b532b653c015c58c4bf90fff8a8539fc`)을 별도로 고정했다. F/I/J의 별도 정답-느림 풀이 3개는 작은 입력 기능 비교 7검사 통과, 최대 입력의 독립 기대값 검사와 함께 오프라인 집중 **39 PASS/1 Windows symlink SKIP**. [v2 Python 실제 격리 첫 실행](freshman-draft-measurements-2026-09-27.md)은 A–J 10/10·79/79 AC·89단계/잔여0이며 새 I 사례 CPU 2.628초다. 별도 [F/I/J 빠른/느린 풀이 첫 격리 비교](freshman-draft-measurements-2026-09-27.md)도 각 동일 입력에서 빠른 풀이 3 AC/느린 풀이 3 CPU TLE·12단계/잔여0을 확인했다. 이는 진단용 상한의 단일 실행 분리이며 다른 언어의 v2 실측·10회 반복·최종 제한 승인 등 전체 수락은 남아 있다. v1 통과 결과를 v2에 합산하지 않는다.

2026-09-27 v1 여섯 언어 첫 실행 후속: 같은 78입력에서 Python·C·C++·Java·JavaScript는 각 10/10·78/78 AC, 설치 B++은 G CPU TLE/J CE였다. 수정 B++ 후보는 컴파일 단계에만 읽기 전용 적용해 78/78 AC였지만 설치 이미지 수락이나 배포가 아니다. [실측 기록](freshman-draft-measurements-2026-09-27.md)에 각 원시 보고서의 해시와 임시 자원 정리를 남겼다.

2026-09-27 실제 초안 Python 첫 패스: [격리 원시 측정·실패 원인 보고서](freshman-draft-measurements-2026-09-27.md). 초기 10초/사례 진단 wall은 B/J 12사례의 총 기한 135초가 기존 서비스 상한 120초를 넘어 **실행 전 거절**됐다(8/10, 원시 실패 보존). 서비스 상한은 유지하고 초안 전용 진단 wall만 8초/사례로 조정한 재실행은 **Python A–J 10/10, 78/78 AC, 88단계 컨테이너, 잔여 0**이었다. 원시 보고서/manifest 해시 검증과 임시 서버 경로 정리 완료. 이 한 번은 다른 다섯 언어·10회 반복·느린 풀이/제한 승인·DB/워커·별도 Docker 데몬 격리 수락이 아니다.

2026-09-27 고정 초안 측정 연결: [78개 초안 manifest](../tools/freshman_contest/corpus-manifest-draft-v1.json)의 최신 해시는 `sha256:12f0c6f989b9736b0f5784fe29de2400b7cf06bc71d63330629f74a24d20b764`이다. 공개 예제 본문도 함께 고정했고, 새 `freshman-draft`/`freshman-draft-candidate` 격리 경로와 전용 아카이브(sha256 `1021333d2822e4849e887e0e4b1847717925918bc1b183f822e4aec18c83020a`)·결과 합산의 해시/사례/출처 격리 검사를 추가했다. 오프라인 집중 **35 PASS/1 Windows symlink SKIP**, 이전 descriptor 합산 21검사 포함. 새 경로의 실제 Linux 채점·6언어 반복 측정은 **미실행**이며 기존 31사례 실측을 대신하지 않는다.

2026-09-27 출제 데이터 후속: [오프라인 출제 자료](../tools/freshman_contest/README.md)에 누락 경계용 A–I 보충 생성기와 `corpus-manifest-draft-v1.json`을 추가했다. 지문 예제 26개+숨김 후보 52개=78개를 해시/바이트 수/소속으로 고정했고, B 216개 순서 있는 세 값은 **로컬 전수 기능 검사**로만 다룬다(채점 묶음에는 대표 6개). 현재 Windows에서 의존성 없이 실행한 보충/manifest/Python 기준 풀이 회귀 8 PASS, Python은 초안 78/78 기능 정답이다. 이는 기존 31개 descriptor의 여섯 언어 Linux 첫 패스와 다른 입력 묶음이며, 최종 검수·여섯 언어 실측·10회 반복·제한 승인·운영 등록을 완료한 증거가 아니다.

2026-09-27 API 준비 상태 후속: [격리 PG·Redis·Uvicorn 검사](judge-postgres-integration-2026-09-27.md) **1 PASS/40.81초**. 워커 SIGKILL 직후 `/ready`가 200으로 남는 30초 heartbeat 지연을 실제 재현했고, 만료 뒤 503·새 워커 뒤 200·정상 종료 뒤 503을 확인했다. 이 유한 지연은 운영 수용 판단이 필요하며, 실제 Docker 실행기/공개 프록시 failover 검증은 남아 있다.

2026-09-27 관리형 워커 후속: [격리 PG·Redis 실제 `app.worker.serve()` 프로세스 검사](judge-postgres-integration-2026-09-27.md) **1 PASS/7.57초**. 첫 프로세스 SIGKILL 후 새 epoch/Redis 소유권, 만료 작업 1회 회수, 이전 토큰 거절, SIGTERM drain/stop과 Redis 준비 상태 해제를 확인했다. `build_worker`·`health_loop`의 Docker 부분은 시험용으로 대체했으므로 실제 sandbox/proxy 수락은 아니다. SIGKILL 직후 API 상태는 위 r3/r4에서 별도로 확인했다.

2026-09-27 `ExecutionWorker` 후속: [격리 PostgreSQL 두 워커 프로세스 검사](judge-postgres-integration-2026-09-27.md) **1 PASS/6.90초**. 첫 `ExecutionWorker.run_once()`가 작업을 맡고 시작한 뒤 SIGKILL; 새 프로세스가 같은 작업을 회수·완료, 이전 토큰으로 덮어쓰기 불가. 가짜 실행기/풀을 사용했으므로 `app.worker` 서비스·Redis 준비 상태·실제 Docker 채점 복구와 구별한다.

2026-09-27 프로세스 복구 후속: [실제 PostgreSQL 격리 검사](judge-postgres-integration-2026-09-27.md)에서 별도 큐 claimant를 SIGKILL한 다음 새 Python 프로세스로 회수·완료하는 검사 **1 PASS/5.84초**. 이전 토큰·중복 완료는 거절, 실제 DB 행·시도 횟수 확인. 이는 큐 API 복구의 부분 증거이며 `app.worker`·Redis·Docker sandbox 복구의 증거가 아니다.

2026-09-27 실제 DB 후속: [격리 PostgreSQL 검사](judge-postgres-integration-2026-09-27.md) **28 PASS/37.63초**, 운영 DB·네트워크·Redis 연결 없음. 새 대회/재채점 12개와 기존 큐/마이그레이션 검사로 마감 접수·중복 득점·동시 반영/반려·감사 보존을 실제 DB에서 확인했다. 첫 19PASS9FAIL은 테스트 DB 인코딩과 FK fixture 순서 문제로 보존하고 수정 후 재실행했다. 로컬 관련92PASS12명시PGSKIP. **실제 워커 프로세스 강제 종료/재시작·프록시 통합 수락은 별도로 남는다.**

2026-09-27 A–J 후보 실측: [B++ 후보 별도 검사](bpp-candidate-reference-measurements-2026-09-27.md)에서 원본 기준 풀이 10개/최대·경계 입력 31개 모두 AC, 컴파일 10회+개별 실행 31회/잔여 0개. 이전 G TLE/J CE가 같은 입력에서 해소됐다. 후보는 읽기 전용 컴파일 연결로만 사용했고 실제 설치 이미지는 변경하지 않았다. 기존 이미지 측정과 혼합 집계하지 않는다. 집중166 PASS/9.53초. **V01의 후보별 부분 증거이지 최종 6언어/전체 출제/10회 반복/DB 워커 수락이 아니다.**

2026-09-27 최종 B++ 후속: 후보의 stage1/stage2 ASM·ELF 전체 동일성 및 stage2 실제 Linux 8개 회귀(native O0/O1 큰 배열, native/SSA O0/O1 GC, G/J 작은 입력) 통과. [원시 결과와 경계](bpp-compiler-candidate-2026-09-27.md) 참조. 첫 ELF 파일명 1바이트 차이는 실패 기록을 보존하고 동일 NASM 입력 경로에서 실제 재빌드하여 해결했다. 기준 풀이/생성 ASM 수정 없음. 101 로컬 집중 검사 통과. **최종 설치 런타임과 전체 A–J/반복 측정 수락은 아직 남았다.**

2026-09-27 B++ 후속: [고정 후보](bpp-compiler-candidate-2026-09-27.md)의 stage0 실제 Linux 빌드와 native-O1 네 검사(큰 지역 배열, 포인터 GC, G/J 작은 원본 입력)가 통과했다. 이전 100 CPU초는 전체 빌드에 부족했으며 실제 컴파일 CPU는 320.843초였다. G/J 전체 입력, 최종 설치 런타임, 자기 컴파일 고정점과 반복 성능 측정까지 통과했다는 뜻은 아니다. 해당 나머지 수락 조건과 전체 V/C 범위는 유지한다. 운영 pin/이미지/데이터 변경 없음.

v20 최종 화면 확인: 프런트 전체 **286 PASS/51파일**, 타입/빌드 **PASS**, 실제 Edge **18 PASS/24.1초**(API 모의, 320/768/1440px). 직접 확인한 작은 화면 내부 입력칸 넘침을 수정했고 각 입력 요소의 카드 내 배치도 검사했다. 정정본 출제 검수 연결 및 감사 화면은 구현됐으며 아래 오래된 버전의 미구현 표기보다 이 후속이 우선한다. 전체 V/C 수락이나 실제 외부 승인까지 완료한 것은 아니다.

2026-09-27 v20 후속: [재채점 검증 기록](contest-rejudge-verification-2026-09-26.md)의 정정본 검수 연결을 구현했다. 후보 자체의 고정 메타데이터/테스트/정책 지문에 네 범주 승인·반려를 추가하고, 미리보기 해시 및 잠금 안의 반영과 정확한 승인 이벤트 감사 기록으로 연결한다. 과거 기록의 NULL 근거는 만들어 채우지 않는다. 백엔드 관련 111 PASS/4 외부 환경 SKIP, 추가 워커/정책/프로브 164 PASS/1 SKIP, 새 동시 반려·반영 포함 검수 전용 15 PASS이며 서로 합산하지 않는다. 관리자 화면/합성 API 브라우저 검증 후 작은 화면 내부 입력칸 보완을 진행 중이다. 전체 목표의 실제 PostgreSQL/재시작, 과거 해결 출처, 대규모 묶음, 최종 실측·외부 승인은 여전히 남았다.

2026-09-27 v21 후속: [재채점 검증 기록](contest-rejudge-verification-2026-09-26.md)에 결정적 캠페인 분할을 추가했다. 제출 1,000건/소스 64 MiB 이하 shard, 전체 제출 집합/경계 manifest, 완료 결과 receipt, 모든 shard 성공 gate를 두고 점수판·점수 ledger·감사는 캠페인 전체를 한 트랜잭션에서 한 번만 반영한다. 이전 형식은 NULL 필드를 만들어 채우지 않고 기존 경로로 읽는다. 로컬 집중 **64 PASS/1 환경 SKIP**, 프런트 **296 PASS/54파일**·타입·빌드 PASS다. 실제 PostgreSQL/프로세스 재시작/운영 규모 1,001건 이상/6언어 Linux 재채점 수락은 남아 있으며 운영 변경은 하지 않았다.

같은 날 [B++ 수정 후보 검사](bpp-compiler-candidate-2026-09-27.md): 후보와 기존 소스 모두 전체 frontend가 100 CPU초에 도달했다. 구 소스의 빈 main 분석은 1.873초, 단일 compiler.annotations import는 62.154초에 완료되어 입력 크기/분석 비용의 영향을 확인했다. 빌드 성공/무한 반복 어느 쪽도 단정하지 않는다. G/J 수정 런타임은 여전히 미수락이다. 원시 보고서 보존 후 모든 해당 임시 서버 복사본을 정리했고 기존 서비스 7개 healthy를 확인했다.

2026-09-27 보강: [B++ G/J 원인 및 빌드 회귀](bpp-runtime-regressions-2026-09-27.md). 구 Linux 컴파일러의 부족한 지역 스택 예약과 포인터 GC 심볼 누락을 실제 최소 코드로 재현했다. 새 런타임 빌드에 필수 회귀를 연결했고 기존 이미지의 실패 차단을 확인했다. 수정 컴파일러 pin/이미지 수락은 미완료이며 현재 pin의 신규 빌드는 의도적으로 차단된다. 집중258 PASS/12 조건 SKIP/10 subtests, 운영 변경 없음. 이전 여섯 언어 58/60 결과를 전체 통과로 바꾸지 않는다.

작성일: 2026-09-26
상태: **구현 진행 — 부분 회귀 검증 및 격리 cgroup OOM 확인, 전체 V/C 수락 전**
범위: `freshman-contest-plan-2026-09-26.md`와 `judge-language-limits-references-2026-09-26.md`를 구현·검증 단위로 풀어 쓴 문서다. 이 문서는 대회 등록, 공개, 날짜 변경, 배포, 운영 부하 시험을 수행하지 않는다.

## 1. 읽는 방법과 증거 규칙

최신 A–J 실제 첫 실행: [문제별 런타임 측정](freshman-reference-measurements-2026-09-26.md). A–I23/J8 입력과 60개 기준 소스를 Linux에서 실행했다. 다섯 언어는 각각10/10문제·31입력 AC, B++은8/10이며 G CPU TLE/J CE가 남았다. 총238단계 컨테이너, 잔여0, 원시 보고서6개를 보존했다. J의 포인터 매개변수 GC 심볼과 일치하는 이후 compiler 수정 후보를 찾았지만 적용 수락 전이다. 로컬 도구/corpus/기존 실행기 회귀250PASS. **이전23개 기본 검사 통과는 이 실제 문제 실패를 해소하지 않는다.** 최소10회·느린 풀이·최종 데이터·DB/워커/나머지 V/C와 외부 승인은 여전히 남았다.

최종 후속 결과: 검증기를 강화한 실제 격리 재실행 **23/23 PASS/46단계**. [원시 JSON](evidence/judge-runtime-matrix-2026-09-26.json)에 CPU/wall/OOM/출력·종료 코드 증거와 소스/스크립트 해시를 보존했다. 테스트 도구의 네트워크·swap·마운트 등 생성 전 조건도 확인한다. 최종 백엔드 집중 **307 PASS/5 환경 SKIP/34.91초**, Edge 전체 **18 PASS/22.6초**(API 모의)다. 모든 검사 프로세스 종료 및 네 개 원격 임시 복사본 제거를 확인했다. 컨트롤러는 신뢰된 Docker 소켓 사용자이며 별도 daemon 경계가 아니다. 실제 A–J 반복 성능·DB 워커 재시작 등 남은 수락 범위는 줄이지 않는다.

최신 격리 실행 후속: [여섯 언어 실행 기록](judge-runtime-matrix-2026-09-26.md). 실제 B++ 컴파일 임시 경로 오류를 재현하고 동일 scratch 예산 안의 단계별 마운트/버전 구분으로 수정했다. 최종 6언어 AC/WA/CE 및 Python CPU/wall/MLE/OLE/exit137 **23/23 PASS**, 서로 다른 단계 컨테이너 46개, 잔여 0개다. A–J 성능·DB 워커 재시작·전체 V/C 수락은 아니다. 반영 후 감사 비교 화면도 추가하여 프런트 전체 **272 PASS/50파일**, 타입/빌드 PASS, 해당 Edge 흐름 **3 PASS**(API 모의)를 확인했다. 이후 전체 E2E와 백엔드 결과는 후속 기록에 따로 남긴다.

최신 v19 후속: [재채점 검증 기록](contest-rejudge-verification-2026-09-26.md). 후보 생성/비교/확인 반영/폐기 UI와 쓰기 없는 점수 미리보기 API를 연결했다. 일반 해결 근거·후보 결과가 검토 후 바뀌면 해시 재계산으로 반영을 거절한다. 같은 시각 근거 선택의 UUID 의존, 참가 기록 누락 시 숨겨지는 점수 변경, 후보 완료 시각 확인 누락을 수정했다. 백엔드 집중 **78 PASS/1 환경 SKIP**, 프런트 전체 **264 PASS/49파일**, 타입/빌드 PASS, 실제 Edge **18 PASS**(API 전부 모의). 반영 후 감사 비교 UI, 과거 근거 검수, 출제 검수 연결, 큰 대회 분할과 실제 PG/재시작/6언어 수락은 여전히 남았다. 아래 이전 버전의 미구현 표기는 그 시점의 기록이다.

재검사 후속: JavaScript 실패 입력 진단을 추가한 뒤 전체 예제 검사는 기존 2초 제한으로 통과했다(10.27초). 빈 Node 실행 20회도 통과했다. 이전 간헐 시간 초과의 원인은 아직 확정되지 않았고, 분리된 통과 결과를 단일 전체 실행 통과로 합산하지 않는다. 재채점 후속 보고서에 최초 실패와 회복 결과를 함께 보관했다.

최신 v18 후속: [재채점 검증 기록](contest-rejudge-verification-2026-09-26.md). 후보 큐 처리, 별도 명시 반영 API, 삭제되지 않는 해결 근거, 전후 순위/원래 계측 감사 기록과 공개 정정 안내를 구현했다. 관리자 이력 페이지 이동/권한 상실 정리/계정 전환 보호를 검증했다. 프런트 247 PASS/47파일, 타입/빌드 PASS, 모의 API를 쓰는 실제 Edge 15 PASS다. 전체 백엔드는 2547 PASS/414 SKIP/8 subtests와 기존 언어 예제 시간 초과 4건으로 끝났으며 전체 PASS가 아니다. 분리 검사에서 B++/Python은 통과, JavaScript 시간 초과는 재현되어 추가 확인 중이다. 재채점 작성/명시 반영 UI, 과거 출처 검수, 출제 검수 연결, 대규모 분할 반영과 실제 PG/6런타임 수락은 아직 남았다. 아래 이전 버전의 '재채점 미구현'은 당시 기준선이며 최신 후속과 구분한다.

최신 v16 후속은 [대용량 데이터 연결 기록](judge-test-data-storage-2026-09-26.md)에 정리했다. 참조를 작성/대회 사본/정책 지문/접수/예약/워커와 관리자 업로드 UI·CLI에 연결했다. 약 9 MB SQLite/ASGI→새 워커 통합은 실행기 모의이며, 별도의 실제 Linux SQLite→복원→Python 어댑터는 1회 컴파일/2개 fresh cases/입력 회수/잔여 컨테이너 0을 확인했다. 둘을 합쳐 실제 DB 워커 재시작 수락이라고 부르지 않는다. 프런트 234 PASS/45 files, 타입·빌드 통과; 실제 Edge 12 PASS(API 모의)다. 전체 백엔드 최종 재검사 결과는 후속 기록에 남긴다. 아래 v15/v16 초기 숫자는 이전 기준선이며 합산하지 않는다. 운영 등록·배포는 하지 않았다.

이 문서의 `수락`은 구현 파일이 존재한다는 뜻이 아니다. 아래 네 경로를 모두 만족하고, 기록 가능한 결과가 남아야 한다.

| 구분 | 의미 | 허용되는 증거 |
| --- | --- | --- |
| 코드/연결 | API·DB·큐·워커·실행기·화면의 계약과 연결을 구현한다. | 소스 검토, 타입/스키마 검증, 단위·통합 테스트 |
| localfake/SQLite | 가짜 실행기와 격리 DB로 UI·권한·점수·멱등성·큐 상태를 검증한다. | 테스트 로그, 요청/응답, DB 전후 스냅샷 |
| realLinux | 실제 Linux Docker/cgroup 및 제공 런타임으로 자원·프로세스·정리 동작을 검증한다. | 커널/cgroup, 이미지 digest, 런타임 버전, CPU·wall·메모리·OOM·프로세스 트리·정리 로그 |
| 승인/외부 | 사용자 결정, 원문·이용 조건, 운영·보안 승인이다. | 승인자·일시·대상 버전·링크·변경 이력 |

전체 수락 체크는 아직 `[ ]`로 남긴다. 초기 문서 작성 이후 진행한 부분 검증은 아래 최신 진행표와 별도 실험 기록을 기준으로 한다. 계획서의 예제 계산이나 모의 채점은 실제 언어별 자원 검증을 대신하지 않는다.

### 1.1 최신 부분 구현·검증 (2026-09-26)

최신 후속: [자원 측정 기록 검증](judge-metrics-verification-2026-09-26.md). v15 단계별 보호 보고서의 영속 저장, 공개 합계/최대값과 관리자 상세 분리, 원자적 점수/결과 반영, 공개·새 접수의 정적 운영자 등록부 대조를 추가했다. Java Unicode 산출물과 이식성 충돌 검사도 보완했다. 실제 격리 Python 연결 재검사와 로컬 Java 한글 클래스 roundtrip이 통과했다. **실시간 워커 준비 상태·다언어 Linux 수락·재채점은 아직 아니다.** B++ A–J 기준 소스도 완성해 로컬 Windows에서 A–I114/J90개 기능 비교를 통과했다. 여섯 언어 소스가 있다는 것과 여섯 언어의 대회 자원 정책이 검증됐다는 것은 다르다.

추가 진행: [비공개 패키지·출처 검수](contest-authoring-workflow-2026-09-26.md). v14 추가형 테이블, 관리자 전용 원자적 등록, 정확한 내용으로 멱등 재시도, 일정 편집 후 연결 갱신과 삭제 보존, 기본 검증 전용 CLI, 콘텐츠 지문에 묶인 4범주 검수 및 관리자 패널을 추가했다. 기존 공개 문제 호환성은 유지한다. 전체 백엔드 **2391 PASS / 410 환경 skip / 8 subtests**, 203.54초. J 오답군 6종이 포함되며 별도 테스트 수와 합산하지 않는다. 새 화면의 실제 Edge 320/768/1440px 6개 검사(기존 정책 3개+출처 패널 3개)가 통과했고 스크린샷을 검토했다. 브라우저 API는 전부 모의 응답이며 운영 등록·실제 검수 승인이 아니다. 프런트 최종 보완·통합 결과는 아래 후속 기록으로 갱신한다.

이번 후속 구현: [감독 실행기 및 실제 Python 연결 검증](judge-measured-launcher-verification-2026-09-26.md). compile-once/fresh-case, 정확한 런타임 등록부, 실행기 해시 고정, CPU/wall/peak/OOM 수집·자식 UID 격리·트리 회수, 취소 중 파일 수집 완료 대기, tar 산출물 검증, 접수 deadline을 연결했다. 실제 격리 Linux 7사례 및 Python 1회 컴파일/2케이스가 통과했다. 다언어/전체 DB 워커 수락은 아니다. standalone Python A–J도 추가하여 A–I156/J90 기능 비교를 통과했다. 최종 전체 회귀는 아래 최신 묶음 결과에 기록했고, 부분 실행 숫자와 합산하지 않는다.

추가 진행: v16 `judge_test_data`의 관리자 전용 UTF-8 불변 저장 참조를 문제 출제 API, snapshot, 큐, 워커, 자원 예산, UI, CLI, proxy 소스에 연결했다. 최종 백엔드 2522 PASS/414 환경 skip/8 subtests(263.00초), 프런트 234 PASS/45 files, 타입/빌드 통과. 격리 기존 Nginx 이미지에서 API/edge/frontend/외부 ingress 설정 4종 문법도 통과했다. 실제 전체 프록시 HTTP 경로·PostgreSQL·최악 외부 RSS·여섯 런타임 수락을 대신하지 않는다.

| 범위 | 구현/증거 | 남은 조건 |
| --- | --- | --- |
| 정책 저장·고정 (C08–C11 관련) | v12 정책 저장·snapshot/접수 고정·단조 revision, v13 자원 예약. v15 이후 API의 공개/새 접수에서도 정적 운영자 등록부와 모든 프로필을 대조한다. 동일 요청 재시도는 기존 접수를 보존한다. SQLite 접수 재시도·원본/일정 변경·반복 마이그레이션·rollback 회귀 통과. | PostgreSQL 실제 실행, 실시간 워커 준비 상태 gate·재채점 감사 이력 |
| 자원 예약·작업 선택 (R07 관련) | [자원 예약 기록](judge-resource-scheduling-2026-09-26.md): peak-stage 메모리+외부 여유분, CPU 배정량, daemon별 영속 상한, 등급 선택/FIFO, 재시작·미확정 Docker 작업 예약 유지. 큐·워커·대회·정책·마이그레이션 묶음79 PASS/39 PG skip. | 실제 Linux/PG 경쟁·혼합 메모리 부하, 감독 실행기의 동일 배정 적용, 물리 호스트/daemon 관계 검증, 승인된 운영 예산·변경 도구. 현재는 호스트당 하나의 daemon 전제 |
| 정책 UI | 일반/대회 문제의 선택 언어별 제한표, 관리자 원본 JSON 가져오기/검토, 정책 보존·미측정 공개 경고. 실제 Edge320/768/1440px 정책 입력 3 PASS, 스크린샷 검토·레이아웃/잘못된 JSON/복수 편집기 ID 확인. | 실제 API와 측정 보고서 import/실행 end-to-end (브라우저 검사는 API 모의 응답) |
| 판정/측정 (V06/V07/V09/V11 관련) | [초기 OOM 실험](judge-isolated-probe-2026-09-26.md) 및 [감독기/앱 연결 실험](judge-measured-launcher-verification-2026-09-26.md): 실제 7가지 감독기 사례. v15 보호된 compile/case 보고서 영속화·고정 프로필 보관·공개 총합/최대와 관리자 상세 분리. 실제 Python 1compile/2freshcase에서 내부 보고서/공개 합계 연결을 재확인. | 다언어/동시 사건/실제 DB 워커 복구·정리의 end-to-end, 부모 감독기 자체 OOM과 할당 실패 원인, 최악 overhead |
| A–J 출제 패키지 (V01/V02 관련) | 여섯 언어 standalone 소스와 Python validator/generator. C/C++ A–I148/J89, Java A–I156/J89, JS/Python A–I156/J90, B++ A–I114/J90 기능 비교. B++은 Windows 명시 도구를 사용하며 일부 최대 입력 포함. A–I18개/J6개 오답 mutant와 반례를 검출했다. A–I에는 지연 생성 23개 최대·적대 descriptor와 standalone Python 전건 순차 기능 회귀가 추가됐다. | 실제 Linux 6언어 반복 측정, J를 포함한 검수된 전체 최대 입력 package/manifest, 난이도·출처/이용 조건 승인 |
| 비공개 등록·검수 (C01/C02/C05/C11의 일부) | 원자적 패키지 등록·동시 재시도·실패 롤백·날짜 편집/삭제 후 영수증 회귀, 관리자 출처/검수 API·4범주 gate·지문 변경/반려/중복 요청 회귀, v14 반복 초기화, 명시 적용 CLI. 관리자 패널 실제 Edge3폭 검사, 모든 API 모의. | 메타데이터 변경 전체 감사 원장, 공개 후 개정/재채점, 실제 6언어 완성 manifest, PostgreSQL 경쟁 실행과 운영 등록 승인. 검수 JSON/해시만으로 실측·이용 허락을 인증하지 않음 |
| 최신 묶음 결과 | v15 측정·정적 등록부·Unicode 산출물·B++A–J 포함 backend 전체 **2443 PASS/414 환경 skip/8 subtests**, 278.45초. 명시한 Windows B++ 도구를 실제 사용했다. 프런트 **42파일221 PASS·타입 검사·빌드 통과**. 최종 Edge **9 PASS**, 11.0초(320/768/1440px, API 모의), 2열 지표 화면 스크린샷 검토. 별도 부분 테스트 수를 전체에 합산하지 않는다. | Linux pinned 의존성/PG/6언어 실제 채점 end-to-end 검증은 별도. skipped를 통과로 간주하지 않음. |

중요: measured-v1 감독 실행기를 연결했지만, 운영 등록부가 없거나 고정된 이미지·런타임·도구·실행기 해시가 맞지 않으면 명시적으로 거부한다. 기존 실행기로 계약을 무시하고 흘려보내지 않는다. 실제 확인은 격리 Python 연결까지이며, 현재 변경을 배포하거나 실제 대회를 등록할 준비가 되었다는 뜻이 아니다.

수락 보고서는 각 행에 다음을 붙인다.

- 문제 패키지 ID, 지문/테스트/정책 hash, 측정 호스트 등급, 이미지 digest, 런타임 버전, 실행 시각
- 입력·기대 출력·참가자 코드의 비밀성 구분. 숨김 입력/기대 출력/전체 제출 코드는 공개 결과에 넣지 않는다.
- 기대 판정과 실제 판정, 최초 입증된 자원 사건, cleanup·슬롯 반환 여부
- 실행하지 못한 항목과 차단 사유. 모의 실행만으로 realLinux 수락을 대신하지 않는다.

## 2. 착수 시 소스 기준선과 유력 변경 지점

아래와 각 매트릭스의 초기 gap은 착수 시 조사한 기준선이다. 이후 구현 상태는 1.1 진행표를 우선한다. 존재나 일부 로직은 수락을 의미하지 않으며, 전체 연결과 실제 검증 전에는 수락으로 올리지 않는다.

### 2.1 대회·문제·점수

- `backend/app/models/database.py`, `backend/app/api/routes/contests.py` — 문제, 대회, 대회 문제 snapshot, 참가자, 제출 모델. 현재 `ContestProblem.snapshot`은 지문·샘플·숨김 테스트와 `judgePolicy`를 deep-copy하며, 정책 안에 revision·test hash·문제×언어 runtime profile/digest가 포함된다. rejudge 감사 이력은 snapshot이 아니라 별도 rejudge 모델에 저장된다. 이 연결 자체는 실제 런타임 수락을 뜻하지 않는다.
- `backend/app/models/schemas.py:8-23,234-254` — 여섯 컴파일 언어와 판정 union, 문제 입력 검증. 현재 변경 중인 Ruby 추가는 C12의 전체 수락 증거가 아니다.
- `backend/app/models/contest_schemas.py:6-47` — 관리자 대회 입력, 시간대, 배점, 제출 request ID 검증.
- `backend/app/api/routes/contests.py` — 신규 비공개 문제 생성, snapshot, 공개/일정 수정, 권한, 참가, 제출 멱등성. 대회 제출은 server-owned snapshot의 `judgePolicy`를 검증한 뒤 `measured-v1 judge_contract`로 동결해 durable payload에 저장한다. 실제 worker/cgroup 재시작 수락은 별도다.
- `backend/app/services/contests.py:20-236` — 대회 상태, scoreboard, finalization, 오답 패널티와 점수 지급.
- `backend/app/services/contest_access.py:19-37` — 종료 전 신규 문제를 일반 문제·커뮤니티·학습 경로에서 숨기는 공통 guard.
- `backend/app/services/scoreboard_cache.py` — revision 기반 공개 scoreboard cache. 자원 정책·rejudge revision과는 별도 계약이 필요하다.

### 2.2 채점·실행·샌드박스

- `backend/app/services/judging.py`, `backend/app/services/measured_judge.py` — `measured-v1` 경로는 제출당 정확히 한 번 compile하고 고정 artifact로 sample/hidden case를 각각 새 실행한다. 로컬 회귀는 compile 1회/run 2회를 고정하지만 legacy 경로와 실제 Docker 수락은 별도다.
- `backend/app/services/compiler.py:228-480` — 실제 애플리케이션의 `DockerCompilerRunner`; 공통 `EXECUTION_TIMEOUT`, `mem_limit`, `nano_cpus`, `pids_limit`, tmpfs, 출력 수집, OOMKilled, cleanup을 설정한다. CPU 실행시간과 문제별 wall/메모리 정책은 별도 구현·계측이 필요하다.
- `runtime/sandbox/run.sh:47-303` — 언어별 compile/run script와 phase frame. 이 경로와 `runtime/sandbox-runner` 데모를 같은 실행기로 간주하지 않는다.
- `backend/app/services/compile_queue.py` — 신뢰된 supervisor `failure_reason=output_limit_exceeded`는 독립 OLE 판정으로 보존한다. 참가자 출력·exit code만으로 신뢰 판정을 만들지 않으며, phase 정보가 없는 과거 결과에만 제한된 호환 fallback이 남는다.
- `backend/app/services/execution_worker.py:181-309`, `backend/app/services/durable_queue.py` — durable claim, lease, worker identity, Docker 소유권, cleanup, 재처리.
- `backend/app/services/execution_results.py:20-100` — 제출·대회 제출·점수 원장과 scoreboard revision 반영.
- `backend/app/core/config.py:34-43,71-76` — 현재 공통 sandbox wall 30초, 메모리 256MiB, CPU quota 1, PID 64, 출력 1MiB, 작업 deadline 120초 기본값. 신입생 대회의 확정 정책으로 간주하지 않는다.
- `backend/app/models/judge_policy.py`, `backend/app/services/judge_policy.py` — 정책/해시/측정 evidence는 `ContestProblem` snapshot, durable payload, measured runner, 관리자 API/UI까지 연결됐다. 로컬 연결 증거를 실제 Docker/cgroup·여섯 런타임·운영 정책 승인으로 확대 해석하지 않는다.
- `runtime/sandbox-runner/` — 정책 템플릿·샘플·Poc runner. 계획서의 실제 앱 경로와 분리된 프로토타입이며, realLinux 수락 보고서 없이 운영 채점 증거로 쓰지 않는다.

### 2.3 화면·문제 등급·기존 테스트

- `frontend/src/app/pages/ContestEditor.tsx`, `ContestDetail.tsx`, `ContestProblemPage.tsx`, `frontend/src/app/components/ContestJudgePanel.tsx`, `frontend/src/app/services/contestApi.ts` — 대회 작성, KST 일정 표시, 문제/제출/scoreboard UI. 선택 언어 제한표와 출처·검수 패널까지 구현했고 모의 API UI 회귀를 통과했다. 실제 backend 연결 수락은 남아 있다.
- `frontend/src/app/pages/Contests.tsx`, `frontend/src/app/components/contests.css` — 목록·상태 필터·반응형 대회 화면.
- `frontend/src/app/constants/difficulty.ts`, `frontend/src/app/services/problemApi.ts`, `frontend/src/app/pages/Challenges.tsx`, `backend/app/api/routes/problems.py:17-21`, `backend/app/services/rating.py:12-24` — Ruby 허용 목록·기존 rating 값 보존·문제 목록 필터의 로컬 회귀가 있다. 전체 legacy/contest 브라우저 흐름과 외부 등급 승인은 남아 있다.
- `backend/tests/test_contests.py`, `backend/tests/test_e2e_contest_flow.py`, `frontend/src/app/pages/ContestPages.test.tsx` — 대회·fake API 회귀가 있으며 최신 관련 결과는 아래 각 C 항목과 결론에 기록한다. V/C의 실제 외부 조건을 대신하지 않는다.
- `scripts/verify_freshman_contest_examples.py` — A–J Markdown 예제 계산 전용 검증기. 기준 풀이·validator·성능·실제 채점기가 아니다.

## 3. V01–V20 실행기·판정 수락 매트릭스

각 행의 코드 게이트는 구현 계약이고, localfake 게이트는 판정·점수·권한을 빠르게 확인하는 단계다. 자원 초과와 실제 프로세스 트리 행은 반드시 realLinux에서 재실행한다.

| ID | 수락 주장 | 코드/연결 게이트 | localfake/SQLite 게이트 | realLinux/Docker-cgroup 게이트 | 승인·외부 게이트 | 현재 gap / 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| V01 | A–J 패키지의 여섯 언어(C, C++, B++, Python, Java, JavaScript) 기준 풀이가 모든 sample/hidden case에서 안정적으로 AC다. | `CompilerLanguage`, `judge_code`, worker, 문제별 정책 snapshot/payload가 같은 테스트 묶음과 언어 profile을 사용하도록 연결한다. | fake runner가 여섯 언어를 각각 compile/run하고 모든 case AC를 반환하는지, 결과·점수·상세가 중복되지 않는지 확인한다. | 같은 이미지·CPU 등급에서 여섯 언어 기준 풀이를 반복 실행하고 case별 CPU/wall/peak memory를 기록한다. | 지원 언어 전체 또는 문제별 제외 범위와 런타임 버전 승인. | 6언어 A–J 기준 소스·정책 연결 구현, 로컬 기능 비교 통과. 실제 Linux 60조합 반복 측정과 완성 데이터 패키지는 미완료. |
| V02 | 상수 오답·off-by-one은 WA이고 점수·정답 ledger가 없다. | `classify_grading_result`, `execution_results`, scoreboard projection에서 `wrong_answer`와 AC 지급을 분리한다. | 동일 문제에 오답 후 정답/오답만 넣어 WA, 0점, 오답 패널티를 DB 전후로 확인한다. | 자원 초과가 아닌 실제 오답 코드로 같은 결과를 확인한다. | WA의 공백/개행 비교 규칙과 대회 패널티 승인. | A–I18/J6 오답·반례 및 점수/WA 로컬 회귀 구현. 실제 6언어 DB 워커 end-to-end는 미완료. |
| V03 | 문법 오류와 Java 파일/클래스 규약 오류는 CE이며 run 단계가 실행되지 않는다. | `compiler.py` diagnostics, `_resolve_filename`, `run.sh` compile branches, compile queue verdict를 연결한다. | fake compiler가 진단을 반환할 때 run 호출 횟수 0, `compile_error`, 점수/패널티 제외를 확인한다. | 여섯 언어별 문법 오류와 Java 이름 오류를 실제 이미지에서 재현하고 컨테이너·artifact cleanup을 확인한다. | 컴파일 자원 오류를 CE와 구분하는 문구·관리자 원인 표시 승인. | 컴파일/실행 단계 분리·컴파일 실패 시 run 차단 회귀, 로컬 Java 한글 산출물 roundtrip 통과. 6언어 실제 CE/자원 분류는 미완료. |
| V04 | CPU를 계속 쓰는 무한 루프는 CPU TLE이고 실행 트리·슬롯이 회수된다. | wall timeout만으로 CPU 제한을 대신하지 않도록 supervisor/cgroup CPU evidence와 `failure_reason`을 연결한다. | fake supervisor가 CPU 한도 사건을 반환하면 TLE, cleanup, queue slot 반환을 원자적으로 확인한다. | busy loop, 자식 busy loop를 실제 Linux에서 CPU time 초과로 종료하고 zombie/container/workdir 부재를 확인한다. | 문제×언어 CPU ms와 overshoot/강제 종료 정책 승인. | CPU 누적 감독·트리 회수 구현, 실제 격리 CPU 초과 실험 통과. 다언어/자식 CPU·슬롯 end-to-end/교정 반복은 미완료. |
| V05 | `sleep`/입력 대기 같은 저CPU 무한 대기는 wall TLE이며 CPU TLE와 구분된다. | CPU와 wall 사건을 별도 필드·판정으로 보존하고 큐 대기/이미지 준비 시간을 실행 타이머에서 제외한다. | fake clock에서 CPU 낮음+wall 초과와 CPU 높음+wall 초과를 서로 다른 evidence로 확인한다. | 실제 sleep·stdin 대기 프로그램을 wall 한도로 종료하고 CPU 사용량·판정·cleanup을 함께 기록한다. | wall 여유 및 정상 동시성 측정 승인. | 독립 CPU/wall 제한과 기록 구현, 실제 격리 wall 실험 통과. 별도 공개 failure subtype과 다언어 교정·정상 동시성은 미완료. |
| V06 | 실제 페이지를 만지는 메모리 초과는 cgroup/OOM evidence가 있는 MLE다. | `compiler.py`의 OOMKilled, cgroup metric adapter, `classify_run_result`, 결과 저장을 연결한다. | fake container state에서 `OOMKilled=true`와 일반 nonzero를 구분해 MLE/RE를 확인한다. | 주소 예약이 아니라 실제 할당·페이지 접근으로 cgroup limit/OOM event를 발생시키고 peak bytes, event, 종료 원인을 기록한다. | 문제×런타임 memory bytes와 JVM/Node/native 포함 범위 승인. | 실제 제한된 OOM·peak 실험 및 v15 보호 기록 저장 구현. 언어별 한도 확정/DB 워커 전체 검증은 미완료. |
| V07 | 자식 프로세스 메모리 증가도 전체 트리 제한에 포함되고 다른 작업은 살아 있다. | 프로세스 트리/cgroup을 job 단위로 묶고 lease별 cleanup·소유권을 보장한다. | fake child tree/worker pool로 한 작업의 MLE가 다른 claim을 취소하지 않는지 확인한다. | fork/child allocator로 트리 전체 limit, 다른 job AC, 부모·자식·컨테이너·tmpfs cleanup을 확인한다. | worker host 동시성·격리·중단 기준 승인. | 실제 detached 자손 회수 확인, job별 cgroup/소유권 검사 구현. 자식 MLE와 동시 정상 작업의 전체 실험은 미완료. |
| V08 | Python MemoryError, Java OOME, C++ bad_alloc 등은 실제 한도 초과가 입증될 때만 MLE이고 나머지는 RE다. | 런타임 예외 문자열을 권위로 삼지 않고 supervisor/cgroup evidence와 exception metadata를 결합한다. | 같은 문구를 출력하는 fake 프로그램과 실제 evidence가 있는 결과를 비교한다. | 제공된 실제 인터프리터/VM에서 할당 예외·비자원 예외를 모두 실행해 MLE/RE를 구분한다. | “런타임 자체 실패”와 MLE 분류 기준 승인. | 신뢰 지표 우선·문구 위조 로컬 회귀 구현. allocator 예외/감독기 자체 OOM의 다언어 실제 분리는 미완료. |
| V09 | `memory`, `timeout` 문자열 출력과 직접 exit 124/137만으로 자원 초과 판정을 만들지 않는다. | phase frame·failure reason·trusted supervisor 결과를 우선하고 legacy fallback 범위를 제한한다. | fake user output/exit code와 supervisor-authenticated result를 섞어 false MLE/TLE가 없는지 확인한다. | 실제 코드가 문자열 출력·exit 124/137을 하며 정상 RE/완료로 남는지 확인한다. | 구 이미지 결과의 호환 기간·마이그레이션 정책 승인. | 보호된 부모 기록과 참가자 출력 분리, 위조 출력·exit code 회귀 및 격리 실험 통과. 구 이미지 호환 전환 승인은 별도. |
| V10 | 잘못된 접근·segfault·미처리 예외는 RE이며 TLE/MLE로 오분류하지 않는다. | signal/exit/phase를 `runtime_error`로 보존하고 숨김 진단을 참가자 결과에서 제거한다. | fake signal/exception 결과로 RE와 점수·패널티를 확인한다. | segfault·잘못된 파일/예외 프로그램을 실제 런타임에서 실행해 signal, stderr 제한, cleanup을 기록한다. | 공개 오류 메시지와 관리자 진단 분리 승인. | 신뢰 판정/숨김 진단 제거와 로컬 회귀 구현. 6언어 실제 signal/exception 판정 수락은 미완료. |
| V11 | stdout+stderr 합산 폭주는 OLE로 독립 판정하고 로그/DB/디스크가 무제한 증가하지 않는다. | `_collect_output` 상한, 독립 OLE verdict를 schemas/DB/UI/scoreboard에 연결한다. | fake stream에서 정확히 limit/limit+1 UTF-8 bytes를 확인하고 반환 payload·DB가 bounded인지 확인한다. | 실제 출력 폭주를 cap에서 중단하고 OLE, 파일·컨테이너·queue slot cleanup을 기록한다. | OLE의 패널티·scoreboard 표시 승인. | 독립 OLE·합산 출력 cap·공개 진단 총량 cap 구현, 실제 격리 OLE 통과. 최대 출력/외부 버퍼 overhead·DB 워커 전체 검증은 미완료. |
| V12 | PID/process limit 초과는 명시된 실패 판정이며 호스트 장애가 없다. | pids evidence/reason code를 판정·관리자 진단에 연결하고 host OOM과 참가자 오류를 분리한다. | fixture cgroup counter에서 `pids.events:max` 증가를 `process_limit_exceeded`로, 누락/역행 counter는 fail-closed로, 동시 OOM은 MLE 우선으로 확인한다. | process explosion/fork/thread 프로그램을 실제 pids cgroup에서 종료하고 호스트·다음 job 상태를 기록한다. | PID/thread limit 및 공개 판정 승인. | v2가 `pids.events:max`를 단계 전후로 읽고 증가를 `process_limit_exceeded`로 저장·필터·표시한다. counter 누락/역행은 fail-closed, OOM은 PID보다 우선하며 v1 영수증은 해시 고정 archive로만 재생한다. 로컬 parser/launcher/registry/UI 회귀 통과. 실제 fork/thread 다언어 cgroup 실험과 공개 판정·패널티 승인은 미완료. |
| V13 | CPU/메모리 80%·120% 교정 프로그램의 경계 판정이 일관되고 계측 오차·overshoot가 기록된다. | trusted metric의 단위·반올림·경계 비교를 고정하고 CPU quota와 CPU time을 분리한다. | fake metrics로 경계 바로 아래/위, 누락 metric, 반올림을 table-test한다. | 같은 호스트 등급에서 80/120% 교정 프로그램을 반복하고 실제 오차 분포와 판정을 저장한다. | 안전 여유와 경계 허용오차 승인. | 정수 경계·누락/위조 지표 단위 회귀 구현. 실제 80/120% 반복 교정과 허용 오차 승인은 미완료. |
| V14 | 컴파일만 시간·메모리를 소모한 경우 실행 TLE/MLE와 분리되고 참가자 오답 패널티가 없다. | compile stage budget, artifact reuse, run-stage result, compile-resource verdict를 별도 저장한다. | fake compile timeout/OOM 후 run 미호출, CE/resource/system 분리와 점수 불변을 확인한다. | 큰 compile 또는 compile OOM/TLE와 정상 artifact case를 실제 이미지에서 검증한다. | 컴파일 자원 오류의 공개 명칭·패널티 제외 승인. | compile-resource 별도 판정·패널티 제외·1회 컴파일 구현과 로컬 회귀 통과. 실제 Python1compile2run 확인; 6언어 compile OOM/TLE 미완료. |
| V15 | 큐 지연·worker restart·Docker 오류는 system error 또는 안전한 재처리이며 점수 중복이 없다. | durable lease/fence, result publish, cleanup journal, idempotency를 제출·score transaction과 연결한다. | SQLite에서 claim 중단·재시작·duplicate finish를 주입해 한 receipt/점수만 남는지 확인한다. | 격리 staging Docker에서 daemon/worker 장애 후 lease recovery, no orphan, no duplicate score를 확인한다. | staging Docker 장애 실험의 별도 승인. 운영 장애를 만들지 않는다. | lease/fence·재시작/중복 완료·예약 유지 로컬/SQLite 회귀 통과. PostgreSQL과 실제 격리 워커 장애 복구는 미완료. |
| V16 | 정상 다중 case의 합계가 기존 120초를 넘으면 새 budget으로 완료하거나 출제 단계에서 거절한다. | case count×wall + compile + preparation/cleanup deadline을 저장·검증하고 초과 package publish를 막는다. | 0/1/200 case 및 계산 초과 policy를 fake DB에서 검증한다. | 정상 기준 풀이가 새 전체 deadline 안에 끝나는지 실제 언어별로 확인한다. | 서비스 최대 job/deadline·최대 resource reservation 승인. | 케이스 수/단계 wall 기반 전체 deadline 고정·서비스 ceiling 거절·워커 적용 구현. 실제 장시간 정상 제출 수락은 미완료. |
| V17 | 제한 설정이 바뀌어도 이미 접수된 retry/restart job은 접수 당시 policy를 쓴다. | contest snapshot와 durable payload에 policy revision/hash/profile을 deep-copy한다. | enqueue 후 전역 policy를 바꾸고 retry/restart 결과가 원 revision인지 확인한다. | worker 재시작·동시 정책 publish를 staging에서 실행해 실제 cgroup 한도가 frozen payload와 일치하는지 확인한다. | 정책 revision 공개·변경 이력 승인. | snapshot/접수에 profile/hash/deadline 고정, 수정/재시도/설정 drift 거절 회귀 구현. 실제 동시 정책 변경·워커 재시작 실험은 미완료. |
| V18 | 클라이언트가 보내는 resource 값은 무시하거나 거절하고 서버 확정값만 적용한다. | 제출 schema에 client limit을 허용하지 않거나 명시적으로 reject하고 server snapshot을 선택한다. | 악성 payload에 CPU/memory/wall을 넣어 4xx 또는 무시, 서버 policy hash 불변을 확인한다. | 실제 job에서 요청값을 바꿔도 cgroup/runner가 서버 profile인 것을 확인한다. | API 오류/무시 방식과 관리자 override 범위 승인. | 서버 정책에서만 receipt를 고정하고 런타임 등록부와 대조한다. 실제 클라이언트 위조값→cgroup 전 구간 검증은 별도. |
| V19 | TLE/MLE 뒤 같은 worker에서 정상 풀이가 AC이고 잔여 프로세스·파일·slot이 없다. | `SandboxPool` 소유권/cleanup/absence 확인과 queue finish 순서를 유지한다. | fake pool에서 failure→cleanup→next claim AC 및 stale result 무시를 확인한다. | 같은 worker에서 CPU TLE, MLE, 다음 AC를 순서대로 실행하고 container/workdir/tmpfs/zombie/slot 상태를 확인한다. | worker drain/recovery와 중단 기준 승인. | 같은 워커 객체에서 TLE→MLE→AC를 처리하고 매 작업 claim·reservation·owned cleanup이 다음 선점 전에 해제되는 로컬 회귀를 추가했다. 실제 격리 단계별 cleanup과 후속 Python AC도 별도로 확인했지만, 동일 durable Linux 워커의 TLE→MLE→AC·컨테이너/workdir/tmpfs/zombie 전 구간 실험은 미완료다. |
| V20 | 정답·오답 완료 순서 역전과 중복 처리에도 첫 AC, 점수, 5분 오답 패널티가 동일하다. | receipt order와 DB unique key를 scoreboard/finalizer에 연결하고 result publish를 idempotent하게 한다. | SQLite에서 completion order를 섞고 duplicate finish/finalize를 반복해 scoreboard·ledger가 동일한지 확인한다. | 실제 실행 순서 지연은 필요 시 staging에서 확인하되 correctness는 DB/fake와 분리 기록한다. | 동점 규칙, J 점수·순위 반영 여부 승인. | 접수 순서·동점·오답 패널티·중복 보상 방지의 기존 대회/SQLite 회귀 통과. PostgreSQL/실제 지연 채점 및 J 운영값 승인은 미완료. |

## 4. C01–C12 대회·권한·UI 수락 매트릭스

| ID | 수락 주장 | 코드/연결 게이트 | localfake/SQLite 게이트 | realLinux/브라우저 게이트 | 승인·외부 게이트 | 현재 gap / 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| C01 | 관리자 초안 생성→새로고침→재수정 뒤 문제 10개, 순서, 배점, 일정이 보존된다. | `ContestWrite`, `save_contest`, `/manage`, editor의 load/save가 snapshot·position을 보존한다. | 관리자 HTTP 흐름과 SQLite 전후 snapshot을 비교하고 중복/부분 commit을 검사한다. | 불필요. 다만 staging에서 실제 backend/frontend 연결 smoke는 별도 기록한다. | 관리자 권한과 초안 수정 범위 승인. | v14 원자적 private import/재시도/수정 후 매핑 보존 구현. 실패 PUT이 기존 mapping을 delete/flush한 뒤 검증 오류를 내도록 재현하고, 새 세션에서 contest 필드/revision·mapping ID/순서/배점/snapshot·비공개 문제·출제 metadata·행 수가 동일하며 즉시 정상 재저장됨을 확인했다(관련 39 PASS/6 환경 SKIP). 확정 10문제 manifest와 실제 브라우저/backend 전체 흐름은 미완료. |
| C02 | 비로그인·일반 사용자·다른 참가자는 초안·문제를 직접 URL/API로 볼 수 없다. | `get_contest`, `read_problem`, `private_problem_ids`, public problem/community/learning guards를 모든 경로에 적용한다. | 세 역할·직접 URL·목록·문제·community·compiler 요청을 fake HTTP로 검사한다. | 실제 배포가 아닌 격리 staging에서 reverse proxy/cache 포함 직접 URL을 확인한다. | 비공개 범위와 관리자 예외 승인. | 대회/문제 비공개 HTTP 회귀와 관리자 출제 API 권한 검사 구현. 참가자 문제 화면도 auth scope 전환 즉시 이전 statement/sample/IDE를 제거하고 polling을 중단하며 늦은 이전 계정 응답을 차단한다(프런트 55파일/299 PASS·타입·빌드). 실제 reverse proxy/cache 전 구간 수락은 미완료. |
| C03 | 비공개 패키지 검수는 운영 점수·제출·순위를 바꾸지 않는다. | 참가자 submit API를 우회하는 admin-only package validator 또는 별도 dry-run queue를 만든다. 결과는 no-score/no-ledger/no-public-cache여야 한다. 공개는 현재 필수 언어별 accepted 증명을 요구한다. | 검수 전후 DB·scoreboard revision·queue receipt를 비교하고 실패/과거 hash/누락 언어 증명의 공개 우회를 거절한다. | realLinux 실행을 하더라도 staging DB/queue와 package ID를 분리한다. | 관리자 검수 권한, 무점수, 숨김 출력 보호 승인. | 저장된 초안 행·출제 지문·기준 풀이 SHA-256·검증 정책·테스트 snapshot에 묶인 관리자 전용 durable job과 no-score/no-ledger/no-public-cache 결과 분기, 전용 비공개 polling, 민감 실행 콘텐츠 보존 메커니즘, 편집 UI를 구현했다. accepted 완료 트랜잭션은 코드·테스트·raw report 없이 문제/대회/snapshot/출제/소스/정책/테스트/언어 지문만 append-only 증명으로 보존하고, 공개 gate는 같은 대회의 현재 필수 언어별 exact 증명을 요구한다. WA·검증 누락·필수 언어 일부 누락·검증 뒤 문제 변경은 공개를 막고, 동일 콘텐츠 일정/배점 저장은 허용하며, 민감 payload/result 만료 뒤에도 증명이 유지된다. 신규 gate·migration·package 회귀 **25 PASS/2 환경 SKIP**. 기존 만료 회귀는 test-only 7일 값으로 source/hidden/result 삭제, receipt hash/status 보존, 조회·동일 키 재시도 410/no-store, 다른 관리자 404, 점수·ledger·scoreboard 불변을 확인했다. 편집 화면은 410에서만 새 request ID를 만들고 503 등 모호한 실패에는 기존 ID를 유지한다. 운영 보존 기간 기본값은 승인 전까지 0으로 유지한다. 실제 기준 풀이를 실행하는 Linux/cgroup·분리 PostgreSQL/Redis queue 검수와 외부 승인 전에는 C03 전체 수락으로 올리지 않는다. |
| C04 | 시작 전 날짜만 변경하면 KST 표시가 바뀌고 문제·테스트·정책 snapshot은 보존된다. | `save_contest`의 locked pre-start update, timezone conversion, immutable snapshot/policy hash를 연결한다. | 시각 경계 전후 PUT/refresh와 snapshot/hash 비교를 SQLite에서 확인한다. | 브라우저 timezone/서버 UTC와 실제 KST 표시를 staging smoke로 확인한다. | 시작/종료 시각, 180분 제안, 종료 후 공개 정책 승인. | 날짜 변경의 snapshot/정책 보존 및 import 매핑 갱신 로컬 회귀를 통과했다. UTC 2029-12-31 시각이 KST 2030-01-01로 넘어가는 시작/종료 표시와 원본 `dateTime` 보존도 프런트 회귀로 고정했다(해당 파일 9 PASS·타입 검사 PASS). 실제 backend 연결 브라우저 수락과 일정 승인은 미완료다. |
| C05 | 시작한 공개 대회의 문제·일정·배점 수정은 API에서 거절된다. | `save_contest` row lock와 `ContestWrite` validation을 유지하고 오류를 일관되게 공개한다. | 시작 전/정확한 시작/진행/종료 후 관리자 PUT을 fake clock으로 검사한다. | 불필요. staging API smoke만 필요하다. | 공개 대회 변경·긴급 수정/rejudge 절차 승인. | 시작 이후 편집 잠금·검수 변경 차단 로컬 회귀 통과. PostgreSQL 경쟁 및 운영 긴급 변경 절차는 미완료. |
| C06 | 미참가·시작 전·종료 시각 제출은 거절된다. | `join`, `submit`, `received_at` 기준과 participant/ends_at guard를 서버에서 확정한다. | fake clock에서 미참가/직전/정확한 시작/정확한 종료/직후 요청을 검사한다. | staging에서 browser button disabled와 API 직접 요청을 함께 확인한다. | 마감 경계와 지연 요청 인정 정책 승인. | 미참가·시작/마감 경계·진행 중 참가·언어 경로 로컬 대회 회귀 통과. 실제 브라우저/API 전체 흐름은 미완료. |
| C07 | 시작 시각·마감 직전 접수와 지연 채점은 receipt 시각의 인정 구간을 보존한다. | receipt transaction, queue lease, finalization reopen rule, scoreboard revision을 함께 보존한다. | DB lock 지연/finalizer race/worker delay를 fake clock·SQLite로 재현한다. | realLinux에서는 staging queue delay만 측정하고 운영 점수판을 사용하지 않는다. | 지연 채점·마감 race에 대한 운영 규칙 승인. | 마감 전 접수·지연 채점·finalizer 대기 race 로컬 회귀 통과. PostgreSQL/격리 실제 큐 지연 검증은 미완료. |
| C08 | 종료 후 공개·점수 반영 재실행은 선택한 정책대로 노출되고 중복 지급이 없다. | `finalize_contests`, `private_problem_ids`, practice score ledger, public cache를 종료 정책과 연결한다. | finalizer를 두 번 이상 실행하고 hidden/scoreboard/general problem 목록·ledger를 비교한다. | staging 재실행 smoke만 허용한다. | **종료 후에도 계속 비공개인지**, 일반 문제 공개 시점, J 점수 반영 승인 필요. | 반복 finalizer/중복 보상 방지 회귀에 더해 revision/commit 직전 강제 실패가 finalized claim·solve evidence·score ledger·사용자 총점·revision을 모두 rollback하고 재시도 두 번이 정확히 한 번만 지급함을 확인했다(관련 45 PASS/6 환경 SKIP). 종료 후 계속 비공개 여부와 J 점수 정책 미결정; 현행 종료 노출 규칙을 임의 변경하지 않음. |
| C09 | 학습/추천/검색/문제 목록/제출 큐/커뮤니티/캐시에서 비공개 제목·지문·테스트가 새지 않는다. | problems, learning, community, compiler queue, scoreboard cache, direct URL 모두 `private_problem_ids` 또는 contest-scope privacy를 사용한다. 관리자 `/manage` 성공 응답은 raw hidden tests를 포함하므로 `Cache-Control: no-store`를 명시한다. | 각 endpoint와 cache hit/miss를 세 역할로 조회하고 secret marker의 부재를 확인한다. 관리자 manage 회귀는 secret marker가 보호된 본문에 존재하는 상태에서 root와 `/webcompiler` root-path 모두 no-store임을 검사한다. | 격리 staging reverse proxy/CDN/cache header까지 확인한다. | 보관·캐시 TTL·종료 후 노출 정책 승인. | 대회 비공개·컴파일 기록 필터/관찰 응답의 코드/제목 누출 차단 회귀와 관리자 manage no-store 계약 구현. 당시 `test_contests.py` 27 PASS였고 후속 참가자 source no-store 회귀까지 포함한 최신 해당 파일은 29 PASS다. v26은 일반 공개 문제를 수정해 초안으로 되돌린 뒤 direct read·공개 목록·레이팅·태그 숙련도에서 모두 제외되는 전이를 추가했으며 최종 backend 전체 3,041 PASS/449 조건부 SKIP이다. 실제 proxy/CDN 전 경로 수락은 미완료다. |
| C10 | 모바일·중간 너비·데스크톱에서 문제→언어→제출→순위 흐름과 선택 언어의 실제 제한 표가 일치한다. | contest API type, IDE/contest judge panel, limit display, verdict mapping, no client limit override를 연결한다. | fake API로 상태·언어·limit/policy revision을 주입해 화면과 payload를 비교한다. | 브라우저 3 viewport에서 실제 staging API의 KST clock, submit, scoreboard, selected/all language limits를 확인한다. | 표시할 여섯 언어·실제 제한·지원 제외 문제 승인. | 선택 언어 제한·정책/출처/자원 기록 UI 구현, 실제 Edge3폭 API-mock 검사 통과. 실제 backend 제출→순위 전 구간은 미완료. |
| C11 | 테스트 0/1/200/201개와 과대 입력 크기의 등록/publication 경계가 일치한다. | `ProblemCreate`, contest save, `_validate_problem_tests`, payload-size, per-case byte/whole-job budget을 같은 규칙으로 연결한다. | 0/1/200/201 sample+hidden 및 큰 input/expected output을 API/DB에서 검사한다. | realLinux는 등록 검증이 통과한 package만 실행하며 자원 측정과 경계 오류를 분리한다. | 테스트 수·바이트·job 예산 상한 승인. | 정책 케이스 수/deadline·package 바이트·직접 API 요청 경계 구현. C/E/I 최대 입력은 약 1–3 MB로 저장 데이터의 개별 16 MiB 상한 안에 있지만 인라인 패키지 한도를 넘는다. 일반 API 프록시와 직접 API에서 512 KiB 요청을 제한하고 별도 업로드 `stored-v1` 참조로 넣는다. A–J 초안 생성기는 26 sample을 inline, 53 hidden 전부를 POSIX owner-only 원자적 내용 주소 blob/참조로 생성하며 corpus·asset 해시와 미승인 선언을 검사한다(Windows 17 PASS/3 POSIX SKIP, 실제 Linux 격리 19 PASS/1 Windows-only SKIP). Windows bundle 출력은 권한을 보장할 수 없어 명시적으로 차단한다. 전체 묶음 적용 관문은 package/index/status와 89개 blob(12,718,689바이트)의 exact closure를 네트워크 전에 검사하고 순차 PUT 성공 뒤에만 import한다(Windows 53 PASS/1 POSIX SKIP, 격리 Linux 54 PASS). 실제 API 적용은 하지 않았다. 네 최대 입력의 직접 대회 흐름은 377 PASS/1 Java SKIP, C 최대의 비공개 package 성공 흐름은 SQLite+PostgreSQL 변형으로 검증했다. 별도 PG 미검수 흐름은 승인 없이 공개·참가·제출·점수 변화가 없음을 포함해 최신 380 PASS/1 Java SKIP이다. 성공 검수 자료는 합성이며 실제 이용 허락·최종 A–J 값/승인, 운영 blob 업로드·Redis/Docker 채점과 상한 승인은 미완료. |
| C12 | Ruby5–Ruby1 입력·표시·필터·정렬·레이팅이 허용 목록과 일치하고 기존 등급 값이 보존된다. | backend problem schema/API/filter/rating, frontend constants/track/admin/profile/contest payload를 모두 일치시킨다. external solved.ac 등급과 자체 등급을 분리한다. | Ruby 각 값 CRUD/list/filter/rating 회귀와 기존 iron–diamond fixtures의 값·순서를 비교한다. root는 Ruby/learning 관련 16 PASS를 통합 증거로 보고했지만 전체 C12로 재해석하지 않는다. | 브라우저 문제 목록·관리자·프로필·대회 편집을 staging smoke한다. | Ruby가 문제 난이도일 뿐 Ruby 언어가 아님을 문서화하고 외부 매핑 승인. | Ruby 허용 목록·API/UI·기존 레이팅값 회귀 통과. 문제 목록의 최초/초기화 범위도 `iron5`–`ruby1`로 고정했고 집중 프런트 5 PASS·타입 검사 PASS다. 외부 등급 승인과 전체 대회/legacy 실제 브라우저 수락은 미완료. |

## 5. 추가 자원 정책 수락 항목

이 절은 V01–V20에 더해 계획서 6절과 언어 제한 참고문의 요구를 분리한 것이다. 제안 배수는 확정값이 아니다. 공개하려면 문제×런타임 버전별 절대 `cpu_ms`, `wall_ms`, `memory_bytes`와 증거가 필요하다.

| ID | 수락 기준 | 코드/연결 게이트 | localfake/SQLite 게이트 | realLinux 게이트 | 승인·외부 게이트 | 현재 gap / 상태 |
| --- | --- | --- | --- | --- | --- | --- |
| R01 | 문제별 정책이 compile/run의 CPU·wall·memory·output·PID·tmpfs를 bytes/ms로 표현한다. | `judge_policy` 모델을 ContestProblem snapshot, DB migration, API, queue payload, compiler/runner에 연결하고 단위·반올림을 고정한다. | Pydantic/DB round-trip, 범위·단위·`tmp_bytes <= memory_bytes`·extra field 거절을 검사한다. | 실제 cgroup/tmpfs/PID/output 적용값과 payload를 대조한다. | 정책 owner가 필드·최대 예산 승인. | v12 정책 저장·snapshot/receipt·queue payload 고정과 v15 등록부 대조는 구현됐다. 실제 cgroup 적용과 여섯 언어 end-to-end, 운영 승인·재채점 이력은 남아 있다. |
| R02 | 각 profile은 runtime ID/version, image digest, toolchain/compiler options, worker class와 연결된다. | trusted runtime registry와 immutable digest를 payload에 복사하고 client/compiler option을 차단한다. | 잘못된 digest/version/worker class와 profile mismatch를 거절한다. | 동일 digest·host class에서만 측정하고 실제 실행 metadata를 남긴다. | 제공할 여섯 런타임 버전·이미지 승인. | 정적 운영자 등록부와 고정 runtime/image/toolchain/실행기 hash 대조를 공개·새 접수에 연결했다. v2 등록부가 archive 실행기를 `admitNew`로 잘못 표시해도 새 접수는 현재 toolchain과 현재 실행기 바이트 해시를 모두 요구하며, archive는 기존 영수증 재생에만 허용한다. 실시간 워커·이미지 준비 상태와 여섯 런타임 수락은 미완료다. |
| R03 | 여섯 언어 기준 풀이를 같은 package/image/CPU 등급에서 최소 10회 측정하고 evidence가 저장된다. | report hash, resource fingerprint, case count, repetitions, safety reason을 policy와 검증한다. | repetitions<10, hash mismatch, 다른 host class를 publish 거절한다. | 각 문제×언어의 CPU/wall peak memory 분포를 측정하고 최종 절대값을 고정한다. | 측정 방법·안전 여유·언어 제외 승인. | v15 보호된 compile/case 보고서는 영속화했고 실제 격리 Python 1회 컴파일/2 fresh case를 확인했다. 여섯 언어×문제 10회 측정·최종 절대값·승인은 미완료다. |
| R04 | CPU time과 wall time을 별도 한도로 적용하고 queue/image/compile/output-check를 실행 budget에서 제외하며 JIT/GC는 포함한다. | supervisor metric과 deadline 계산을 분리하고 global multiplier를 판정 시 재적용하지 않는다. | synthetic CPU/wall/queue timings로 계산·경계 table-test를 한다. | busy/sleep/JVM warm-up/GC/Node startup를 실제로 측정한다. | wall overshoot와 public limit 구분 승인. | 보호된 단계별 CPU/wall 측정과 deadline 검증·저장은 구현됐고 작은 실제 Python 연결도 확인했다. JVM/Node 등을 포함한 여섯 언어 경계 측정과 공개 한도 승인은 남아 있다. |
| R05 | memory limit은 전체 process tree, runtime native/heap, child, thread, participant tmpfs의 실제 peak bytes를 포함하고 외부 준비 비용은 분리한다. | cgroup metrics/OOM event adapter를 payload/result로 연결하고 virtual address를 MLE 근거로 쓰지 않는다. | metric missing/zero/virtual-only evidence를 publish·MLE에서 거절한다. | Python/Java/Node/C/C++/B++ 최대 입력과 child allocator를 측정한다. | memory safety margin·JVM/Node flags 승인. | v15는 보호된 peak/OOM과 트리 회수 기록을 결과에 저장하고 외부 여유분을 예약 계산에 분리한다. 실제 여섯 언어 최대 입력·부모 감독기 OOM/overhead·안전 여유 승인은 남아 있다. |
| R06 | compile은 별도 budget에서 한 번 수행해 job 전용 read-only artifact를 만들고, 각 case는 새 격리 환경에서 재사용한다. | `judge_code`, `DockerCompilerRunner`, run.sh, artifact lifetime을 연결하고 제출 간 공유를 차단한다. | fake runner call count가 compile 1회/case run N회이며 case마다 새 sandbox key인지 검사한다. | compile-heavy source와 multi-case 제출에서 compile time이 run budget에 중복되지 않는지 확인한다. | artifact 보존·삭제·compile failure 정책 승인. | measured-v1 경로에서 compile-once/fresh-case와 읽기 전용 산출물을 구현했고 실제 Python 1회 컴파일/2 case를 확인했다. 실제 DB 워커·여섯 언어·compile-heavy 수락은 미완료다. |
| R07 | 전체 deadline = compile 한도 + case별 wall 합 + 제한된 준비/정리 여유이며 서비스 최대 budget·reservation을 넘는 package는 저장/공개 거절한다. | `validate_publishable` 같은 계산을 contest save/publish에 연결하고 case count/test hash와 함께 저장한다. | 0/1/200/201 case, 예산 초과, memory reservation 초과를 deterministic하게 검사한다. | 정상 기준 풀이의 실제 합산 wall과 worker deadline을 대조한다. | host capacity·최대 동시성·중단 기준 승인. | 단계 wall과 case 수로 deadline을 고정하고 서비스 ceiling 초과를 거절하며, v13의 daemon별 영속 예약도 구현했다. 실제 장시간 정상 제출·Linux/PG 혼합 부하와 운영 예산 승인은 남아 있다. |
| R08 | stdout+stderr, PID, nofile, tmpfs, network, read-only, capability 제한을 정책 버전과 함께 적용한다. | compiler container kwargs와 sandbox-runner handoff를 policy-driven으로 바꾼다. | fake Docker kwargs와 output byte exact boundary를 비교한다. | 실제 network/file/syscall/output/PID violations와 cleanup을 측정한다. | 보안 profile·예외 허용 범위 승인. | v15는 보호된 출력량과 OLE·compile-resource 판정을 분리해 저장한다. 정책별 모든 Docker/cgroup 값의 실제 위반·cleanup 검증과 보안 profile 승인은 미완료다. |
| R09 | 공개 시 문제 snapshot에 최종 여섯 언어 표와 policy revision/hash/test hash를 복사하고 제출 접수 payload에도 freeze한다. | API가 client 값을 받지 않고 server snapshot을 선택하며 retry/restart/global change에도 동일값을 사용한다. | enqueue 후 policy mutate/retry와 deep-copy 불변성을 DB에서 검사한다. | worker restart 후 실제 runner metadata가 접수 revision과 같은지 확인한다. | 공개 화면에 표기할 fields·revision 정책 승인. | v12는 정책 revision/hash/deadline을 snapshot·접수·재시도에 고정했고, v15는 새 접수의 등록부 대조를 추가했다. 실제 worker restart와 cgroup 적용값의 end-to-end 수락은 남아 있다. |
| R10 | 언어별 memory reservation 합과 worker 운영 여유를 넘지 않도록 큐를 배치하며 검증 host class별로 실행한다. | durable queue admission/reservation을 policy memory와 연결한다. | 동시 fake jobs에서 reservation 합·queue fairness·QueueFull을 검사한다. | 서로 다른 memory profile 동시 실행에서 host OOM 없이 진행되는지 확인한다. | host capacity·worker class 운영 승인. | v13은 peak-stage memory+외부 여유분·CPU를 daemon별 영속 예약하고 등급/FIFO를 적용한다. 실제 Linux/PG 혼합 부하, 물리 호스트 다중 daemon 관계와 운영 예산 승인은 남아 있다. |
| R11 | 문제 화면과 IDE는 선택 언어의 실제 CPU/wall/memory와 전체 언어 표, 미측정/legacy 상태를 보여준다. | contest API/public limits schema, frontend types/components, stale cache invalidation을 연결한다. | fake API mismatch·missing language·unverified policy가 공개/제출을 막는지 확인한다. | staging에서 표시값과 실행 payload/runner evidence를 대조한다. | 참가자에게 보일 정책·지원언어 승인. | 일반/대회 화면에 언어별 제한표·미측정 경고와 관리자 JSON 검토 UI를 구현했고 Edge 3폭 모의 API 검사를 했다. 실제 API/측정 보고서/runner 연결 수락은 미완료다. |
| R12 | 현재 운영 이미지 보안·sandbox 설정은 재검토하고 이전 배포의 예외/98건을 자동 재사용하지 않는다. | image digest/scan result/policy review를 release gate와 package metadata에 연결한다. | stale scan, wrong digest, expired exception을 gate가 거절하는지 검사한다. | 현재 이미지의 실제 scan·runtime smoke·resource tests를 격리 staging에서 수행한다. | 보안 담당자·운영 환경 승인. | 이전 기록은 현행 재스캔이 아니며 이번 문서 작성 중 scan하지 않음. |

## 6. 재채점(rejudge)과 이력

계획서의 “오류 수정 후 재채점” 요구를 별도 상태 변경으로 취급한다. 종료 순위를 조용히 덮어쓰지 않는다.

| ID | 수락 기준 | 코드/연결 | localfake/SQLite | realLinux / 승인 게이트 |
| --- | --- | --- | --- | --- |
| RG01 | rejudge는 관리자 작업으로만 실행되고 대상 contest/problem/submission, 사유, 요청자, 시각, package/policy revision을 기록한다. | admin API/service, audit event, explicit job kind와 idempotency key를 추가한다. | 일반 사용자/중복 요청/다른 대상 변조를 4xx로 확인하고 audit 전후를 비교한다. | 실제 실행은 승인된 staging만 허용. 운영 대회에는 별도 승인 없이는 실행하지 않는다. |
| RG02 | dry-run/package validation은 점수·제출·순위·practice ledger를 변경하지 않는다. | C03의 별도 `authoring-validation-v1` durable job을 사용하며 참가자 제출·점수 경로와 generic execution serializer를 우회한다. | 제출·대회 제출·문제 점수·solve evidence·공개 queue 행 수, 사용자 점수와 scoreboard revision 불변, 다른 관리자/일반 사용자 polling 차단, 멱등 재시도와 숨김 값 비노출을 검사한다. | 실제 자원 측정은 명시적으로 만든 격리 staging DB/queue에서만 수행한다. 현재 그런 환경이 설정됐다고 가정하지 않으며 운영 연결은 사용하지 않는다. |
| RG03 | 적용 rejudge는 before/after verdict, 기존 정책, 새 정책, hash, 판정 차이를 공개/관리자 이력으로 남긴다. | result history와 score adjustment ledger를 append-only로 만든다. v24는 legacy 해소 provenance도 application audit에 보존한다. | 같은 result를 두 번 실행해 보정이 한 번만 적용되는지 확인한다. v24 로컬 회귀는 중복 요청·stale source/legacy 지문·전체 롤백을 포함한다. | 실제 package를 실행할 경우 six-language/resource evidence를 새로 수집한다. 실제 PostgreSQL 경쟁은 별도다. |
| RG04 | 종료 contest의 rank/score 변경은 자동 덮어쓰지 않고 관리자 검토·공지·이의 제기 절차를 거친다. | finalization lock, adjustment event, scoreboard revision을 분리한다. legacy-only 차감은 append-only 관리자 결정을 추가로 요구한다. | final scoreboard를 rejudge해도 old projection과 change set이 보존되는지 확인한다. 명시적 유지/검증된 영수증 연결, 한 번의 차감, 다른 accepted 근거 보존을 검사했다. | 운영 공개 전 담당자·참가자 통지와 실제 legacy 판단 승인이 필요하다. |
| RG05 | 기존 문제/기존 대회는 명시된 legacy policy로 보존되고 새 policy로 자동 재채점되지 않는다. | job payload에 legacy policy ID/version을 유지하고 migration/backfill을 명시한다. | legacy job retry/recovery가 당시 limit/verdict schema를 쓰는지 확인한다. | 실제 old image가 필요한 경우 보존 가능성·보안 승인 없이는 실행하지 않는다. |

현재는 관리자 전용 rejudge 후보 생성·검수·미리보기·폐기·결정적 shard 처리·단일 원자 반영·감사/공개 정정 이력, 점수 보정 ledger와 legacy 출처 해소 절차가 구현돼 있다. legacy 해소는 원본을 수정하지 않고 명시적 유지 또는 기존 accepted 영수증 연결만 append-only로 기록한다. 실제 PostgreSQL 대규모 재시작, 여섯 언어 Linux 실행, 운영자의 실제 출처 판단과 통지·이의 제기 절차는 아직 수락 전이며 운영자가 DB를 직접 덮어쓰는 방식으로 대체하지 않는다.

## 7. 출제 패키지·문제 품질 수락 항목

### 7.1 A–J 공통 패키지

- [~] `docs/freshman-contest-statements-a-i-2026-09-26.md`의 A–J 제목·입출력·제약·26개 예제를 validator/oracle과 대조했다. 79-case 초안 manifest 및 package source와 해시로 묶었지만 사용자 지문 승인은 남아 있다.
- [ ] A–I의 원문 URL·대회/저자·현재 티어 확인일·이용 조건·변경 내역을 기록한다. 목표 Bronze/Silver/Gold는 최신 solved.ac 결과로 주장하지 않는다.
- [ ] J Banks의 원 출처, 번역·각색 조건, 현재 티어, 이용 조건을 확인한다. 이용 조건을 확인하지 못한 문제는 등록 보류 또는 독립 창작으로 대체한다.
- [~] 참가자 본문과 출제자 메모를 분리하고 hidden/validator/정답 자산은 content-addressed private bundle로 분리했다. 로컬 privacy/cache 회귀가 있으나 실제 reverse proxy 수락은 남아 있다.
- [~] 공개 예제 26개, 숨김 후보 53개, 여섯 언어 기준 풀이, validator/generator, A–I 오답 18종/J 오답 6종과 F/I/J 느린 풀이를 draft package ID·manifest hash로 묶었다. 최종 검수된 hidden 묶음과 독립 출처 승인은 남아 있다.
- [~] 예제와 초안 expected output을 validator·작은 oracle·독립 계산으로 재검산한다. 모든 최종 hidden에 대한 사람 검수와 실제 여섯 언어 수락은 남아 있다.
- [~] manifest가 지문 예제·생성기·validator·source hash 변경을 감지하고 snapshot 혼합을 거절한다. 최종 승인 뒤 변경 절차는 운영 수락 전이다.
- [~] 0/1/200/201 테스트·byte/deadline/reservation 경계와 89-blob private bundle closure를 로컬/격리 회귀로 검사한다. 최종 정책·운영 host 예산과 실제 publish 후보 승인은 남아 있다.

### 7.2 문제별 핵심 acceptance

| 문제 | 반드시 준비할 검증 | 승인/미결정 |
| --- | --- | --- |
| A–E | 경계 입력, 출력 안내 문구, 최소/최대/동률/대소문자/문자열 반복의 기준·오답 비교. | 사용자 지문 승인, 원문 이용 조건. |
| F–H | 음수·중복·정수 경계·이분 탐색, 누적합 최댓값, BFS 시작 거리/방문·도달 조건. | 입력 제한과 언어별 기준 풀이 측정. |
| I | 다중 시작점·동시 전파·초기 완료·시작점 없음·분리 영역·1,000×1,000 큐 성능. | large case의 six-language memory 측정. |
| J | N=1/2 퇴화 이웃, 0은 대상 아님, 원형/방향/양의 배수 성질, 최적성·종료·중간값·정답 정수 범위 증명. | Banks 원문 대조, 이용 조건, BigInt/Number 선택, J 점수·순위·AI 규칙. |

현재 예제 verifier는 J의 작은 BFS oracle과 26개 문서 예제를 계산한다. 별도로 `banks.py`의 O(n log n) 기준 풀이, `docs/banks-reference-proof-2026-09-26.md`의 증명, 여섯 언어 J 기능 비교가 있다. J의 대규모 입력 실제 자원 수락·원문/이용 조건·점수/순위 규칙과 실제 채점은 아직 준비 전이며, “예제 통과”를 출제 승인으로 승격하지 않는다.

## 8. UI·표시 수락 항목

- [~] 관리자 editor에 제목·KST 일정·순서·배점·sample/hidden·정책·runtime/measurement·출처/검수 패널을 연결했다. 모의 API 회귀는 통과했으며 실제 backend 브라우저 수락은 남아 있다.
- [~] 문제 화면/IDE에 서버 payload의 선택 언어 CPU/wall/memory/output/PID와 전체 언어 표, policy revision·검수 상태를 표시한다. 확정 운영 숫자와 실제 API 연결 수락은 남아 있다.
- [~] 대회 상세의 상태·KST 일정·배점·동점/오답·제출 가능 구간 UI와 로컬 회귀가 있다. 180분/실제 일정 승인과 staging 확인은 남아 있다.
- [~] `ContestJudgePanel`은 language/code/request ID만 보내며 client resource override를 제출 schema가 거절하고 서버가 profile을 freeze한다. 실제 cgroup 전 구간은 미검증이다.
- [~] AC/WA/CE/TLE/MLE/OLE/`process_limit_exceeded`/RE/system/compile-resource 표시와 숨김 상세 비노출 회귀가 있다. 실제 여섯 런타임·관리자 진단 화면 수락은 남아 있다.
- [ ] 모바일·중간 너비·데스크톱 각각에서 문제→언어 선택→제출→지연 결과→scoreboard 흐름을 실제 viewport로 검증한다. 문서의 브라우저 fake 테스트만으로 반응형 완료를 주장하지 않는다.
- [~] Ruby5–Ruby1은 난이도 배지·필터·정렬·관리자 입력·프로필/레이팅 로컬 회귀에 연결했고 Ruby 언어와 구분한다. 전체 legacy/contest 실제 브라우저 수락은 남아 있다.
- [~] private contest title/statement/test와 queue/learning/community/cache 경계를 역할별 HTTP·UI 회귀로 검사했다. 실제 reverse proxy/CDN/cache 수락은 남아 있다.

주요 화면 경로는 `ContestEditor.tsx`, `ContestDetail.tsx`, `ContestProblemPage.tsx`, `ContestJudgePanel.tsx`, `contestApi.ts`, `constants/difficulty.ts`, `problemApi.ts`, `contests.css`다. resource policy API와 표시는 구현됐지만 운영 승인값과 실제 backend 브라우저 연결은 아직 수락 전이다.

## 9. 레거시 보존 수락 항목

- [~] 과거 계약이 없거나 mutable identity인 job은 현재 값으로 추론하지 않고 append-only legacy resolution 없이는 선점하지 않는다. 실제 역사 자료 backfill과 운영 수명주기 승인은 남아 있다.
- [~] 진행 중 접수는 정책·테스트·runtime·점수 snapshot/hash를 durable payload에 보존하고 retry/restart 때 재검증한다. 실제 PostgreSQL/Redis 동시 재시작은 미검증이다.
- [~] OLE·compile-resource·policy metadata를 새 판정으로 분리하고 기존 graded 결과에는 보호된 report/명시적 legacy resolution을 요구한다. 운영 migration 기간·통지 승인은 남아 있다.
- [~] Ruby 추가 전후 기존 score/rating/tier fixture와 순서를 보존하는 로컬 회귀가 있다. 외부 solved.ac 매핑과 전체 운영 데이터 대조는 남아 있다.
- [~] additive migration·부분 legacy shape·double initialization·unresolved skip 회귀가 있으며 원본 payload를 고치지 않는다. 실제 PostgreSQL/Redis 복구와 cache lifecycle 수락은 남아 있다.
- [ ] 이전 이미지가 더 이상 안전하지 않다면 자동 재사용하지 않고, 보존된 artifact 또는 새 검증 가능한 대체 이미지를 운영 승인으로 선택한다.

현재 모델에는 rejudge campaign/shard/item/application/audit 이력과 당시 policy/runtime/receipt snapshot이 있다. v25에서는 계약이 없거나 mutable image tag만 가진 `legacy-v1` graded job을 선점 전에 보류하고, 관리자가 job/payload/contract/verdict schema에 정확히 묶은 append-only measured replay resolution을 기록한 경우에만 보존된 runtime/image/toolchain/launcher snapshot으로 실행한다. durable payload는 바꾸지 않으며 완료 저장도 같은 resolution hash를 다시 대조한다. `system_error`가 아닌 graded 완료는 보호된 resource report를 반드시 가져야 하며, AC는 compile 성공과 frozen sample/hidden 전체의 accepted evidence가 있어야 한다. 로컬 SQLite에서 unresolved zero-attempt skip, 뒤 작업 진행, exact replay, runtime/hash 변조 차단, reportless AC 차단, no-store/redaction, additive double initialization을 검증했고 최종 backend 3,036 PASS/448 조건부 SKIP/10 subtests/실패 0을 확인했다. 실제 과거 계약값·이미지를 현재 설정에서 추론하지 않았고, 운영자 기록 생성·PostgreSQL/Redis 재시작·실제 archived Linux runtime replay와 운영 승인된 legacy 수명주기는 아직 수락 전이다. 이 항목은 새 필드 유무뿐 아니라 오래된 대회·점수 원장을 읽는 호환 테스트까지 포함한다.

## 10. 사용자 결정·외부·운영 게이트

아래가 비어 있으면 대회를 등록·공개하지 않는다.

| 게이트 | 결정/증거 | 상태 |
| --- | --- | --- |
| G01 문제 승인 | A–J 참가자용 한국어 지문, 입출력, 제한, 새 예제 최종 승인자·일시. | [ ] 미결정 |
| G02 원문·이용 조건 | A–I 후보와 J Banks의 원문·현재 티어·번역/각색/테스트 재배포 조건 기록. | [~] 2026-09-27 solved.ac Ruby V 목록에서 J(BOJ 10350)를 확인했고 SEERC 2014 원문 PDF와 대조했다. solved.ac 공식 안내상 난이도는 변동 가능하다. ICPC U도 기록된 라이선스가 없는 외부 문제는 원 소유자에게 권리가 남는다고 명시한다. A–I 최신 티어와 A–J의 명시적 번역·각색·테스트 재배포 권리는 확인되지 않아 등록 보류. |
| G03 J 수학 검수 | N=1/2, 중복 이웃, 최적성·종료 증명, 정수형(Number/BigInt), 독립 기준 풀이·대조 풀이. | [ ] 독립 증명·BFS/이차식 대조·6언어 기능 소스 구현. 출제 검수 승인/실제 런타임 수락은 별도. |
| G04 대회 운영값 | 제목, 시작/종료 KST, 180분 여부, 10문제·순서·배점, 참가 규칙. | [ ] 미결정 |
| G05 종료 후 공개 | 종료 시 신규 문제를 일반 문제로 노출할지, 계속 비공개로 둘지와 별도 공개 정책. | [ ] 미결정 |
| G06 J 순위 | J를 100점 정규 문제로 둘지, 0점 비채점으로 둘지. 현재 API는 대회 문제 배점 최소 1이므로 비채점은 기능 변경 승인 필요. | [ ] 미결정 |
| G07 AI/외부 도움 | 검색·AI·외부 코드·타인 도움 허용 범위, 설명 요청·이의 제기·사람의 판단 절차, 탐지 서비스 전송 금지·보관 기간. | [ ] 미결정 |
| G08 언어 범위 | 여섯 언어 전체를 지원할지 문제별 제한을 둘지. 제한 시 API·화면·참가 규칙과 이유. | [ ] 미결정 |
| G09 자원 측정 | 문제×runtime별 최소 10회 측정, 안전 여유, CPU/wall/memory absolute limits, host class, image digest, runtime/toolchain. | [ ] 미측정 |
| G10 OLE/compile-resource | OLE 표시·패널티, compile 자원 오류의 공개 판정·패널티 제외, host OOM 책임 경계. | [ ] 미결정 |
| G11 rejudge | 관리자 전용, dry-run, 정책 revision, 점수 보정 ledger, 종료 순위 통지·이의 제기. | [~] 관리자 전용 후보·검수·미리보기·결정적 분할·단일 원자 반영·감사/공개 정정 안내 구현. 실제 PostgreSQL/대규모 재시작 검증과 운영 통지·이의 제기 절차 승인은 미완료. |
| G12 realLinux 권한 | 실제 Docker/cgroup/언어 런타임/호스트 측정·fault injection을 별도 staging에서 실행할 승인과 실제로 식별 가능한 격리 환경. 사용자의 “격리 테스트만 허용”은 환경을 설정했다는 뜻이 아니며 현재 별도 격리 환경은 없다. 운영 서버·무거운 build/load는 범위 밖이다. | [ ] 격리 환경을 먼저 명시적으로 구성·식별한 뒤 작은 OOM/PID/감독기/Python 실험을 수행한다. 6언어/DB워커/fault 전체 수락은 미완료. |
| G13 보안 재검토 | 현재 sandbox image digest의 최신 scan·예외 검토. 과거 배포의 98건/예외를 자동 재사용하지 않음. | [ ] 미실행 |
| G14 비공개 등록 | 승인된 서버에서 관리자 draft 등록·snapshot/hash 확인. 공개는 별도 최종 승인. | [ ] 실행 금지 상태 |

## 11. 완료 조건과 현재 결론

신입생 대회 수락은 다음을 모두 만족할 때만 가능하다.

1. V01–V20과 C01–C12에 대해 코드/연결, localfake/SQLite, 필요한 realLinux/브라우저 결과가 각각 기록된다.
2. 여섯 언어의 문제별 absolute limits, compile/run 분리, 전체 deadline, output/PID/tmpfs, runtime/image/test hash, snapshot/payload freeze가 수락된다.
3. OLE·compile-resource·system error·MLE/RE 근거가 분리되고, queue/worker cleanup과 duplicate score가 검증된다.
4. A–J package의 원문·이용 조건·독립 풀이·validator/generator·seed·오답/느린 풀이·J 증명이 승인된다.
5. rejudge/legacy 절차와 Ruby 등급 end-to-end 회귀가 완료된다.
6. G01–G14의 사용자·법적/출처·운영·보안 게이트가 모두 승인된다.

현재 결론은 다음과 같다. 2절의 최초 소스 위치 조사와 과거 체크포인트는 이 최신 구현 상태와 구분한다.

2026-09-27 백엔드 전수 회귀 체크포인트: v21 물리 legacy schema 테스트의 PostgreSQL wrapper가 제거된 v17 함수명을 import해 전체 수집을 막던 문제를 고치고, dialect별 migration fixture를 분리했다. **그 체크포인트 소스**는 전체 **3,436 tests collected**, 실행 결과 **2,991 PASS/445 조건부 SKIP/10 subtests PASS/실패 0/299.13초**다. 이후의 캐시 경계 변경은 별도 focused 회귀로 검증하며 이 전수 결과에 소급해 포함하지 않는다. 이 실행에는 실제 `TEST_POSTGRES_URL`, Redis, Linux/cgroup/6언어 runtime이 없었으므로 445 SKIP은 외부 수락으로 남는다. 참가자 본인 제출 원문 API에는 `Cache-Control: no-store`를 추가했고 root 및 `/webcompiler` root-path의 200/no-store/정확한 source와 타 참가자 404를 검증했다(`test_contests.py` 29 PASS). 실제 reverse proxy/CDN cache 검증, 운영 변경·배포·push는 수행하지 않았다.

2026-09-27 v26 최신 로컬 체크포인트: 일반 관리자 문제도 생성·수정 즉시 공개하지 않고, 현재 내용의 출처 기록·네 검수·필수 언어 기준 풀이 통과 증거가 있어야 공개된다. 일반 문제 증거는 `__problem__` 범위와 해당 문제 ID에 함께 묶여 대회 증거를 재사용할 수 없다. 초안은 직접 API뿐 아니라 레이팅·상위 난이도·태그 숙련도에서도 제외되며, 공개→초안 전환 시 캐시를 무효화한다. 관련 focused 34 PASS, 프런트 **58 files/322 PASS**와 타입 검사/build PASS, 최종 백엔드 **3,123 PASS/450 조건부 SKIP/10 subtests PASS/실패 0/408.79초**다. 450 skip은 별도로 구성된 실제 PostgreSQL/Redis/Linux/cgroup/6언어/reverse-proxy 환경이 없어서 남은 외부 조건이다. 운영 B++ 단일 실행과 두 API의 7/5 read-only 분배는 확인했지만 전용 daemon/cgroup·혼합 부하·장애 복구를 대체하지 않는다. 사용자는 그런 격리 환경을 설정한 적이 없고, 이 최종 회귀 작업도 서버 설정·운영 데이터·배포·push를 수행하지 않았다.

- 정책 snapshot→durable receipt→자원 예약→실측 compile-once/fresh-case→결과/측정 저장 경로를 구현했다. NULL/legacy 정책 호환을 유지하며 measured 경로 실패를 기존 실행기로 숨기지 않는다.
- 운영자 등록부의 정확한 승인값을 공개/새 접수 단계에서 대조한다. 실제 워커/이미지의 라이브 준비 상태, 운영 예산/호스트 관계 확인은 아직 필요하다.
- 보호된 CPU/wall/peak/OOM 측정, OLE/컴파일 자원 오류 구분, 원자적 metric/점수 저장을 구현했다. 작은 실제 Linux 감독기·Python 실험과 로컬 회귀는 통과했지만 여섯 언어의 모든 자원 경계·장애 수락은 아니다.
- 여섯 언어 A–J 독립 소스, validators/generators, 일부 오답·경계 입력을 마련했고, A–I에는 지연 생성 23개 최대·적대 descriptor와 모든 descriptor를 순차 실행한 Python 기능 회귀가 있다. J를 포함한 검수된 최악 입력/출력 package와 60조합 반복 측정은 남아 있다. `stored-v1` 대용량 데이터는 관리자 업로드·problem/contest snapshot·frozen receipt·worker case loader·queue reservation에 코드/합성 테스트 수준으로 연결됐다. 이는 실제 Docker/cgroup·운영 blob 업로드·외부 승인 또는 대용량 실채점 수락 증거가 아니며, 최종 상한·저장/요청/큐 메모리 예산 승인은 여전히 필요하다.
- 비공개 등록/멱등 영수증, 출처·검수 지문과 관리자 UI가 있다. 점수 보정 가능한 rejudge campaign과 감사 이력도 구현했지만 실제 PostgreSQL 대규모 재시작·여섯 언어 실행·운영 통지/이의 절차는 아직 수락 전이다.
- Ruby/API/UI 및 정책·출처·측정 화면의 로컬 회귀와 모의 API 브라우저 검사는 실제 등록·공개 승인이나 실제 backend 전체 브라우저 수락을 대신하지 않는다.
- 모든 격리 서버 실험은 허용된 임시 환경에서만 수행했다. 운영 DB/큐/점수판 변경, 대회 등록, 배포, Git push, 이미지 설치/pull, 운영 부하 시험은 하지 않았다. 출처·난이도·일정·J 점수·종료 공개 규칙은 미승인 상태다.

2026-09-27 운영-ref 재현 후보 추가 확인: exact 배포 ref 기반 백엔드 **2,315 PASS/380 조건부 SKIP/8 subtests**, 프런트 **58 files/322 PASS**, 타입 검사/build가 통과했다. 콘텐츠 주소형 launcher LF·digest 및 Git fresh-checkout/archive 재현성과 public readiness 설정도 후보에 포함됐다. 그러나 이 검증은 A–J 이용 권리, A–I 최신 티어, 일정·배점·종료 공개·J 순위/AI 규칙, 실제 문제별 6언어 cgroup 측정이나 비공개 등록 승인을 만들지 않는다. G01–G14는 그대로 미결정이며 어떤 대회도 등록·공개하지 않았다.
