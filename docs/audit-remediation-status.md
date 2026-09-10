# 감사 후속 수정 진행표

## 최신 결과 — 기본 LB 운영 배포 완료

사용자가 축소 승인한 기본2-API LB 범위는 운영 배포 및 HTTPS6언어 실행·로그인·목록·API1개 중지 후 신규 실행까지 확인했다. 최종 release는 `eef08f2486926bbf5eb1017886d0b88634eddb45`이며 두 API/worker가 healthy다. 일반/대회 전체 채점은 운영 복사본의 격리 환경에서 검증했다. 전환 중 익명 제출1개가 TTL로 삭제되어 백업에서 그 행만 복원했고, 자동 삭제를 비활성화한 뒤 원본9개 테이블을 다시 대조했다. [배포·검증·복구 기록](basic-load-balancing-release-2026-09-10.md)에 정확한 범위와 미완료를 기록한다. 아래 전체 감사/managed lifecycle 상태를 완료로 바꾸지 않는다.

## 2026-09-10 — 축소된 활성 마일스톤

현재 활성 마일스톤은 전체 감사 항목을 완료했다고 주장하지 않고, 다음의
작은 운영 경로만 확인하는 것이다: 기본 2-API LB, 공유 login/queue/grading,
6개 언어와 대회 smoke, API 하나를 내린 상태에서의 신규 요청 성공, 그리고
production 배포 smoke와 복구 자료 확보. 실제 완료·미검증 범위는 위 최신 결과와
배포 기록을 따른다. 전체 rollback 전환이 검증되었다는 뜻은 아니다.

다음 범위는 이 마일스톤에서 명시적으로 보류한다: 전체 A01-A25 검증, managed
lifecycle(승격·drain·재시작·retirement 및 경쟁 조건), 전체 security 검증,
mixed-bot/혼합 버전 검증, 외부 환경·외부 endpoint 검증. 이 보류 목록은 해당
검사가 실패했다는 뜻이 아니라, 이번 축소 범위의 완료 조건에 포함하지 않는다는
뜻이다.

## 최신 확인 — 전체 빌드와 실제 기본 서비스 시험

소스SHA `db839d58e1bdd05e21d0b99d357c0ba3e3c670334e813b29864dfc4c14fd6ad7`의
전체 E2E(41615)는 **1049.092초에 실패**했다. 세 이미지 빌드는 완료했으나 DB
이미지 pull 중 여유 디스크가 8GiB 안전선 아래로 내려갔다. 실제 빌드 RUN의
2GiB/no-extra-swap·1CPU·512PID 상속은 확인했다. 정확한 시험용 빌더와 캐시만
정리하고 완성된 세 이미지는 보존했다. 중단된 setup namespace는 완료 기록 없이
격리 보류하며, 전체 E2E 통과로 바꾸지 않는다.

그 이미지와 원본 build-context 파일의 바이트 일치를 확인한 별도 runtime-only
검사(52408)는 실제 7서비스 자원/loopback, B++ 컴파일·오류 분석과 6언어 42 출력
검사를 통과한 뒤 로그인 helper에서 실패했다. API의 camelCase 응답을 helper가
snake_case로 읽은 문제다. `accessToken/tokenType`으로 수정하고 로그인 실패
로그의 토큰 노출을 제거했다. Luna의 실제 응답 모델 기반 회귀를 검토했고 집중
28개/0.87초 통과. 실패한 시험의 정상 drain·DB 미완료 0건 확인 및 자기 자원
정리도 통과했고, 이후 독립 조회에서 해당 컨테이너·볼륨·네트워크가 없었다.

다음 검사(50404)는 로그인 이후 일반 채점 helper의 잘못된 기대값 때문에 실패했다.
`SubmissionResponse`에 없는 별도 leaderboard API의 필드를 요구한 것이다.
서버 API를 바꾸지 않고 제출 기록의 `awardedPoints`와 계정 총점·해결 기록을
독립 조회해 검증하도록 수정했다. 이 실패 실행도 자기 자원 정리가 완료됐다.

**수정 후 runtime-only 검사(15270)는 194.139초/exit0으로 통과했다.** 같은 실제
이미지를 새 namespace/DB/Redis에서 실행했으며 재빌드·배포하지 않았다.

- 실제 7서비스 자원 한도·loopback, readiness·프런트 HTML 확인.
- B++ 컴파일 결과와 잘못된 코드 진단 4건, B++/C/C++/Python/Java/JavaScript 각각42 출력.
- 일반 문제 두 정답의 독립 제출 ID, 제출 내역 지급20/0, 계정 총점과 문제 해결 기록 일치.
- 비공개 대회 생성→공개 예약→시작 전 문제 접근 거부→참가→채점→500점/1위 반영.
- 같은 대회 요청 ID 재시도는 같은 제출 기록 반환. 종료 후 일반 문제 공개·17점 지급,
  숨겨진 테스트 비공개 유지.
- 정상 producer 종료·DB 미완료 작업/lease0 확인 뒤 자기 컨테이너·sandbox·볼륨·
  네트워크·태그·작업 폴더 정리. 후속 독립 Docker 조회에서도 자기 자원이 없었다.

별도 실행 adapter를 사용했으므로 원래 build+up 전체 진입점이나 최종 managed-LB
검증을 대신하지 않는다. 개발 설정의 기본 스택이며 배포 SHA/runtime instance는
설정하지 않았다. 브라우저 조작, 대량 공격 부하, 장애 복구·혼합 버전 전환 증거도 아니다.
최신 로컬 전체(8257)는 **1940통과·357skip·8subtests/73.13초**다.

재현 증거:

- 서버 `/home/vulpo/webcompiler-audit-runtime-reuse-guZo9Z`, unit `audit-runtime-reuse-v3-guzo9z`.
- E2E script SHA `edfb64764069377b7f4509f6b97c0301b6c7bb4ac86c827b1b0cd5b1268aaea8`.
- 일회성 adapter SHA `d8d7863bb40337ef4881d86b4a287d54fdf0485267c8fb03b18658a6e367969b`.
  원본 archive 전체 파일의 바이트·권한·symlink 부재와 변경된 E2E script의 고정 hash를 검사했다.
- 로컬 `.deploy/audit-runtime-reuse-v3.log` SHA
  `bb4b447a2302f2dfd2118ff414b7c302bb6499799aa624f4b032753f458d015f`.
- 재사용 image IDs: backend `sha256:bb8a4b854f438e67cf4b77373f13fe18173a0dd71dfdf83a1a2ea09b22b0e4bf`,
  frontend `sha256:0b4a5a6963d555f23be49d081b6857d8c0481ffcfbbc9f86dceb48a33b8d7ec6`,
  sandbox `sha256:5d1590bc099feeb72017ebf22a6721add973b269922027f3fd980414a669625a`.
- Controller768MiB/no-extra-swap/0.5CPU/128Tasks/600초, helper540초 및8GiB free-disk floor.
  각 서비스와 별도 sandbox 한도는 기존 E2E 설정을 유지했다. 종료 후 여유11907MiB.

디스크 원인 수정도 추가했다. Terra의 E2E 전용 cache-release helper를 검토하고,
CLI builder와 검증 환경의 builder 불일치 거부를 보완했다. E2E만 명시적으로
활성화하며 두 build가 성공한 뒤 세 nonce 태그의 immutable ID를 확인하고 해당
BuildKit의 캐시만 비운다. 이후 builder와 이미지 ID를 다시 대조하고 실패하면
서비스 시작 전에 중단한다. 일반 실행은 기본 비활성이다. **새 cache-release의
실제 Buildx 실행과 수정 후 build+up 전체 진입점 재검증은 아직 남아 있다.**

시험을 실제7서비스 자원/loopback 설정 대조→6언어 실행→B++컴파일 분석·오류→
일반 채점/중복 지급 방지→비공개 대회 생성·공개·참가·동일 요청 재시도·채점·
점수판·종료 후 일반 공개/17점 지급 확인으로 확장했다. HTTP API 기반이며
브라우저 조작 및 최종 관리형 LB 구성 검증을 대신하지 않는다.

정리 전에는 시작 요청의 완료 기록, API/worker 정상 종료, DB의 미완료 제출·
Docker 작업·lease 0건과 worker drain을 요구한다. 확인되지 않는 중단은 DB와
소유 증거를 보존하며 정리 성공으로 처리하지 않는다. 이는 불확실한 요청의
자동 복구 완료가 아니라 안전한 정리 허용 조건이다. 전체 이미지 보안 검사,
최종 LB/장애·혼합 부하·외부 조건은 계속 미완료이며 운영 변경/배포/main push 없음.

## 최신 확정 — 통합 시험 자원 정리·중단 복구

최종 추가 검증: 부모 프로세스를 강제 종료해도 살아 있는 실행 스크립트가
잠금을 유지하도록 FD를 상속했다. 실제 Linux 검사 **2개/15.208초 통과**,
소스SHA `063c8fede8909c881a9498b718db5842a1189ca5cc8a8aea59cadb3974b4994b`.
CI는 stack 정리가 성공한 뒤에만 빌더를 제거한다. 수정 직전 전체 백엔드는
1896통과·355skip·8subtests/74.72초였고, 최종 FD/CI 수정 후 집중 검사는
82통과·7skip/1.65초다. skip을 실제 환경 통과로 계산하지 않는다.

**남은 정리 조건:** 호출자가 사라진 뒤 Docker daemon이 create/build를 늦게
완료하는 경우와 worker 강제 종료 중 미완료 요청은 아직 검증·해결되지 않았다.
Terra 검토로 분리한 이 조건은 자식 잠금 상속이나 반복 목록 조회만으로 완료
처리할 수 없다. 실제 전체 앱 시험 전에 producer 종료/요청 완료 확인 또는
불확실한 실행의 격리 보류 처리를 보완해야 한다. 현재 검사는 정지된 Docker
자원 정리와 OS 프로세스 잠금 범위이며 전체 취소·장애 복구 완료를 뜻하지 않는다.

E2E가 시작 전에 전용 namespace를0600 소유 기록에 저장하고, 중단 후 CI에서도
그 기록을 읽어 정리하도록 변경했다. 실행 중인 테스트의 lock을 얻지 못하면
정리를 거부한다. 컨테이너의 full ID·소유 label·작업 경로, 볼륨과 네트워크의
정확한 이름을 대조한 뒤 worker를 멈추고 별도 sandbox와 나머지 자원을 정리한다.
이미지는 전용 tag만 제거하며 기본 이미지·빌더·다른 프로젝트는 정리하지 않는다.
CI의 기본 프로젝트 대상 logs/down과 정리 오류 무시를 제거했다.

로컬 집중46개 통과, Luna의 CI 테스트4개를 검토했다. 별도 서버에서 실제 Docker
중지 상태 컨테이너·sandbox·볼륨·네트워크·이미지 tag·작업 경로를 만든 뒤 이전
namespace 복구와 반복 정리, 동시 정리 거부, 별도 대조 볼륨/기본 이미지 보존을
검증했다: **1개/13.802초 통과**. 실제 Compose 구성 검사도1개/0.698초 통과했다.
소스SHA `14f7b4128207e0ef11a6f00974438d02cd179a0e5a1ee144940f1b54743f228f`.
검사 제어 프로세스는256MiB/no-extra-swap·0.25CPU·64Tasks로 제한했다.

이는 정리 프로토콜 검증이며 실제 앱이나 채점 컨테이너를 실행한 검증이 아니다.
전체 앱 실행·실제 자원 제한 대조·6언어/대회·관리형 LB·부하·외부 조건은 남았다.
운영 데이터 변경·배포/main push 없음. 아래 정리 작업 미완료 문구는 이전 이력이다.

## 최신 확정 — 실제 세 이미지 빌드

31244는 **1039.180초 통과**로 종료했다. 현재 frontend/backend 이미지85.0초,
B++ sandbox922.2초이며 모든 실제 RUN은 기존2GiB/no-extra-swap·1CPU·512PID
제한 안에서 수행됐다. 전용 이미지·빌더·캐시 정리와 unit 비활성까지 확인했다.
이전 아래 '빌드 진행 중'은 당시 기록이다. 전체 이미지 보안 검사·실제 서비스
통합·최종 managed LB/부하·외부 조건은 아직 남아 있다. 운영 배포/main push 없음.

통합 시험에는 별도7서비스 자원 제한 overlay와 기존 상태가 있는 checkout 거부,
동일 checkout 실행 잠금, 지정 loopback 포트 충돌 검사, 실제 Compose 모델의
자원 상한 검사를 추가했다. 집중 로컬33통과/1Linux조건skip이며, 실제 Compose의
7서비스 제한·외부 설정 제외·동일 checkout 잠금/해제 후 재획득도1개/0.605초에
통과했다. 소스SHA `ac3a642aa038bab3c75cf00661b2fbda200e252720db30202c4c4213116113fb`.
처음에는 Compose의 UnitBytes 숫자 문자열을 거부해 실패했고, 제한을 완화하지 않고
정수와 엄격한 십진 문자열만 읽도록 보완했다. 그 직전 전체 로컬은1879통과/354skip,
이후 파서 보완은 집중·실제 Linux 검사로 확인했다. 테스트 전용이며 운영 기본값은
바꾸지 않았다. Compose 밖 sandbox 자원은 이7서비스 합계에 포함되지 않는다.

전체 통합 실행 전에는 전용 volume/image/sandbox 경로 정리 검증과, E2E의 무작위
프로젝트 이름을 모르는 CI의 기본 `docker compose logs/down` 후처리를 전용 이름에
묶는 작업이 남아 있다. 아직 기존 전체 E2E를 서버에서 실행해도 된다는 뜻은 아니다.

## 최신 통합 시험 환경 분리

기존 E2E가 호출 환경의 COMPOSE_FILE을 받아 운영용 설정으로 바뀔 수 있는 문제를
로컬 실패로 재현했다. 실행/임시 경로와 명시적인 제한 빌더 설정만 전달하고,
테스트 Compose·로컬 Docker·빈 env 파일을 고정했다. 별도 서버의 실제 Compose
설정 검사1개/0.689초에서 외부 Compose와 프로젝트 `.env`·자동 override가
섞이지 않음을 확인했다. 소스SHA
`9a613170f18e208bd2f669fb7efc44fc24f9a2be8ea3ba94b1b738dee05cbf0e`,
256MiB/0.25CPU/64Tasks 제한이며 실제 서비스는 시작하지 않았다.

정리 실패를 버리던 경로도 재현 후 오류를 전달하도록 고쳤다. 단, 전체 E2E 실행
승인이 아니라 실행 전 조건 보강이다. Terra 검토와 대조한 남은 조건은 새 checkout의
전용 sandbox 경로, 전용 빌더, PostgreSQL/PgBouncer 자원 제한, 포트 충돌 확인,
전용 volume/image/Compose 밖 sandbox 정리 검증이다. 기존 스크립트는 base Compose
시험이므로 최종5개 overlay의 managed LB 전환·drain·부하 검증을 대신하지 않는다.

현재 로컬 전체22127은 **1851통과·354skip·8subtests/78.94초**로 종료했다.
skip은 통과로 계산하지 않는다. 이전 frontend/backend 이미지 통과 뒤 이어진
B++ 빌드31244는 720초 시점에도 실행 중이며, 전체3이미지 결과는 아직 미확정이다.

## 최신 A17/A23 — Monaco 전체 로컬 배포물과 빌드 메모리

Monaco 전체 min/vs를 같은 lock 패키지에서 byte 그대로 제공하고 ESM 재번들을
제거했다. 첫 워커만 교체한 방식은 실제2GiB에서26217 실패였으며 대체했다.
현재1024MiB 힙 로컬 빌드13.042초/최대RSS831008KiB, 최종70프런트테스트·타입 검사,
두 base의 실제 Edge10개/23.3초가 통과했다. 기능 축소 없이6언어 템플릿·토큰 색상·
JS 자동완성·진단·엄격 script CSP에서 동작을 확인했다. API 채점 검증은 아니다.
[변경과 실패/회귀 증거](frontend-build-memory.md).

실제 Linux31244에서 frontend/backend 전체 이미지 build/export/load이 기존2GiB한도로
85.0초에 통과했다. B++ sandbox 빌드는 진행 중이므로 전체3이미지 결과는 아직
미확정이다. 앞선31938의 archive Nginx설정 누락은 보완했다. 최신 전체 백엔드94028은
1848통과·353skip·8subtests/76.93초로 종료했다. 운영 배포/main push·
자원 증설을 하지 않았다. 전체 수명주기/부하/대회/외부 조건은 여전히 미완료다.

## 최신 A17 — 설치 이미지 검사와 Nginx 회귀

최종 현재 소스 전체 로컬88185는 **1848통과·353skip·8subtests/74.42초,exit0**다. 실제 Docker-source88243 및 작은 metadata 이미지의 Buildx iidfile→Docker inspect→Trivy→CycloneDX 연결60161(1개/47.799초)도 통과했다. 잘못된 역할 거부·실제 controller/builder 자원 상한·nonce 정리를 확인했다. 실제 앱 frontend 빌드 대신 만든 작은 fixture임을 [증거 문서](image-security.md)에 구분했다. 아래 Docker 검사 중 문구는 이전 checkpoint이며 현재 실행 중인 테스트는 없다.

새 Trivy wrapper에서 기존 Nginx index는111 package/advisory 행(critical2/high34)으로 실패, 선택한1.30.4-alpine-slim은21 package/0행으로 통과했다. CycloneDX 변환 전후의 모든 고유 PURL과 이미지 식별자를 대조한다. Nginx 실제 edge2개 회귀도40.989초에 통과했다. root가 scanner/복잡한 테스트/전체 이미지 CI job을 작성했고, Terra가 지적한 library 누락·role 혼동·partial SBOM 통과 조건을 보강했으며 Luna 단순 CI 테스트를 검토했다. [명령·hash·범위·남은 조건](image-security.md).

필수 image-security job을 선택 E2E 조건 밖에 추가했지만 실제 GitHub run과 세 전체 이미지 build/scan은 미완료다. Docker-source image identity도 실제 검사 중이며, remote base scan으로 대체하지 않는다. 전체 로컬 최초 검사1실패/1846통과/353skip/8subtests는 새 세 번째 CI 작업을 허용하지 않던 고정 개수 테스트였고, 모든 builder job의 cleanup을 검사하도록 고쳤다. 최종 재검증은 별도 기록한다. 운영 배포/main push·frontend 자원 증설 없음.

## 최신 확정 — Node24 실제 Linux 실행

Node24 공급/Ubuntu 부분과 실제 runtime packaging tail을 사용한 격리 서버 검사55143은 **1개 통과,467.081초,exit0**다. `sandboxuser`가 실제 실행 스크립트를 직접 실행해 표준입력·한글·BigInt·구문/실행 오류를 검증했고, nonce 빌더·캐시·테스트 이미지 정리까지 통과했다. 소스SHA `2e977994d8800c918c6c904218fc3b6eb6ade82911ccf8ac272c605366ca687d`,512MiB/0.25CPU/256PID 제한이다. [명령과 증거 범위](image-lock.md). 현재 전체 로컬은1793통과·353skip·8subtests/73.35초이며, skip을 실제 환경 검증으로 계산하지 않는다.

Terra의 실행 방식/packaging 검토를 root가 반영했고 Luna fixture를 실제 검사에 사용했다. A09/A11/A12/A17 표의 과거 “진행 중”과 오래된 수치를 terminal 기록에 맞췄다. 이는 이전 소스 통과를 현재 전체 통합 증거로 바꾸는 작업이 아니다. 전체 B++/frontend 빌드·managed rollout/rollback·혼합 부하·대회 E2E·외부 조건은 미완료다. 운영 배포/main push는 하지 않았다.

## 최신 A17 — Node24 LTS와 깨끗한 설치

frontend 이미지·CI 두 작업·`.nvmrc`와 JavaScript 실행 이미지 구성을 Node24.21.0 LTS로 맞췄다. NodeSource 원격 script 실행을 없애고 digest-pinned glibc Node/npm 공급 단계를 사용한다. 새 npm ci에서 DOMPurify 선택 의존성 누락을 재현하고 lock8줄만 보완했다. 전용 복사본의 fresh npm ci·51개 테스트·타입 검사·빌드43.80초 통과, 최신 전체 로컬1787통과·353skip/76.46초다. 최신 SBOM572/43개 실제 재검증2개도 통과했다. Terra CI 설정·Luna 단순 테스트를 root가 검토했고, 복잡한 전환/실행/누락 수정은 root가 수행했다. 자세한 범위는 [이미지 검증](image-lock.md), [의존성 기록](dependency-inventory.md)에 정리했다. Linux 실제 새 이미지 실행/전체 빌드·rollout·부하·외부 조건은 아직 남아 있으며 운영 변경·배포/main push는 하지 않았다.

## 최신 A17 — 외부 기본 이미지 고정

최종 현재 소스 로컬 전체: **1781통과·347skip,77.51초,exit0**(28352). registry 실제 실행 결과와 구분하며 skip은 해당 환경 미검증이다.

외부 기본 이미지7종의 실제 registry index/amd64 manifest를 조회·hash 검증하고 `runtime/image-lock.json`에 기록했다. Dockerfile·Compose·관리형 helper 기본값과 Terra가 수정한9개 live fixture의12개 참조를 같은 digest로 맞췄다. 기존 override와 DB/Redis 무변경 거부 정책은 유지한다. 실제 registry 검사 포함78개/11.59초, Luna 기본값 검사와 root 재사용 검사8개/0.80초 통과. 구체적 변경·검증 범위는 [이미지 lock 문서](image-lock.md)에 기록했다. 실제 컨테이너 시작/전체 앱 빌드는 새 digest로 아직 실행하지 않았으며, Node20 지원 종료 이전·이미지 OS/CVE/컴파일러 프로필과 전체 lifecycle 검증이 남아 있다. 서버 변경·배포/main push 없음.

## 최신 A17 — 잠금 파일 SBOM과 CI 증거 연결

최종 현재 소스 전체 로컬 회귀: **1770통과·340skip,66.81초,exit0**(82396). skip은 외부/플랫폼/opt-in 미검증이며 실제 생성기2개 통과와 구분한다. 아래1700개 기록은 SBOM 변경 전 이력이다.

프런트 npm11.19.1 고정 생성기와 백엔드 pip-audit2.10.1의 실제 CycloneDX 출력을 현재 lock과 대조해 각각571/43개 패키지·버전 일치를 확인했다. npm10의 중복 참조 실패는 재현하고 고정 생성기로 해결했다. 주 에이전트가 정합성 검사/복잡한 변조 회귀를 작성했고 Luna CLI 테스트를 검토했다. Terra가 찾은 raw-only artifact 업로드 경로는 validator outcome 성공 조건으로 막았다. 집중 회귀+기존 CI gate91개, 실제 생성기 통합2개 통과. 구체적 명령·범위·미검증 조건은 [의존성 목록 문서](dependency-inventory.md)에 기록했다. 소스 목록은 이미지 SBOM/서명/전체 graph 검증이 아니며 실제 CI 실행과 이미지 수준 A17 조건은 남아 있다. 서버 증설/배포/운영 데이터 변경/main push는 하지 않았다.

## 최종 상태 정정 — 프런트 빌드 메모리 미해결

위로 이어진 실제 v2(67106)는134.647초 후1GiB V8 heap 부족으로, v3(49813)는203.813초 후1.5GiB heap 부족으로 종료했다. v3 delta는 `202a3652da650fdcc497dbe4d4bb63aeed76e50a9dc539525caf9086158ff2a5`다. 전체 builder2GiB 상한은 세 시도 모두 유지했다. v2에서 backend 실제 이미지 빌드/로드는 성공했지만 frontend와 B++ 전체 빌드는 미완료다. 현재 실행 중인 빌더는 없고 nonce fixture는 정리됐다. 더 큰 테스트 빌드 예산 여부를 사용자에게 확인하며 성공으로 처리하지 않는다.

현재 소스 전체 로컬 결과는 **1700통과·338skip,67.10초**(11018)다. 이 결과는 actual frontend build failure를 상쇄하지 않는다. 아래 v2 실행 중 문구는 당시 이력이다. 전체 목표는 계속 미완료이고 운영 배포/main push는 하지 않았다.

## 최신 실제 빌드 검증 — 진행 중, 전체 완료 아님

- 빌더 v6: 격리 서버의 실제 RUN이 동일 Docker 컨테이너 cgroup에 속하고 CPU·메모리·추가 swap 금지·PID 상한을 상속함을 확인했다. 1개 테스트/38.131초 통과, delta SHA256 `82486a1d32340af44cde8065237f7412afd2139f7d8d436d142ba381caac6dc7`. 앞선 daemon의 `init` 경로만 부모로 요구한 판정은 잘못된 테스트였으며 정정했다.
- CI 정리: setup이 기존 빌더를 거부한 뒤에도 `always()` 단계가 같은 이름의 빌더를 삭제할 수 있는 경로를 수정했다. 성공적으로 전달된 full ID와 재검증이 있어야 정리한다. Luna의 단순 테스트를 주 에이전트가 검토했으며, 실제 Linux shell/fake Docker 회귀는 8개/0.040초 통과했다. GitHub workflow 자체의 실행 결과는 아니다.
- 실제 앱 이미지 v1: SHA256 `e3903cf8c0817418bb4e3edb0ac8789473fcde44b753a62f25d16e2ca60fee9c`, 실행 54548은 117.318초 후 실패했다. 2GiB/no-extra-swap·1CPU·512PID builder에서 실제 frontend `vite build`가 memory exhaustion으로 종료했고, backend 설치는 취소됐다. B++ 소스 빌드는 아직 도달하지 못했다. fixture builder/cache/nonce 이미지 태그는 정리했고 운영 자원은 변경하지 않았다.
- 후속 수정: frontend Dockerfile의 빌드 명령에만 V8 old-space 1024MiB를 지정해 native memory/worker/BuildKit 여유를 남겼다. builder 상한은 완화하지 않았다. v1 위에 v2 delta `6baab4ec1bde3d102272b8455e94693c39d81669ccf7741616c36e6ef6a8f9e9`를 hash 검증 후 적용해 실행 67106에서 실제 재빌드 중이다. 아직 통과가 아니다. 테스트는 초기 14GiB 디스크 여유를 요구하고 8GiB 미만이면 해당 테스트 빌드를 중단한다; 이것이 호스트 전체의 hard disk quota를 뜻하지 않는다.
- v1 소스 전체 로컬 백엔드: 1698통과·338skip/71.04초. frontend: 51테스트·타입 검사·빌드 통과(빌드46.92초, 큰 chunk 경고 남음). 실제 Edge 브라우저에서 receipt polling 2개, desktop/mobile Monaco 2개, 두 탭 충돌 해결 1개 통과했다. API는 fixture로 격리했으므로 실제 서버 생성→참가→채점 흐름을 대신하지 않는다.

전체 managed Compose 최초 시작/전환/drain/rollback, 혼합 부하와 replica 증감, 실제 전체 브라우저 흐름 및 SMTP·백업·보존 정책 등 외부 조건은 여전히 미완료다. 개별 통과나 추정 진행률로 완료 판정하지 않는다. 운영 배포·main push는 하지 않았다.

## 최신 checkpoint — 배포 범위/리터럴 비밀 설정

**최종 v4 전체 로컬도 확정:1624통과·330플랫폼/외부 조건 skip,70.67초,exit0(49162).** 위임 작업과 실행 중 테스트는 모두 종료했다. 현재 소스의 Linux 집중88통과와 로컬 전체 결과를 구분해서 기록하며, skip은 통과로 계산하지 않는다. 아래 실행 중 표기는 역사적 기록이다. 이 변경의 검증 결과는 전체 목표 완료·운영 적용을 뜻하지 않는다.

**최신 v4 실제 확정:88통과,3.71초,skip없음,exit0.** 최종 delta SHA256 `7a1a2d4f7fc4754cd8e921465e21ff826ea66e1cef5eb26e22d468aa7783e3e6`를 기존 별도 stateful96bINc 소스에 hash 검증 후 적용했다. 아래 v1~v3 기록은 중간 증거이며 이 결과가 최신이다. 명령은 아래 v1 명령에 `tests/test_deploy_credential_preflight.py`를 추가하고 basetemp를 `/test-tmp/pytest-secret-scope-v4`로 바꾼 것이다. 같은 `--no-deps`·SQLite·빈 외부 DB/Redis 테스트 URL 및 768MiB/0.5CPU/128PID 제한을 사용했다.

Terra 검토에서 발견한 pathname 재열기·늦은 의미 검증·fsync 시점 교체 후 재읽기를 root가 수정했다. 검증된 부모 directory FD와 최종 파일 FD에 초기화를 묶고, 전후 identity를 확인한 mapping만 prepare 전에 소비한다. 기존 환경 credential도 임의 재생성하지 않는다. root의 복잡한 회귀는 read/write/fsync·부모 rename/symlink 교체, alias·리터럴 길이·환경 credential 보존을 확인한다. Luna가 작성한 단순 Bash 분기 tests를 root가 검토·보강했으며 invalid PG/app 값이 edge adapter 호출·비밀 파일 생성 이전에 거부되는 실제 CLI 경로도 통과했다. Terra 최종 read-only 검토에서 stated path-swap/adoption 범위의 추가 blocker는 없었다.

중간 v2 실제81통과/3.67초, v3 실제86통과/3.70초. v2 전체 로컬4550은1622통과/325skip/73.12초, v3 전체 로컬9888은1622통과/330skip/72.86초다. 이 둘은 최종 v4의 전체 검증으로 합산하지 않는다. 최종 v4 전체 로컬을 별도 실행 중이다. 모든 본래 A01–A25/5.4 요구는 유지하며 전체 앱 Compose rollout·rollback·혼합 부하·브라우저·실제 운영 credential/SMTP 등 미완료 조건을 완료 처리하지 않는다. 운영 변경·배포·main push는 하지 않았다.

**로더 최신 실제 검증:61통과,2.19초,skip없음,exit0.** `runtime-secret-scope-v1` delta SHA256 `af73ae359881624943cd9b35869559765ce0b0c099ffb862c1e8ed2490b4f006`를 hash 확인 후 별도 stateful96bINc 소스에 적용했다(기존 baseline+보존v5+prefixv1 위). 명령은 제한된 audit test-runner에서 `python -m pytest -q tests/test_runtime_secret_scope.py tests/test_runtime_secret_values.py tests/test_deploy_updater_namespace.py tests/test_deployment_project_prefix.py tests/test_managed_deploy_wiring.py tests/test_shared_runtime_config.py --tb=short -p no:cacheprovider --basetemp=/test-tmp/pytest-secret-scope-v1`다. 의존 컨테이너를 추가 시작하지 않도록 `--no-deps`, SQLite 및 빈 TEST_POSTGRES_URL/TEST_REDIS_URL을 사용했다.

실제 Bash에서 명령 치환 모양의 비밀값이 실행되지 않고 그대로 전달됨, POSIX 공개 권한/symlink/FIFO 거부, 기존 export/인용 키 보존·없는 자동 생성 키만 한 번 추가, custom prefix updater의 배포 guard 이전 중단을 확인했다. initializer/updater 테스트는 실제 shell과 복사한 product script를 쓰지만 후속 배포는 marker-only fixture로 막는다. 실제 Compose config도 같은 추출에서 **7통과,1.822초**로 재확인했다. 전체 로컬3724는 실행 중이다. 전체 managed 앱 배포/부하 및 운영 비밀 유효성은 이 결과의 범위가 아니다.

이전 전체55768은 **1853통과·24skip·2subtests,1380.32초,exit0**로 종료했다. baseline `b496048371c9aa1c5685e5d39c4407bebfd99c44b2a1a15ec3b42a7c6782b19e` + 보존 v4 delta `0cb4303d63a695b0554da52448cd875be199eb927c0b0ffa6d6493d3e47175da`의 결과이며, 아래 과거 LIVE 표기는 현재 상태가 아니다. v5 원자적 보존이나 후속 prefix/로더 변경에 대한 전체 검증으로 합산하지 않는다.

A18/A25·5.4: 배포 prefix를 색상 identity·기본 stateful/edge 이름·이미지 태그에 연결했다. prefix-v1 delta `ea1ec9d94da27d45f92ec2166cdbfff16a8d117aea144165d98dbd996e17c6c8`의 실제 호스트 검사 `RUN_SHARED_REDIS_INTEGRATION=1 python3 backend/tests/test_shared_runtime_live.py -v`는 **7통과,2.043초**다. 제품 Bash 함수를 실행해 다섯 Compose overlay의 실제 해석을 확인했으며 서비스 시작이나 전체 배포 검증은 아니다.

후속 로더는 비밀 파일의 shell 실행과 사전 검증 이후 scope 변경을 막는다. root가 FIFO 비차단 거부와 기존 export/인용 키의 초기화 보존도 추가했다. Terra 독립 검토 진행 중이며 Luna의 custom-prefix updater 차단 테스트는 root가 검토하고 timeout을 추가했다. 최신 집중 로컬 **51통과·5POSIX skip,0.84초**는 updater 테스트 추가 전이다. 실제 Linux 검증은 현재 진행할 단계이며 아직 성공으로 기록하지 않는다. 기존 파일 형식 이전·운영 비밀/메일 유효성·전체 managed Compose 수명주기·혼합 부하·브라우저 및 다른 항목의 외부 조건은 남아 있다.

## 현재 검증 checkpoint — 보존 컨테이너와 배포 간 설정 일치

**v5 실제48776 확정:208통과,99.20초,exit0,skip없음.** 양 색상 단일 manifest·빈 선택 고정까지 포함한 현재 코드로4개 실제 Docker inventory 사례 및 관련 회귀를 통과했다. 전체 로컬은1578통과/301skip이다. 단, v4 전체55768은 별도 실행이므로 그 결과를 v5 전체 서버 검증으로 합산하지 않는다.

v5 최신 로컬 전체77985는 **1578통과·301외부/플랫폼skip,69.59초,exit0**다. v5 실제48776은 별도 소스에서 실행 중이며, v4 전체55768은34% 이후 새 출력을 확인했다. 두 실행 소스와 결과를 구분해 보존한다.

후속 v5 보강: Terra 최종 검토에서 최초 선택이 비어 있으면 기준 파일이 없어 나중에 보존 ID가 추가될 수 있음을 확인했다. 주 에이전트가 양 색상(빈 목록 포함)의 선택·설정 기준을 단일 `preserved-stateful.json`에 원자적으로 저장하도록 변경하고, 초기 빈 선택→추가 거부 및 파일 저장 직후 중단→반대색 등록 거부 회귀를 추가했다. 최신 집중 로컬은 **204통과,4.77초**다. v5 delta SHA256 `73a7f87318cf9647166578fa690fe184777fb04b2ec2ddddd481874e38f2313b`를 별도 stateful96bINc 추출에 적용해 실제 검증 중이다. 기존 root t82HFh에서는 v4 전체55768이 진행 중이므로 소스를 덮어쓰지 않았다. v4 결과를 v5 결과로 표시하지 않는다.

최신 확정: v4 실제57982는 **206통과,87.07초,exit0**이며 skip이 없다. 기존 role restart/replacement/정상 종료와 legacy default bridge·Redis/AOF 데이터 보존·동일 ID 설정 변경 거부를 실제 Docker에서 검증했다. 현재 전체 로컬58006은 **1576통과·301외부/플랫폼skip,69.76초,exit0**다. 아래 v4 시작/미확정 문구는 이 종료 결과로 갱신한다. 이 결과를 전체 실제 앱 배포 완료로 확대하지 않는다.

이전 `ingress-cold-v5` 전체 서버47932는 **1810통과·24skip·2subtests,1336.04초,exit0**로 종료했다. 고정 소스 SHA256은 `b496048371c9aa1c5685e5d39c4407bebfd99c44b2a1a15ec3b42a7c6782b19e`다. 아래 과거 실행 중 표기를 이 결과로 정정한다. 새 보존 컨테이너 변경은 그 결과에 포함되지 않는다.

A09/A18/A25·5.4의 첫 전환 검토에서 `--remove-orphans` 없이 남긴 색상별 PostgreSQL·Redis를 전체 inventory가 거부하는 문제가 확인됐다. 임의 삭제 대신 전체 ID로 명시한 기존 stateful 컨테이너만 보존 대상으로 분리했다. 기본값은 빈 목록이며 실제 운영 ID는 설정하지 않았다. 보존 ID는 managed 역할·retirement stop 대상에서 제외하고, 소유 라벨·공용망·양 색상의 전용망에 대한 예외 우회는 거부한다.

Terra의 독립 검토는 같은 ID의 설정 변경을 다음 release에서 새 digest로 받아들이는 결함도 찾았다. 주 에이전트의 `test_preservation_preflight_cannot_rebaseline_changed_config`가 **1실패(DID NOT RAISE)**로 재현했다. 현재는 `prepare`가 release와 별개의 보존 기준을 먼저 저장하고, preflight와 inventory 관찰이 설정·network endpoint·alias까지 비교한다. 목록 누락/교체·preflight 이후 변경·기동 중단 후 재시도에서도 기존 기준을 덮어쓰지 않는다. 복잡한 구현/회귀는 주 에이전트, 단순 입력 검증12개는 Luna max가 작성했고 주 에이전트가 검토했다. 최신 로컬 집중 검사는 **202통과,4.41초**다.

실제 검증 이력:

- 별도 `/home/vulpo/webcompiler-audit-stateful-96bINc`, Compose project `webcompiler-audit-stateful-96binc`, `--no-deps`와 SQLite/빈 TEST_POSTGRES_URL·TEST_REDIS_URL을 사용한다. 기존 전체 검증의 추출 소스는 변경하지 않았다. Compose가 빈 프로젝트 volume을 생성했지만 PostgreSQL·Redis dependency 컨테이너는 추가 기동하지 않았다.
- 초기83761은 **1실패/3미선택,17.40초**였다. 진단10882는 **1실패/3미선택,16.66초**이며 테스트 Redis가 AOF 디렉터리 권한 오류로 종료됨을 확인했다. fixture를 image의 `redis:redis` 계정으로 변경했다. capability 또는 운영 sysctl은 변경하지 않았다.
- 보존 v3 delta `8d41c11a0b2a0a230d430c6fae3992473f8905cd625e31a6fd0e7d5096a0add1`의 실제77489는 **1통과/3미선택,26.32초**다. 기존 Redis/AOF volume·저장 값을 유지한 채 managed fixture 컨테이너7개를 종료하고, 보존 ID를 stop 대상으로 요구하면 거부했다. 이 버전은 후속 설정 기준 고정을 포함하지 않는다.
- 최신 v4 delta `0cb4303d63a695b0554da52448cd875be199eb927c0b0ffa6d6493d3e47175da`를 위 v5 baseline 위에 적용해57982를 시작했다. `RUN_SANDBOX_INTEGRATION=1 pytest -q tests/test_preserved_stateful_inventory.py tests/test_preserved_stateful_config.py tests/test_preserved_stateful_validation.py tests/test_runtime_inventory_live.py tests/test_runtime_inventory.py tests/test_runtime_retirement.py tests/test_edge_deploy.py --tb=short -p no:cacheprovider --basetemp=/test-tmp/pytest-preserved-stateful-v4`. 실제 legacy default bridge, Redis/AOF, same-ID Docker memory 변경 거부를 추가했다. 현재 종료 결과는 아직 미확정이다.

위 실제 inventory fixture의 managed 역할은 sleep/true 또는 최소 Nginx이며 앱·worker 전체 구현이 아니다. 전체 Bash/Compose의 실제 최초 기동·동일 색상 재생성·완전한 retirement·혼합 버전 rollback·혼합 부하·브라우저 E2E, 운영 데이터 이관/메일/보관 정책 등 기존 외부 조건은 그대로 남아 있다. 이번 진행은 운영 변경·배포·main push나 목표 완료를 뜻하지 않는다.

## 실제 ingress 검증 갱신

최신 확정: v5 전체 로컬81513은 **1534통과/300외부·플랫폼skip/72.97초**다. 같은 구현의 실제 host edge 검사37936도 **2통과/41.076초**로 종료했다(실제 Nginx HUP·rollback·프로세스 중단/재시작·기존 HTTP/WS 유지·소켓 파일 보호, 앱/controller는 명시된 fixture). v5 전체 서버47932를 시작했으며 현재 결과는 미확정이다. 추출 소스를 검사 종료 전까지 보존한다.

v2 집중2483은1실패/150통과(32.18초)였다. 진단 delta `ae927476319b2bc015235c92101b32daa32b61d2d3141fbf9d86dc680bb0508f`에서 Nginx가 root로 시작해 제거된 capability로 임시 디렉터리 소유권을 바꾸려다 실패함을 확인했다. 테스트 실행 계정만 비root로 고치고 해당 테스트 디렉터리·소켓 소유권을 맞췄다. 제품 권한을 완화하지 않았다.

v2 본체(`08480386a8acce55afd956e44959f8d0891f59df19ac3fa79ee848fa65e6fff9`)에 최종 단일 테스트 delta `27e4b579cc123f16883e72acf0e1e6c96d4846611dcfbb0eace250ce189fbb8f`를 적용한 실제39038은 **1통과/7.31초/exit0**다. 명령은 `RUN_LB_INTEGRATION=1 pytest -q tests/test_trusted_ingress_live.py --tb=short -p no:cacheprovider --basetemp=/test-tmp/pytest-ingress-fixture-v4`. 실제 Nginx1.27.5 두 hop, 별도 Uvicorn 두 프로세스, 격리 Redis를 사용했다. 두 PID 모두 요청 수신, 사용자 A/B의 서로 다른 IP, 위조 IP·프로토콜 무효화, 명시된 peer의 전달 값 유지, 제어 경로 접근 거부, HTTP+WS 합산 한도429와 다른 사용자의200을 확인했다. 실제 TLS handshake·전체 앱 채점 부하·controller gate는 이 fixture의 검증 범위가 아니다.

실제 Compose 해석도6통과/1.488초(v2), v2 전체 로컬은1534통과/300외부·플랫폼skip/71.26초다. 수정된 fixture까지 포함한 전체 소스는 `ingress-cold-v5`, SHA256 `b496048371c9aa1c5685e5d39c4407bebfd99c44b2a1a15ec3b42a7c6782b19e`로 다시 고정해 전체 검증한다. 운영 반영이나 전체 목표 완료로 표시하지 않는다.

## 최신 보강: 신뢰 프록시와 최초 후보 실패 정리

아래 과거 실행 중 표기보다 이 절이 우선한다. `retention-v1` 전체 서버3838은 **1730통과·23skip·2subtests,1334.11초,exit0**로 종료했다. 이 결과는 이후 프록시 변경을 포함하지 않는다.

현재 `ingress-cold-v2` 고정 SHA256 `08480386a8acce55afd956e44959f8d0891f59df19ac3fa79ee848fa65e6fff9`의 변경:

- A01/A16/A20/A25·5.4: Uvicorn의 선행 proxy-header 처리를 이미지와 Compose 모두에서 끄고, 실제 연결 상대가 명시된 CIDR에 속할 때만 ASGI에서 단일 사용자 IP·프로토콜을 받는다. HTTP와 WebSocket이 같은 정규화·공유 제한을 사용한다. 신뢰되지 않은 전달 헤더는 버리고, 신뢰된 상대의 잘못된/중복 전달 값은400 또는 WebSocket1008로 거부한다.
- API 프록시와 host edge는 각각 확인된 직전 프록시만 신뢰하고 전달 값을 덮어쓴다. realip 적용 후에도 원래 연결 주소로 제어 endpoint 접근을 제한한다. API CIDR은 소유권 검증된 전용 API network에서 공급한다. proxy-control 소유 기록과 edge layout/ACK에 신뢰 정책을 묶어 변경된 정책을 조용히 재사용하지 않는다.
- A09/A18/A25·5.4: 첫 후보의 postflight 실패 후 닫힌 라우팅으로 복구했는데 `retained=None`을 정리기가 거부해 다음 빌드가 계속 막혔다. 소유된 실행 중 edge·닫힌 설정/ACK·두 listener503을 확인하는 경로를 추가했다. 기존 작업/연결/claim·sandbox가 남으면 기다리고, 정확한 물리 종료 증명과 영속 완료 인증서를 남긴 뒤에만 실패 후보 예약과 drain marker를 소비한다. 다음 후보는 새 runtime ID를 받는다.

최신 로컬 집중 명령 `pytest -q tests/test_runtime_retirement.py tests/test_trusted_ingress.py tests/test_ingress_rendering.py tests/test_ingress_validation.py tests/test_shared_runtime_live.py tests/test_shared_runtime_config.py tests/test_managed_deploy_wiring.py --tb=short -p no:cacheprovider`는 **104통과/7플랫폼·외부 조건 skip,3.39초**다. 두 실제 Nginx·두 API 프로세스·공유 Redis 테스트는 작성했으며 현재 소스에서 아직 성공했다고 주장하지 않는다. 테스트의 membership UDS와 TLS 전달 정보는 명시적인 fixture이며, 실제 전체 controller rollout/공개 TLS handshake 검증의 대체물이 아니다.

운영 전 필수: `WEBCOMPILER_EDGE_TRUSTED_INGRESS_CIDRS` 및 `WEBCOMPILER_PROXY_TRUSTED_INGRESS_CIDRS`에 실제 직전 peer를 확인해 명시해야 한다. host loopback→Docker NAT 이후 보이는 주소를 추측하지 않는다. 외부 TLS 계층이 사용자 제공 헤더를 제거/덮어쓰는지 확인해야 한다. 기존 edge owner의 layout에 새 필드가 없으면 자동 채택하지 않으며, 기존 운영 구조→관리형 edge 전환은 별도 승인/검증이 필요하다. 현재 화면/운영 서비스에는 배포하지 않았다. 전체 cold retirement 실행, 구/신 스키마 호환·롤백, 혼합 부하/최종 E2E 및 기존 외부 조건은 미완료다.

## A21 현재 소스 실제 검증 결과

고정 `retention-v1` SHA256 `c24210524adcdbbeec650c38287c8c2e9e3af24692fd78eca5232089fe5cb81b`의 서버 집중65319는 **105통과,121.67초,exit0**로 종료했다(skip/경고 없음). `/home/vulpo/webcompiler-audit-t82HFh`의 제한된 test-runner/격리 PostgreSQL·Redis를 사용했다. 명령은 `RUN_SANDBOX_INTEGRATION=1`과 `pytest -q tests/test_queue_retention.py tests/test_execution_retention.py tests/test_execution_retention_migration.py tests/test_execution_api.py tests/test_execution_retention_owner.py tests/test_submission_durable_integration.py tests/test_housekeeping_retention_pass.py tests/test_submission_retention.py tests/test_execution_http_live.py tests/test_durable_queue.py tests/test_queue_observation.py tests/test_development_initialization.py --tb=short -p no:cacheprovider --basetemp=/test-tmp/pytest-retention-v1`다.

SQLite·실제 PostgreSQL에서 정리/동시성/점수 보존/가산 migration을, 별도 실제 API 2개와 Docker worker로 채점→본문 만료→API 재시작→동일/변경 요청410·타인404·중복 실행/지급 없음까지 검증했다. Compose 실제 해석도 같은 소스에서5통과(1.247초)다. 이는 운영 배포나 v9/v10 혼합 버전 교체 검증이 아니다. 같은 소스 전체 서버 회귀를 후속 실행한다.

이 결과는 아래 A21의 '현재 소스 실제 PG/HTTP 대기'를 대체한다. **보관 기간 승인, 최소 receipt 장기 상한, 큰 이력에서 정리 지연, 실제 버전 교체/전체 rollout 및 나머지 A01–A25/5.4 조건은 남아 있다.** 정책 기본값0/운영 미반영을 유지한다.

최신 실행 상태 정정: 이전 전체63743은 **1671통과/23skip/2subtests,1272.48초,exit0**로 종료했다(ownedpg-registration-v3). 새 A21 소스는 `audit-retention-v1.tar.gz`, SHA256 `c24210524adcdbbeec650c38287c8c2e9e3af24692fd78eca5232089fe5cb81b`로 고정했다. 로컬26623은1455통과297skip(64.84초), 이후 추가된 owner namespace 테스트 및 관련 endpoint/maintenance 최종집중은10통과4PG skip(2.49초)다. 26623의 전체 숫자에 새 테스트를 소급 포함하지 않는다. 새 archive의 실제 서버 검증을 다음 단계로 진행하며, 아래 A21 서버 검증 대기는 여전히 유효하다.

## 최신 로컬 A21 작업 — 검증 범위 분리

이 절이 아래 과거 LIVE 표현보다 우선한다. ownedpg-registration-v3 `e3e0554a69806c322ec794aa6fa523350a33bd4728e82bc47b48f3a4519ef796` 집중82129는 실제125통과(282.77초), 호스트31499는23통과로 종료했다. 동일 소스 전체63743은 현재 실행 중이다. 다음 A21 변경은 그 고정 소스보다 새로우며 **아직 실제 PostgreSQL/전체 서버 통합 검증을 통과했다고 주장하지 않는다**.

- `execution_retention.py`: `EXECUTION_CONTENT_RETENTION_DAYS=0` 기본값으로 새 코드·결과 삭제는 비활성. 승인된 양수 일수를 지정한 경우에만 완료/실패한 일반 실행의 payload/result를 최대500건씩 비운다. 대회 제출 참조, active 상태, lease의 어느 한 필드, 미해결 sandbox operation이 있으면 보존한다. 접수 키·해시·상태·소유자·실행 근거는 유지한다.
- `/executions`와 일반 제출 경로: 삭제된 본문은 소유자에게410/no-store, 타인에게404. 같은 키/변경된 본문 재시도로 새 실행이나 점수 지급을 만들지 않는다. 대회 원본·점수 원장·일반 Submission의 기존 보관 정책은 이 본문 정리로 변경하지 않는다.
- `queue_retention.py`: 공개 완료 이력만 기존 `COMPILER_QUEUE_HISTORY_LIMIT`(기본500)까지 정리하며 회당 최대500건 삭제한다. 접수 시각/id 순서와 `(status, queued_at, id)` 인덱스를 사용하고, 상태별 제한 조회 후 DB 안에서 제한된 결과만 합친다. 정렬을 Python으로 옮겨 DB collation과 달라지는 경계도 피한다. private receipt나 점수 원장을 삭제하지 않는다.
- 실제 재현 추가: 본문이 아직 남은 완료 요청의 공개 이력만 삭제한 뒤 동일 HTTP 요청을 재시도하면 영구 queued 표시가 다시 생성됐다(회귀1실패). 이제 완료 receipt는 해당 표시를 재생성하지 않고 기존 완료 ID·결과를 반환한다. 처음 만든 재현 fixture의 필수 결과 필드 누락은 보완한 뒤 실제 count1/expected0 실패를 확인했다.
- `housekeeping.retention_pass`: 익명 제출·실행 본문·공개 이력을 같은 트랜잭션에서 처리한다. worker와 같은 execution-lock→submission 순서를 사용하고 뒤 단계가 실패하면 앞선 삭제도 rollback한다. Luna 작성 테스트를 주 에이전트가 검토·통합했다.

현재 집중 명령: `pytest -q tests/test_queue_retention.py tests/test_execution_retention.py tests/test_execution_retention_migration.py tests/test_execution_api.py tests/test_submission_durable_integration.py tests/test_housekeeping_retention_pass.py tests/test_submission_retention.py --tb=short -p no:cacheprovider` → **38통과,31외부 PostgreSQL 조건 skip,7.37초**, 경고 없음. SQLite 인덱스 계획, 접수/완료 순서 역전, DB collation, 경계/동시 정리/rollback, v9→v10 가산 migration과 기존 migration 적용 DB의 새 인덱스 복구를 포함한다. 프런트410 자동 재시도 금지는51개 전체 테스트 통과에 포함되며 실제 브라우저 종료 안내까지 증명한 것은 아니다. 최신 전체 로컬23850/프런트 빌드10273 진행 중.

남은 조건: 사용자의 본문 보관 기간 선택, v9 API를 모두 drain한 뒤 정책 활성화하는 실제 교체 검증, 현재 소스의 실제 PG/HTTP·재시작 회귀, 대규모 정리 중 큐 지연 측정, 최소 멱등 receipt의 장기 보관/상한 설계. **receipt는 아직 무기한 남으므로 DB 전체 증가가 해결됐다는 뜻이 아니며 A21 전체 완료가 아니다.** 실제 운영 설정·데이터·배포/main push는 변경하지 않았다.

최신 확정: 위·아래 진행 기록 중 호스트7967은 종료됐다. 현재 고정 소스의 **실제 PostgreSQL 수명 검사1개(18.153초)와 Compose 검사5개(1.421초)가 모두 통과**했다. 최신 실제 readiness/worker/cache 집중82129만 실행 중이며, 첫 readiness 사례의 통과를 관측했다. 나머지 사례와 현재 소스 전체 서버 검증을 대신하지 않는다.

## 현재 통합 소스와 검증 상태

`e3e0554a69806c322ec794aa6fa523350a33bd4728e82bc47b48f3a4519ef796`(ownedpg-registration-v3)의 전체 로컬 검사는 **1,425통과/269외부·플랫폼 skip, 60.91초**로 종료했다. 생성 직후 반환받은 network/container ID까지 최초 inspect와 대조하고, PostgreSQL 준비·테이블 확인을 단일 인증 작업으로 묶으며, GPU/device 요청 설정도 거부한다. 같은 소스의 실제 readiness 4개·worker 복구·DB/cache 집중 검사82129와 최신 PostgreSQL·Compose 호스트 검사7967은 진행 중이다.

이전 cleanup-cache-v1 전체31457은 **4실패/1,610통과/21skip/8경고/2subtests, 1,222.24초**로 종료했다. 네 실패는 모두 `test_readiness_live.py:102–110`의 Docker 불통 worker 등록 대기이며, 로컬 재현과 일치한다. 현재 수정 버전의 실제 결과가 나오기 전에는 해결 검증 완료로 표시하지 않는다. 아래 이전 checkpoint의 실행 중 표기는 당시 이력이다. 운영 배포·실제 데이터 이전·자격증명 확인은 수행하지 않았다.

## 공유 PostgreSQL 보강 검증 갱신

v2의 시작 전 endpoint 문제를 네트워크 **이름 대신 immutable ID로 생성**하는 방식으로 수정했다. 실행 중인 컨테이너의 endpoint ID는 반드시 검사하며, 시작 전/종료 상태의 미할당 endpoint만 고정 NetworkMode ID와 함께 처리한다. v3 실제 격리 검사 **1개 통과(21.921초)**, SHA256 `9587837c550726a551cd012bb61e5291aabc382f5d88573b8ce5e1a8364f8cc7`. 같은 DB를 이용하는 두 클라이언트·재시작·값 보존·소유권/설정 변경 거부와 인증된 앱 테이블 조회를 포함한다. 운영용 Compose의 양색상 credential/대상 일치, 누락 거부 및 개발 조합 보존도 실제 설정 해석 **5개 통과(1.305초)**, SHA256 `9811d9f598b89ebf584ef553434ede9d00d2cfd5d655c4249a4e7fed56ff5a33`다. 이 두 검사는 전체 앱 배포 시험이 아니다.

통합 후속 소스는 `40b87d9d03f44eed9e4b1b4b33215d73991fb5195a2e5308c62e05aa93dbb7b7`이며 현재 전체 로컬39957 검증 중이다. 이전 로컬14013은1417통과/269skip(59.29초)이나 최종 네트워크 변경 전 결과다. 이전 서버 전체31457은 실패4개가 관측된 실행 중 상태다. 실제 worker 등록 수정 재검증, 최신 전체 서버 회귀, 최초 운영 데이터 이관/자격증명 및 전체 rollout gate는 남아 있다.

## 최신 후속 작업: 공유 PostgreSQL 소유권·worker 등록

cleanup-cache-v1 SHA256 `d987066614945d0e80034d3ee2aaee9f30ba856dc867dfe4cdbab950a680bc56` 실제 Docker·PG·Redis 집중 검사는 **95통과(93.11초), setex 사용 중단 경고8개**로 종료했다. 실제 Redis 캐시 적중/TTL/동시 revision 검증을 포함한다. 같은 소스 전체31457은 실행 중이며 **실패4개가 관측되어 통과로 기록하지 않는다**. 현재 추가 수정은 이 이전 소스의 집중 성공으로 검증됐다고 간주하지 않는다.

주 에이전트가 Docker 불통 때 claim 이전 lane 등록이 누락되는 문제를 로컬 회귀로 재현했다(1실패). 등록은 의존성 검사 전에 하되 claim/readiness와 분리하고, stop/drain이 등록으로 풀리지 않게 수정했다. 관련 집중53통과/20외부조건 skip 및 추가 DB 잠금 경쟁 회귀를 작성했다. 전체 로컬14013 진행 중이며 실제 readiness 실패와의 대조·재검증은 남아 있다.

이름만으로 기존 PostgreSQL을 시작·네트워크 연결하던 배포 helper를 소유권/설정 검증으로 대체하고, 운영용 기본 비밀번호를 제거했다. Terra의 production overlay/CI 자격증명 일치·필수 조건과 Luna의 Redis set(ex=ttl) 변경을 검토했다. 별도 실제 PostgreSQL v1 fixture는1개 통과(16.561초)했지만 네트워크 ID·환경 변수 정확 비교를 추가한 v2는 시작 전 endpoint ID가 비어 있어 실패했다. 오류를 구체화한 진단도 같은 원인을 확인했으며, 이 후속 버전은 아직 통과가 아니다. [공유 PostgreSQL 전환 조건](shared-postgres.md)에 운영 자격증명·기존 미소유 데이터의 승인/이전 gate를 기록했다. 운영 데이터·배포·main push는 변경하지 않았다.

## 최신 로컬 구현: 일반 정리 journal(v9)·점수판 revision 캐시(A11)

실제 worker는 claim 시 원래 Docker 데몬 ID를 저장한다. 일반 정리와 만료 복구도 정리 의도를 먼저 저장한 뒤 공통 DB 잠금을 풀고, 원래 worker/pool 라벨과 같은 데몬의 전체 claim 종료를 확인한다. 정리가 거부되면 결과를 완료로 게시하지 않으며, 구버전의 데몬 미확인 작업은 임의 회수하지 않는다. 원래 데몬과 다른 실행 및 journal 없는 bound start도 거부한다. 이 변경은 로컬 구현/회귀 단계이며 최초 구·신 worker 전환과 미관측 요청의 최종 복구 조건은 남아 있다.

Terra의 A11 구현은 공개 점수 셀만 Redis에 15초 TTL로 저장하고, 참가·구성·접수·상태·판정·종료·legacy 복구와 같은 DB 트랜잭션에서 revision을 올린다. 캐시 적중 시 제출/문제 snapshot을 읽지 않고 이름만 필요한 열로 갱신한다. 주 에이전트가 stale ORM revision·커밋 전 캐시 오염·동시 판정 경계를 검토해 보강했으며 두 세션 회귀4통과/4 PG조건 skip, 합산 집중13통과/10외부조건 skip까지 확인했다. 실제 Redis·PG fixture는 작성했지만 아직 현재 소스로 서버에서 실행하지 않았다. Luna의 v8→v9 보존 테스트는1통과/1 PG조건 skip이다.

합쳐진 소스 SHA256 `d987066614945d0e80034d3ee2aaee9f30ba856dc867dfe4cdbab950a680bc56`를 고정했다. 전체 로컬 검증 중이며, 이전 v2 서버 전체93933이 종료되기 전에는 새 소스를 풀어 덮어쓰지 않는다. 운영 데이터 변경·배포·main push는 하지 않았다.

## 최신 검증 대상: 데몬 식별까지 묶은 복구 v2

같은 v2 소스의 호스트 전용 검증도 **21개 모두 통과**했다(정상 종료1, edge2, 공유 Redis/Compose5, 네트워크1, Git/배포 잠금12). 서버 전체 회귀는 아직 실행 중이며 결과 미확정이다.

현재 소스 검증 확정: 전체 로컬 **1,351통과/251외부·플랫폼 skip(57.74초)**, 실제 격리 Docker·PostgreSQL 집중 **97통과(88.77초)**. 같은 소스의 서버 전체 회귀와 호스트 전용21개 검증은 진행 중이다. 실제 컨테이너 생성·시작 후 응답 유실 및 삭제 후 응답 유실, 재접속 복구를 포함하되, 관측 전 프로세스 사망·전체 운영 전환을 검증했다고 확대하지 않는다.

같은 pool 이름으로 다른 Docker 데몬을 보는 경우도 거부하도록, 실제 컨테이너를 관측한 데몬 ID를 복구 단계에 저장하고 삭제/부재 확인/전체 claim 정리에서 재검증한다. 최초 컨테이너 관측이 없는 start의 NotFound도 완료 증거로 쓰지 않는다. 추가 컨테이너가 남아 있으면 작업 폴더와 복구 기록을 유지한다.

v2 SHA256 `f57d120ed2a509c2b1f961c7679b5ff6b4662fa4d8c5b14ba7cb16de9cc133f0`: 로컬 집중26통과/20 PG조건 skip, 새 전체 로컬 및 실제 격리 Docker·PG 검증 진행 중. 직전 v1은 전체 로컬1348통과/248skip 및 격리 집중91통과(79.07초)였으며, v2 보강의 검증 증거로 재사용하지 않는다. 전체 감사 완료 및 운영 배포는 여전히 미완료다.

## 2026-09-10: 미확인 Docker 작업의 확인 가능한 복구 경로

로컬 구현은 만료된 작업의 원래 worker/pool 및 관리 라벨을 검증하고, 실제 확인된 컨테이너 ID를 DB에 저장한 다음 삭제·부재 확인·해당 claim 정리를 수행한다. 삭제 응답이나 DB 완료 저장이 끊겨도 같은 ID로 재시도하며, 늦은 원본 ACK는 정확한 JSON/lease 비교로 거부한다. 느린 Docker 호출 중 공통 큐 DB 잠금은 유지하지 않는다. 생성 이름이 아직 관측되지 않은 경우는 취소로 간주하지 않고 슬롯을 유지한다.

검증 중 소스 SHA256: `704aa712f5686e35bc66ff8a001ad4aa5efa1530d76619e7e743c85ac525b314`. 로컬 집중 회귀23통과/17외부 PG조건 skip, 실제 Docker·PG 집중 검증과 새 전체 로컬 회귀 진행 중. 이전 전체 로컬1336통과/228skip은 정리 경로 보호까지만 포함한다. 임시 격리 컨테이너 외 운영 서비스·데이터는 변경하지 않았다.

이 단계는 A01/A06/A09/A10/A12/A25 및 5.4 복구 조건의 일부다. 관측되지 않은 요청의 최종 조정, 일반 만료 reaper의 원래 pool/provenance 보장, 구버전 worker 최초 전환, 전체 배포·drain·rollback 및 나머지 항목별 외부 검증은 미완료다. 전체 감사 목표 완료나 운영 배포로 해석하지 않는다.

## 지연 Docker 요청의 슬롯 보호 — 구현/검증 진행 중

- 최신 로컬 전체 검사71801 종료: **1331 passed / 223 외부·플랫폼 skipped**,50.82초. strict-xfail은 없으며 지연 요청의 슬롯 보호 재현이 정상 회귀로 통과했다. 자동 reconciliation과 실제 PG/Docker 검증의 완료를 뜻하지 않는다.

- A06/A09/A25/§5.4 후속으로 실행 작업에 `sandbox_operation`을 추가했다. Docker create/start 이전 DB commit, 정확한 응답 이후 해당 요청만 해제, 불확실한 요청이 남은 작업의 완료·자동 재시도·만료 lease 재사용 차단을 연결했다. 요청 이름/operation label도 생성 기록과 연결한다.
- 기존 strict-xfail 지연 생성 재현은 이제 정상 회귀로 통과한다. 별도 세션의 동시 완료·만료 복구, DB commit 실패, 늦은 정상 응답, 취소 후 요청 합류, runtime 증거의 active claim 유지, nullable JSON migration과 반복 초기화 보존을 로컬에서 검사했다. PostgreSQL/실제 Docker 후속 검증은 아직이며, 로컬 전체 검사71801 실행 중이다.
- **자동 복구 완료는 아니다.** 결과가 불확실한 요청의 긍정적 완료/종료 증거를 확보하는 reconciliation, 이 필드를 모르는 v7 worker와의 최초 전환 안전성, 전체 rollout/retirement 검증은 남아 있다. 운영 daemon 재시작이나 운영 배포를 수행하지 않았다.
- 후속 소스 archive SHA `5727837e0bda3724a8d255759245ba562f0443e4828b6d37c5a5effd42b9050a`. 진행 중인 서버 전체 검사96409는 이전 retirement-v2 소스이므로 이 변경의 증거로 사용하지 않는다.

## 최신 종료 절차 검증 — 미완료

- 최신 확인: 별도 호스트 검사3288은 **21개 모두 통과**하고 종료했다. 전체 격리 서버 검사96409만 계속 실행 중이다. 아래 진행 중 표시는 각 기록 시점의 상태다.

- 후속 retirement-v2 SHA `b4ec581af17f6c5a69ec4dc45e6f1ce32965255c5793b6b6bdacbbb1ef8625a5`: 로컬 **1305 passed / 201 skipped / 1 strict-xfail**,50.04초. strict-xfail은 아래 지연 생성 결함을 실제로 재현한 미해결 요구사항이다. 이 소스의 전체 격리 서버 검사96409 및 별도 호스트 검사3288은 진행 중이다. live/initializer의 Docker 재시작 정책 검사를 추가했지만 공유 운영 daemon을 재시작하지는 않았다.

- binding-v5 전체 격리 서버 회귀: **1360 passed / 20 host-tool skipped / 2 subtests passed**, 1110.11초. 별도 같은 소스 호스트 검사20개 통과. archive SHA `41c5f5ad8cce01990941e979b8d5c68141f4ccc8fa1f56370775688697beb7d4`.
- 후속 retirement-v1 SHA `3a9637a677e665f07aed62e1ba1353a9e9f3651b8c2143e2b62398bd3e171fc2`: 로컬 전체 **1273 passed / 201 skipped**(50.32초), 실제 Docker inventory 정상 종료·재시작 거부 및 관련 집중 검사 **101 passed**(62.25초). 호스트 실제 Docker TERM/QUIT 요청 검사1개(두 signal subcase)도6.763초에 통과했다. CLI 타임아웃 뒤 컨테이너 생존, 지연 정상 종료, 같은 수명/재시작 횟수를 직접 확인했다.
- A06/A09/A25/§5.4의 **미해결 결함**: Docker create/start 요청이 통신 오류 후 서버에서 뒤늦게 처리되면 빈 cleanup/list 조회만으로는 종료를 증명할 수 없다. 현재 zero-claim/두 번의 sandbox 조회는 이를 막지 못한다. durable allocation 완료·불확실성 원장/복구를 구현하고 strict-xfail 재현을 정상 회귀로 바꾸기 전에는 retirement를 배포 절차에 연결하지 않는다.
- 위 증거는 전체 cold rollout/rollback·실제 앱 종료·미완료 작업 복구·나머지 A01–A25를 완료했다는 뜻이 아니다. 운영 변경·배포·main push 없음.

runtime-binding-v5(`41c5f5ad8cce01990941e979b8d5c68141f4ccc8fa1f56370775688697beb7d4`) 새 실제 PostgreSQL·API2·worker1 연결 검증이 통과했다(75836,1 passed,192.05초). 실제 컨테이너 namespace에서 조회한 모든 process epoch를 전체 ID에 연결하고, 다른 API의 응답 교환·컨테이너 중단을 거부하며 미완료 websocket2개/claim1개를 보존했다. 테스트의 inventory adapter는 세 프로세스만 다루므로 8-role 구성 전체나 실제 종료 절차의 검증은 아니다. Docker SDK 별칭 설정과 테스트 메모리/모듈 loader 문제를 수정한 후의 결과다. 같은 소스 호스트20개도 통과(25505)했고, 현재 소스 서버 전체 회귀는 새로 실행 중이다.

runtime-binding-v1(`e0531fea33da4462e09f60cb67bf2270c20aff4de76fc13a98418fcf1600f294`) 로컬 전체1181 passed /199 skipped(44.33초). DB 연결 대상·libpq override 검사와 각 컨테이너의 전체 DB snapshot 대조까지 포함한다. 운영과 분리된 새 PostgreSQL/API2/worker1 실제 연결 테스트와 기존 Docker inventory/DB evidence 회귀를 실행 중이다. 직전 runtime-evidence-v1 전체는1302 passed /20 host-tool skipped /2 subtests passed(915.96초)로 종료했고 같은 소스의 별도 호스트20개도 통과했으나 새 binding 검증으로 간주하지 않는다.

DB→Docker 연결 검증을 로컬에 추가했다. 각 컨테이너의 검증된 hostname·전체 ID와 DB의 모든 process epoch·namespace scope를 대조하고, 관찰 전후 Docker/DB 변화·누락·중복·unknown을 거부한다. 읽기 전용 `Deployment.inspect_runtime` 경로이며 실제 종료·DB 정리·drain 기록 삭제는 하지 않는다. 새 집중 테스트129 passed /1 실제 Docker 테스트 skipped(2.09초). 앞선 로컬 전체1169 passed /198 skipped(44.48초) 이후 실제 Docker/PG 연결 테스트 파일과 오류 보강이 추가되어 최신 전체 회귀는 다시 필요하다. Terra hostname 변경과 Luna reader 테스트를 주 에이전트가 검토했다.

프런트 현재 소스는 `npm run test:run` 14 files /47 tests 통과, `npm run typecheck` 통과, `npm run build` 성공(Vite6.4.3,3974 modules)이다. 큰 chunk 경고는 남아 있으며 브라우저/E2E·혼합 부하·전체 배포 검증을 대신하지 않는다. 운영 배포나 main push는 수행하지 않았다.

runtime-evidence-v1(`4004d1c62f712b94fe112221e6b00c3483bf5232f12c06495d5c210829060dca`) 실제 집중76803은122 passed(107.64초)다. PostgreSQL/SQLite 동시 완료 중 일관된 snapshot, 불명확한 lane/요청 종류 거부, 실제 CLI·커널 관찰, 메인 스레드만 종료된 경우의 오판 방지를 검증했다. 로컬 전체1124 passed /198 skipped(43.39초). 같은 소스 전체 서버 회귀/호스트 검사 진행 중이며, 아직 Docker epoch 연결·종료 절차 전체를 완료하지 않았다.

inventory-v5 전체86700은1237 passed /20 host-tool skipped /2 subtests passed(858.61초)로 종료했고, 동일 소스 호스트20개도 통과했다. 이후 로컬에서 종료 검증용 일관된 DB/process 조회와 Linux 다중 스레드 종료 판정 보강을 추가했다. 별도 실제 검사에서 메인 스레드가 Z여도 다른 스레드가 살아 있는 경우를 재현했으며, 새 코드는 전체 스레드 종료가 확인되지 않으면 unknown을 유지한다. 새 소스 집중93 passed /23 skipped(3.30초), 실제 PG/Linux 재검증은 아직 남아 있다. 이전 전체 성공을 이 후속 소스의 검증 증거로 사용하지 않는다.

최신 v5(`f9d63837751ab4b50a0a48f158af5c6884b5339cd46c9c99b24faffaf8b634fe`) 로컬 전체37549는1080 passed /177 skipped(40.49초), 실제 서버 집중70597은85 passed(39.41초)다. 진입망 loopback HTTP, worker24회 재조회, 외부 network member·재시작·교체 거부를 확인했다. 같은 소스로 전체 서버 회귀 및 호스트20개 검사를 시작했으며 결과는 대기 중이다. 운영 반영은 하지 않았다.

최신 v4 집중6301은66 passed(183.04초)다. 실제 API/worker 및 비권한·read-only frontend 최종 이미지의8080 실행이 통과했고, 같은 버전 호스트 검사는18 passed(shared5/network1/Git12)다. 별도48회 읽기 검사에서 Docker Mounts 배열 순서만 변하는 현상을 확인해 v5에서 목적지 기준으로 정규화했다. 이 후속 변경은 별도 검증하며 이전 성공으로 대신하지 않는다. 전체 Compose cold 배포·retirement·혼합 부하 등은 여전히 남아 있다.

최신 inventory-v2 실제 진단25585는2 failed(26.53초)로 종료됐다. 내부 전용 bridge에만 연결된 frontend/api-proxy의 요청 포트와 실제 포트 매핑이 달랐다(null). 진입 전용 bridge 분리와 frontend 비권한8080 실행을 수정·검증 중이며, 포트 검사를 완화해 통과시키지 않는다. 현재 실행 중인 원격 검사는 없고, 아래의 과거 실행 중 표기는 당시 이력이다. 전체 goal은 미완료다.

기준: site-audit-2026-09-09.md A01–A25, 5.4절. 구현 시작 2026-09-09.
배포/main push/운영 데이터 변경은 하지 않는다. 기존 미커밋 변경을 기반으로 개선하며 무관한 보고서 변경은 보존한다.
완료는 코드 작성만이 아니라 항목별 검증 증거로 판정한다. 환경이나 외부 권한이 없으면 미검증으로 남긴다.

최신 inventory-v1(`a76b3f032b2e7a3e3c67e06f81fcf87833cd0aab01b2160ffd3e7cd82417ef55`) 로컬 전체33076은1055 passed /177 skipped(40.37초)다. 실제 소형 Docker 컨테이너 수명/소유권 및 CLI·DB 집중 검사49531은 실행 중이다. 8역할9개 fixture 컨테이너를 사용하며 실제 애플리케이션 Compose 배포 시험과 구분한다. 최신 소스 전체 서버 회귀와 검증된 retirement는 아직 완료하지 않았다.

최신 완료 checkpoint: namespace-v7-v2 전체9140은1145 passed /20 host-tool skipped /2 subtests passed(816.06초)이며 같은 소스의 호스트20개도 통과했다. 후속 Docker inventory는 아직 로컬 검증 중이다. 실제 ID/시작 시점/이미지/역할 label/namespace/network와 loopback 포트를 연결하고, 원문 Docker 출력의 크기·시간과 허용 role 설정을 검사하도록 edge 전환에 연결했다. 집중64 passed /8 skipped(1.44초), 최신 전체 로컬 및 실제 Docker 검증은 남아 있다. 운영 반영이나 검증된 retirement 완료로 보지 않는다.

최신 호스트82561도20개 전부 통과했다(edge2/41.632초,shared5/7.292초,network1/3.484초,Git12/1.269초). 현재 진행 중인 검사는 namespace-v7-v2 전체9140 하나이며, 집중97개/호스트20개 통과를 전체 회귀 완료로 확대하지 않는다.

최신 실제 집중 결과: namespace-v7-v2의1243은97 passed(59.60초), 생략 없이 종료했다. 실제 Linux PID 수명·CLI/SQLite/PostgreSQL·같은 hostname의 다른 Docker PID namespace·marker/Redis 회귀를 포함한다. 같은 소스의 전체9140과 호스트20개82561은 실행 중이다. CLI가 API 미해결 WS와 양쪽 process row를 보존하는 것은 확인했지만, 실제 CLI가 worker의 진행 claim/lease를 보존하는 추가 검사는 남겨둔다(커널 관측 대역을 쓰는 DB 회귀는 통과). 이 결과가 물리적 컨테이너 종료나 전체 배포 검증을 뜻하지는 않는다.

후속 namespace-v7-v2 archive `22eddd9c3b14591c4fed4ea7d248638f9c0584d0d290ccd6c095888303ef1d07`: 로컬 전체990 passed /175 skipped(39.48초), 최종 mock 경로 강화 후 집중58 passed /8 skipped(1.11초). 실제 Linux·Docker·SQLite/PostgreSQL·CLI 집중 검사1243 실행 중이다. 코드 검토에서 확인한 namespace 읽기 오류·stale active marker·DB/CLI 통합 검사를 추가했으며, 운영 컨테이너나 데이터는 변경하지 않았다. 전체 최신 서버 회귀와 물리적 소유권/retirement는 미완료다.

최신 완료 검증: worker-binding-v2 전체 서버48618은1077 passed /20 host-tool skipped /2 subtests passed(776.27초, exit0)이며 같은 소스의 호스트52380에서 생략20개도 통과했다. 후속 namespace v7/scope-v3 로컬 전체41509는971 passed /171 외부·플랫폼 skipped(39.33초)다. 새 namespace 구현은 procfs PID 번호와 PID/user namespace·UID를 함께 대조하고 잘못된 kernel stat을 부재로 취급하지 않는다. 최신 소스의 Linux/Docker 통합 검사는 아직 남아 있으며, 이전1077개 통과로 대신하지 않는다.

현재 우선 기록: worker-binding-v2 집중 검사77339는99 passed(340.78초), 동일 소스 호스트52380은20개 전부 통과했다. 전체48618은52%까지 관측된 실행 중 검사다. 후속 로컬 namespace-observer v7은 다른 PID namespace의 보이지 않는 PID를 종료로 오인하지 않도록 읽기 전용 관측을 추가했으며, Windows의 부재 판정은 지원하지 않고 unknown으로 남긴다. 프로세스 관측으로 DB 미해결 기록을 지우거나 컨테이너를 종료하지 않는다. 물리적 컨테이너 소유권·종료 증명과 전체 retirement는 여전히 미완료다. 아래 오래된 실행 중 기록은 각 시점의 이력이며 최신 소스 검증을 대신하지 않는다.

최신 변경(2026-09-10): worker-process-binding-v2 archive `6d9d4da68834425359500f64cc8d90d86de3ac9d150c9ae65286d65fee185dab`, 로컬930 passed /167 skipped(38.88초,62623 exit0). 실제 집중 검사77339 실행 중. worker process↔lane FK·process-wide fence·남은 claim의 stop 보류·exact runtime metadata 검사와 전용/내장/API startup 취소 cleanup을 보강했다. 이전 API-lifecycle-v2 전체50055는1006 passed /20 host-tool skipped /2 subtests passed(699.89초), 생략20개도 동일 소스 호스트에서 통과했다. 그 완료 결과로 최신 worker binding 검증을 대신하지 않는다.

후속 실행 상태: API-lifecycle-v2 동일 소스의 호스트 검사46696은20개 전부 통과했다(edge2/42.029초,shared5/7.525초,network1/3.335초,Git12/1.211초). 전체 서버50055는 현재 실행 중이며 마지막 관측34%까지 실패가 없었다. 전체 완료 결과는 아직 아니다.

최신 API 수명 검증: `7d2fb8b339e28f4458bfddbcdf2cd869c74d754d1dce3d162a121072b628cc76`(API-lifecycle-v2), 로컬885 passed /141 skipped(45.70초), 실제 전체50055·호스트20개46696 실행 중. 이전 v1 집중 검사는60 passed /2 failed(263.10초): 정상 정리 뒤 SIGTERM을 재전달하는 Uvicorn의 종료 코드를 fixture가0으로만 기대한 문제였다. 종료 코드와 각 프로세스의 DB 정상 종료 기록을 함께 확인하도록 수정했다. 별도 full-stack 재현에서 관리자 감사 로그 중복/404 허위 로그와 CORS 사전 요청의 drain 우회를 확인·수정했다. v2는 실제 API 강제 종료 후 재시작해도 미해결 WS 기록을 덮지 않는 검사도 포함한다. 아직 전체 서버 결과나 검증된 retirement 완료로 보지 않는다.

최신 검증(2026-09-10): process-epoch-v2 archive `e1b1a6b71c68b5f7786c8a572f40d6dfb75a4978effe93820b9828faf4adbe16` 전체 서버 검사 943 passed /20 host-tool skipped /2 subtests passed(637.54초,76826 exit0). 동일 소스 호스트 검사20개도 통과(52480). 후속 API HTTP/WS admission/accounting 소스는 별도이며, 로컬878 passed /141 skipped(35.89초). 새 archive `1f7d40afd6074af1226d1c9fa717285e8ffd2da885c62e2b80c203e5787aa53e`의 실제 API/DB 집중 검사32948 실행 중. 아래 과거 진행 중 표시는 해당 checkpoint 당시 기록이다. 전체 A01–A25/5.4 완료 또는 운영 배포 검증으로 확대하지 않는다.

| 항목 | 담당 | 상태 | 검증/다음 작업 |
|---|---|---|---|
| A01 공개 실행 제한 | 주 에이전트 | 부분 검증 | WS Origin/시작 5초/코드·입출력·frame 한도, HTTP/WS 공통 admission 및 Redis atomic 전역/IP/계정 연결 lease 구현·실Redis검증. 대회/익명 연습 간 대기열 굶주림 방지, 신뢰 프록시와 혼합 LB 부하 검증은 남음 |
| A02 계정 초안 | 주 에이전트 | 로컬 검증 | v2 계정/guest 저장 키, legacy는 guest만, account switch/늦은 GET/잘못된 계정 PUT 방지 4개 테스트 통과 |
| A03 비밀번호/SMTP | 주 에이전트 | 부분 검증 | auth_version로 기존 JWT 폐기, reset CAS/만료 경계 3개 회귀 통과. 실메일 미설정/미검증 |
| A04 0테스트 문제 | 주 에이전트 | 로컬 검증 | 공개 생성/수정 1–200 테스트 필수, legacy 빈 테스트 제출 409. 대회 초안은 유지 |
| A05 삭제 점수 원장 | 주 에이전트 | 로컬 검증 | deleted_at 논리 삭제, 점수/풀이/댓글/레이팅 보존·접근 차단. 동시 삭제/제출 통합 검증 남음 |
| A06 다중 프로세스 큐 | 주 에이전트 | 부분 검증 | DB durable receipt→worker→fenced result 연결. 두 실제 API 중 접수 프로세스 종료 후 다른 API 조회/별도 worker 채점 성공(SQLite·PG). WS API/worker 강제 종료 및 실제 Nginx 경유 실행·receipt 공유 통과. 혼합 부하 검증 남음 |
| A07 실행 출력/로그 | 주 에이전트 | 부분 검증 | 합산 1MiB 스트리밍/초과 종료, Docker 로그 none, swap 금지. 실제 Docker 출력·시간 제한과 WS 한글 입출력/종료 통과. 프록시 경유 느린 소비자·혼합 부하 추가 검증 남음 |
| A08 Docker 권한 분리 | 주 에이전트/Terra ultra | 부분 검증 | 실제 LB의 API nonroot/read-only/socket·소스 mount 없음, worker sandbox 소유 UID/GID·socket 보조 그룹 및 접수 API 종료 후 별도 채점 검증. frontend 최종 Nginx stage의 UID10001/read-only/cap-drop/NNP/tmpfs/8080 실행도 검증. React 빌드는 fixture였으며 전체 이미지 빌드·Compose 수명주기 검증은 남음 |
| A09 재시작/readiness | 주 에이전트/Terra ultra/Luna max | 부분 검증 | PG 초기화/rollback, readiness, controller/edge 복구, worker fence와 API crash/SIGTERM·migration 검증 이력이 있다. runtime-evidence-v1(4004d1c…)의 DB/kernel snapshot·살아 있는 다른 스레드의 unknown 판정은 집중122개, 전체1302개와 호스트20개 검사에서 통과했다. 해당 실행은 종료됐으며 이후 소스의 정확한 컨테이너 종료 증명·retirement·전체 cold Compose/빌드 수명주기 검증을 대신하지 않는다 |
| A10 일반 제출 내구성 | 주 에이전트 | 부분 검증 | 접수 코드·시각·문제 snapshot·job 단일 commit→202→private polling, 동시 정답 1회 지급/rollback/수정 후 retry/한도 거절 원자성 PG 검증. legacy offline 복구/rollback PG 통과; 실제 배포 이관 및 최종 부하 시험 남음 |
| A11 점수판 조회 | Terra ultra/주 에이전트 (초기 Sol 이력) | 부분 검증 | 제출6열·문제3열 projection, 공개 revision 캐시/15초 TTL/같은 transaction bump 구현. cleanup-cache-v1(d987066…) 실제95개에 Redis hit/TTL/동시 revision 검증이 포함됐다. setex 경고 수정 후 ownedpg-registration-v3(e3e0554…) 집중82129도125개 통과로 종료됐다. 이 과거 소스의 증거와 별도로 현재 최종 구성의 대규모 조회 비용·혼합 부하 검증이 남는다 |
| A12 Redis 큐 정체 | 초기 Sol 기여 보존; 주 에이전트 | 부분 검증 | HTTP/WS 모두 DB job 사용, legacy contest/closure/Redis callback 실행기 제거. 공개 큐는 별도 thread에서 SELECT만 수행. initialize-v2(9a385d…) 실제 PG/Redis/Docker 전체245개 검사는 skip 없이186.18초에 종료됐다. 이후 변경된 worker/retirement·혼합 부하·전체 rollout 검증을 그 결과로 대체하지 않는다 |
| A13 저장 충돌/유실 | 주 에이전트 | 부분 검증 | 즉시 local 저장+UUID revision CAS/UTC/동시 수정·삭제 재생성 방지 backend4개 PG 통과, frontend 충돌 테스트 및 실제 Edge 두 탭 충돌→명시 해결 통과 |
| A14 모바일 IDE/목록 | Sol | 부분 검증 | 모바일 full-width 탭/마운트 유지·카드 목록·390px 브라우저 확인. 실제 데이터 카드 검증 남음 |
| A15 503 로그아웃 | Terra | 로컬 검증 | ApiError 상태 보존, 401/403만 세션 폐기, 임시 실패 재시도/회귀 통과 |
| A16 요청/관리 감사 | 주 에이전트 | 부분 검증 | 공유 IP/계정/전체 admission, 실제 Redis multiprocess limit/TTL 통과. 관리자 actor/action/request ID를 변경과 같은 commit에 기록(민감 body/query/token 제외), rollback/동시 context/권한/API 회귀 PG 통과. 감사 조회·보관/배포 프록시 신뢰 설정 남음 |
| A17 의존성/빌드 | 초기 Sol 기여 보존; 현재 주 에이전트/Terra/Luna | 부분 검증 | source-lock SBOM572/43개 대조, 외부8종 digest 고정, Node24 Linux 실행과 프런트 fresh install/51테스트/타입/빌드 통과. Nginx1.30.4-slim의 실제21개 OS package/PURL 및 CVE scan·실제 edge2회귀 통과. 필수 전체-image CI job을 추가했으나 실제 GitHub 실행·세 완성 이미지 검사·compiler inventory·검사 이미지와 운영 artifact 결속은 미완료. [설치 이미지 증거](image-security.md), [의존성 증거](dependency-inventory.md).2GiB 서버 프런트 빌드3회 실패는 로컬 성공으로 상쇄하지 않는다 |
| A18 SHA 배포 | 주 에이전트/Terra ultra/Luna max | 부분 검증 | 정확 CI SHA/main/원본repo/path성공 gate, pinned known_hosts·단일SSH/stdin전달, sync→deploy동일lock, no-force/no-overwrite-ignore, committed archive build, backend/컴파일러SHA태그·B++pin. 실제 임시Git/lock12개+CI/transport회귀 통과. 프런트 최종 image의 static SHA/no-store marker와 잘못된 빌드 인자 거부 실제 검증. 실제GitHub권한/known_hosts secret·production승인규칙·전체고정이미지재빌드·drain배포 검증은 남음 |
| A19 백업 복구 | 주 에이전트/Luna max (초기 Sol 이력) | 부분 검증 | private mktemp/no-clobber custom dump, stdin hash, empty DB 복원. 이전 실제10table 복원에 더해 정식 Docker/PG 회귀에서 관계·한글/CR 경로·덮어쓰기·비어 있지 않은 대상·checksum 거부 통과. 정기일정/외부보관/RPO·RTO 미적용 |
| A20 보안 헤더/origin | Terra/주 에이전트 | 부분 검증 | nosniff/XFO/Referrer/Permissions/512k body limit, CSP Report-Only self-host 정책 및4개 정적 회귀. CSP enforce/HTTPS terminator HSTS·trusted proxy 검증 남음 |
| A21 보관 정책 | 주 에이전트/Terra ultra/Luna max | 부분 검증 | 일반 제출200개/익명7일 정책에 공개 완료 이력 기본500개·회당500건 정리 및 opt-in 실행 본문 만료/410 접수 기록 보존 추가. 기본값0은 본문 만료 비활성. 현재 실제 PG/HTTP 재시작 포함 집중105통과, Compose5통과. 기간 승인, 최소 receipt 장기 상한·대규모 지연·혼합 버전 교체 검증 남음. 상세는 최상단 A21 절 |
| A22 임시 파일 정리 | Terra/주 에이전트 | 부분 검증 | 초기화·파일 작성 실패시 정리 및 미확인 RPC의 컨테이너/작업폴더 증거 보존 검증. v9 일반 정리 journal·원래 데몬/claim 종료 확인 뒤 삭제로 보강했으며 현재 소스 실제 장애 복구 검증 남음 |
| A23 조회/번들 | Terra/Sol/주 에이전트 | 부분 검증 | 커뮤니티 GROUP BY, 13 lazy routes로 초기JS1655→786KB. Monaco/worker self-host 실제 Edge 검증(CDN0). 문제/대회/library 서버 필터 후 pagination/count, 프런트 더보기/필터 재시작 테스트 통과. 대규모 데이터 조회 비용/번들 추가 최적화 검증 남음 |
| A24 안내/접근성 | Terra/Sol | 부분 검증 | tokenless 비밀번호 재설정 요청 폼, Admin 로그인 안내, 모바일 탭 접근성 테스트 통과. 전체 화면 검사 남음 |
| A25 로드밸런싱 | 주 에이전트/Terra ultra 검토/Luna max 단위검사 | 부분 검증 | 다섯 overlay/edge adapter, internal API·frontend plane와 frontend/proxy 전용 ingress, 색상별 loopback 포트·pooler alias·두 peer promotion 구현. 실제 분배·차단·단일 peer 거부·loopback HTTP·별도 edge rollback 중 HTTP/WS 유지 통과. 실제 controller+adapter의 전체 cold 배포·검증된 drain/종료·신뢰 프록시·혼합 부하·장시간 WS·proxy 재생성은 남음 |

## 최신 통합 checkpoint

- **process-epoch-v1 집중 검사 완료:** 실제 Linux private lock·PID/CLI·Redis owner/epoch·지연 보고 경합·SQLite/PG worker 재시작·개발 내장 worker·managed proxy 등102 passed(371.28초,34702 exit0). 이후 코드 검토에서 확인한 조기 종료 revoke와 부분 owner 정보 유실 경계를 보완한 최신 v2는 로컬838 passed /125 skipped(37.68초). archive `e1b1a6b71c68b5f7786c8a572f40d6dfb75a4978effe93820b9828faf4adbe16`의 전체 서버 회귀76826 진행 중이다. 아래 v1의 진행 중 표시는 과거 기록이며 v2 전체 통과의 근거는 아니다.

- **runtime-fence-v2 전체 검증 완료:** 서버846 passed /20 host-tool skipped /2 subtests passed(575.29초,93617 exit0), 호스트20 검사도8895 exit0으로 통과했다. archive `518d97993f46051677e1195415dcdcd0c9cb8966fa4bf5717b04a2bb126aeb2a`. 개발 모드 실제 내장 worker 준비 상태, runtime 충돌 시작 거부 및 영속 종료 차단을 포함한다. 아래 해당 버전의 진행 중 표시는 과거 기록이다.
- **process-epoch-v1 구현·통합 검증 중:** worker 시작마다 새 epoch와 PID 생성 시각을 기록하고 수명 잠금을 유지한다. 별도 readiness CLI는 동일한 private marker와 살아 있는 프로세스를 확인한다. Redis owner/epoch CAS와 최종 revoke로 늦은 상태 보고 및 이전 프로세스 cleanup을 차단한다. 로컬838 passed /123 skipped(32.26초). archive `43eabd340956fc4a623d7fd6b72b14c3bed8061fae6c861dffb44b50ddcdf172`의 실제 Linux/Redis/CLI/재시작/프록시 집중 검사34702 진행 중. 아직 최신 전체 서버 통과 또는 안전한 컨테이너 retirement로 확대하지 않는다.

- **runtime-fence-v1 서버 종료:**838 passed /1 failed /20 host-tool skipped /2 subtests passed(491.64초). 실패는 실제 proxy 시험에서 다른 SHA의 API가 기존 runtime ID를 재사용하면서 새 identity guard에 의해 시작을 거부당한 사례다. 다른 버전/다른 pool 시험 대상은 별도 runtime ID로 수정하고, 동일 ID의 SHA/pool 충돌은 실제 시작 거부 검사로 분리했다. runtime registry 검증을 완화하지 않았다. 호스트20은51545 exit0으로 통과했다. 개발 모드 수정·추가 검사를 포함한 v2 archive `518d97993f46051677e1195415dcdcd0c9cb8966fa4bf5717b04a2bb126aeb2a`로 새 서버 전체93617 검증 중이며 아직 전체 통과를 주장하지 않는다.

- 추가 로컬 수정: 개발 모드 자동 초기화의 readiness marker 누락과 내장 worker heartbeat task 누락을 각각 재현해 수정했다. 개발 초기화도 기존 전용 initializer 트랜잭션을 사용하며 legacy recovery를 임의 허용하지 않는다. 기본 개발 import 반복·자동 초기화 비활성화·production 자동 초기화 거부, 내장 heartbeat 시작/종료 회귀 포함 로컬752 passed /114 skipped(37.18초). 실제 개발 API/내장 worker readiness 검사는 새로 추가했으나 아직 서버에서 실행하지 않았다. 이 최신 로컬 변경은 진행 중인 runtime-fence-v1 서버 검사의 대상이 아니다. v1 전체31000에서 실패 표시1개를 관측했으며 종료 후 상세 원인을 확인한다.

- **incarnation-v2 최종 완료:** 서버748 passed /20 host-tool skipped /2 subtests passed(476.43초,85681 exit0). 같은 소스의 호스트20 검사도77271 exit0으로 통과했다. 아래 해당 버전의 진행 중 기록은 과거 기록이다. 이 결과는 배포 세대 식별/예약 변경의 근거이며 전체 배포·retirement 완료 근거는 아니다.
- **runtime-fence-v1 검증 중:** runtime 전체 worker claim 차단 DB 기록과 정확한 대상의 비공개 CLI, API/worker 시작·readiness 연결을 추가했다. 로컬747 passed /112 외부·플랫폼 skipped(34.58초). archive SHA `cbe42ff810724ef9824e5004decaf62e8e10cd1026e2bccac0bc3b6acecbacbf`의 실제 서버 전체31000 및 호스트20 검사51545 진행 중. 새 lane ID로 재시작해도 차단 유지·기존 claim 완료·두 DB 잠금 순서·identity 충돌·rollback을 검사한다. HTTP/WS 자체 admission/counting, 프로세스 재시작 epoch, 실제 sandbox/컨테이너 부재와 검증된 retirement는 여전히 남아 있다.

- **현재 incarnation-v2 최종 서버 검사 진행 중.** 영속 candidate 예약, 배포 세대와 lane UUID 분리, DB runtime 연관, 정확한 세대의 API/worker/peer/promotion/control-volume 연결을 구현했다. v1 서버746 passed /1 failed /20 host-tool skipped /2 subtests passed(478.15초)에서 실패는 새 필드를 누락한 UDS 응답 기대값 하나였고, 새 실제 세대 분리·정상인 stale API 제외·migration·예약 검사는 통과했다. 기대값과 잘못된 세대의 안정화 시간 재시작 검사를 보완한 v2는 로컬668 passed /100 skipped(30.65초). archive SHA `2d9c4459798990d28311aceeacbf16c67c54a2a75aa973bf98d7b2849d2fd1a1`. 실제 최종 전체 통과는 아직 주장하지 않는다. 아래 worker-fence-v2는 이전 전체 정상 checkpoint다.
- production 시작에는 예약된 nonzero 32-hex `RUNTIME_INSTANCE_ID`가 필요하다. 기존 worker의 알 수 없는 세대는 빈 값으로 남기고 기존 종료 차단을 유지한다. runtime 전체의 admission fence·프로세스 health 식별·API/WS drain·전체 Bash/Compose 배포·검증된 retirement는 아직 남아 있다. 상세: [배포 세대 예약](edge-transactions.md).

- **worker-fence-v2 전체 서버700 passed /20 host-tool skipped /2 subtests passed, 393.60초.** archive SHA `070c9746506eb2beede901b90d92e16bfcf3fcd07f1cde27a77745bb7945d789`. 로컬625 passed /95 외부·플랫폼 skipped(25.60초). 생략된20개는 같은 소스의 호스트 edge2(41.751초)·shared5(8.560초)·network1(2.975초)·Git12(1.276초)로 모두 통과했다. 모든 실행은 종료 코드0이며 archive 이후 제품·테스트 변경 없이 문서만 정리했다. 아래 runtime-pool-v2는 이전 소스다.
- worker lane UUID와 DB claim 소유권, 영속 종료 차단 기록, 추가형 migration 및 schema readiness 버전을 구현했다. 실제 DB 경합·worker crash/sandbox 회수·전용 worker SIGTERM·다른 색상 readiness 유지와 기존 데이터 보존·반복 migration이 SQLite/PG에서 통과했다. 앞선 v1 집중 검사의23 passed/1 failed 중 실패는 PostgreSQL inspector의 dialect 차이였으며 공통 PK API로 테스트를 수정한 뒤 위 전체 검사에서 재검증했다. 구현 범위와 잔여 종료 조건은 [worker 배정 차단](readiness-load-balancing.md)에 기록했다. 배포 runtime 세대·API/WS drain·전체 배포/retirement는 여전히 미완료다.

- **audit-runtime-pool-v2 전체 서버628 passed / 20 host-tool skipped / 2 subtests passed, 377.82초.** 로컬561 passed / 87 외부·플랫폼 skipped(28.18초). 생략된20개는 같은 소스의 호스트 edge2개(42.043초)·공유 서비스5개(7.346초)·network1개(3.252초)·Git/flock12개(1.246초)로 별도 통과했다. archive SHA `76e12367cd5abbe86c3f237ef6acafbe53add595eaa224b4b833755483bd6838`. 이후 제품·테스트 변경은 없고 문서만 정리했다.
- 같은 SHA/DB/Redis/sandbox 범위에서 blue worker만 있을 때 green503, green 시작 뒤 blue 종료 시 green200 유지, 별도 CLI 및 실제 controller의 wrong-pool 제외를 검증했다. 기존 코드는 SQLite·PG에서 모두 green200을 반환해 재현한 뒤 수정했다. 앞선 v1 집중23개(151.89초)와 Compose 실제4개(1.138초)도 통과했다. v2는 끝 LF/CRLF 거부 등 설정 테스트5개를 더 포함한다. 이 결과는 개별 worker 세대/claim 소유권이나 안전한 종료의 완료를 뜻하지 않는다. 아래 adapter-v2는 이전 전체 checkpoint다.

- **audit-edge-adapter-v2 전체 서버610 passed / 20 host-tool skipped / 2 subtests passed, 333.63초.** 로컬543 passed / 87 외부·플랫폼 skipped(27.88초). 생략된20개는 실제 호스트 edge2개(41.690초)·공유 서비스5개(7.679초)·network1개(3.441초)·Git/flock12개(1.293초)로 모두 통과했다. 부모 lock4개(0.839초)도 호스트에서 별도 통과했으며 이4개는 전체610개에도 포함되므로 생략된20개에 중복 합산하지 않는다. archive SHA `f2d583bb157a1ed5b30a010dafef8d16b34b81e17f7fbe83b89bc88ad2ea2f27`. archive 뒤 제품·테스트 변경은 없고 문서만 정리했다. 아래 edge-v5는 이전 소스의 전체 checkpoint다.
- `deploy_server.sh`에 adapter의 preflight/prepare/candidate/switch를 연결했다. committed snapshot이 권위이며 active-color는 호환 표시다. legacy 자동 중지를 제거하고 미완료 drain 기록이 있으면 새 후보 빌드를 거부한다. 이는 종료 구현 완료가 아니다. 별도 실제 edge fixture는 HTTP 역할 대역을 사용하고 controller gate는 stub이므로 전체 Bash 배포/실제 controller/공유 DB 구축을 검증한 것으로 확대하지 않는다.
- 부모가 잠그지 않은 fd9도 adapter가 받아들이던 결함을 Linux에서 재현(3통과/1실패)하고 수정했다. 상속한 파일 설명의 잠금 보유 및 별도 파일 설명의 경합, inode 일치를 검사하며 실제 4개 회귀가 통과했다. 전체 배포·main push·운영 데이터 변경은 실행하지 않았다.

- **audit-edge-v5 전체 서버 570 passed / 20 host-tool skipped, 337.32초.** SHA `9774106c9c8f696cf88d1049b1f76fa15f21ade45db1b1ee19ff76e7fe357cf5`. 생략된20개는 실제 호스트 edge2개(32.458초)·공유Redis/Compose5개(7.070초)·network1개(3.219초)·Git/flock12개(1.304초)로 따로 모두 통과했다. 실제 frontend 최종 stage/managed readiness 및 edge 단위·POSIX 집중 검사73개(93.87초)와 로컬 전체507 passed / 83 외부·플랫폼 skipped(23.79초)도 통과했다. 이 archive 이후 변경은 문서뿐이다. 이전 전체 checkpoint는 아래 이력으로 보존한다.
- edge-v5 당시 새 edge는 정확한 설정 snapshot·intent·commit 복구와 private UDS 응답 검증을 구현했다. 실제 시험에서 발견한 Docker HUP의 자동 재시작 차단, 강제 종료 후 stale socket, 새 worker 확인 직후 public listener handoff 지연을 수정했다. 파일/소켓 보호와 real process crash를 검증했다. 배포 연결은 그 뒤 adapter-v2에서 진행했으며, drain 기록은 종료 완료를 뜻하지 않는다. 상세: [edge 전환과 복구](edge-transactions.md).
- 프런트 marker는 API/SPA fallback이 아닌 최종 Nginx image의 독립 파일이다. production SHA의 newline·대문자·누락·길이 오류와 ENVIRONMENT 오타를 실제 Dockerfile 실행에서 거부하고, 두 경로의 JSON·no-store 응답을 확인했다. React build output은 이 격리 Docker 시험의 fixture이므로 전체 React/Docker pipeline의 증거로 확대하지 않는다.

- **audit-promotion-v3 전체 서버 498 passed / 18 host-tool skipped, 324.08초.** SHA `dcab7e2257ff1a7e37cf6601d325d79fedccc1a3f7a89de2d1e46e72b48d45f7`. 생략된18개는 호스트 공유 Redis/Compose5개(7.731초)·API network1개(3.054초)·Git/flock12개(1.287초)로 별도 통과했다. 로컬 전체436 passed/80 외부·플랫폼 skipped(24.03초), 프런트47개·타입검사·빌드 통과. 큰 번들 경고는 남아 있다. 이 실행 뒤 제품·테스트 변경은 없고 문서만 보완했다. 아래는 이전 checkpoint의 시간순 기록이며 그때의 “최신/미검증” 표현을 현재 상태로 해석하지 않는다.
- 프런트 시험은 실제 Dockerfile 최종 Nginx stage/빌드 인자/격리 네트워크/API 경유/프록시 차단을 검증했지만 React 산출물은 최소 fixture다. 전체 프런트 Docker 빌드·브라우저 E2E 또는 운영 배포를 검증했다고 주장하지 않는다. worker는 여전히 Docker 권한을 가지므로 내부 네트워크 분리가 호스트 침해까지 막는 보안 경계는 아니다.

- **audit-ready-v3: 서버 413 passed / 17 skipped, 295.78초.** SHA `a72b959e88ac06e54a621d6514a6d83b53ebf4d8499cab4e75e45e8e7974b695`. 생략된 호스트 도구 검사는 공유 Redis/Compose 5개(6.812초), 임시 Git/flock 12개(1.260초)로 별도 통과했다. 로컬 전체는 357 passed / 73 외부·플랫폼 skipped(23.41초). 이 전체 실행 후 제품·테스트 코드 추가 변경은 없고 기록만 보완했다.
- 새 controller 통합 시험은 실제 API·worker·Nginx를 사용한다. 준비되지 않은 API/다른 SHA 제외, 두 API 분배, 하나의 API 중지, controller SIGSTOP/SIGCONT·kill/restart, worker 중지/재시작, 제한된 capability 초기화·재실행 보존·다른 pool/SHA 거부를 확인했다. generation 승인/실패 설정 복원/DNS 지연 상한은 별도 단위·TCP 회귀를 포함한다. **전체 운영 배포 연결과 raw keepalive·긴 대기 WS·혼합 부하의 증거는 아니다.** 상세: [readiness 로드밸런싱](readiness-load-balancing.md).

- 이전 **audit-shared-v2: 서버 388 passed / 16 skipped, 236.89초.** SHA `2a72bff6897121bdc6274cfec2b1fb002513b79e537b3e809ebaa80c15ec08a2`. 컨테이너에 없는 호스트 도구 때문에 생략된 항목은 별도 호스트 실행으로 검증했다: 실제 공유 Redis·Compose 4개(6.901초), 임시 Git/flock 12개(1.302초). 로컬 전체는 333 passed / 71 외부·플랫폼 skipped(22.73초). 이후 제품 코드 변경 없이 사전 검사 호출 순서/legacy 보존 정적 회귀를 보강했고 해당 모듈 6개가 로컬·서버 모두 통과했다.
- 공통 Redis URL/namespace와 색상별 DB·Redis 제외 overlay를 배포 경로에 연결했다. Redis 두 클라이언트/반복 provisioning/stop-start/설정·소유권 거부, 관리형·외부 URL/필수 설정 누락/개발용 구성 보존, 실제 CI의 두 색상 Compose 해석을 통과했다. 두 색상·legacy 실행기의 Redis 주소·namespace 불일치와 active 상태 미확인은 전환 전에 거부한다. **운영 blue/green 경로의 managed LB 연결·앱 전환·rollback/drain 검증은 아직 남아 있다.** 상세: [배포 무결성](deployment-integrity.md).

- 이전 **audit-sha-v4: 서버 337 passed / 12 skipped, 236.84초.** SHA `ad415b2fb24b3f22f4a7af799f7034f6327d2435a61e930f74ddad596ff74b54`. 실제 PostgreSQL·Redis·Docker·Nginx를 사용했다. Git 도구가 없는 테스트 컨테이너에서 생략한 12개는 서버 호스트의 새 임시 Git 저장소에서 별도로 통과했다(1.268초). 로컬은 282 passed / 67 외부·플랫폼 skipped(24.37초).
- A18: 공통 앱 환경에 검증 SHA 전달, no-store `/health`의 `deploymentSha`, 공유 PostgreSQL을 직접 가리키는 initializer, 전환 전후 bounded `/ready` 검사 추가. 실제 Compose로 기본·blue·green·LB 설정의 DB 목적지/버전/포트를 검증했다. **실제 배포·이미지 provenance·rollback/drain 검증은 아니다.**
- A19: 실제 백업·복원 스크립트와 PostgreSQL로 두 관련 테이블/한글 데이터 비교, 기존 백업 덮어쓰기 거부, 비어 있지 않은 DB 복원 거부, 잘못된 체크섬의 빈 DB 무변경을 검증했다. 일반/CR 경로 모두 통과. 테스트가 만든 DB·파일만 회수했다. 별도 실서비스 백업 일정·외부 보관·RPO/RTO는 여전히 미설정이다.
- A09/A25: frontend 재시작·healthcheck·CPU/메모리/swap/PID/로그 한도를 추가하고 설정 검증했다. 실제 LB에서는 GET readiness probe가 worker 가동 시 성공하고 종료 시 실패하는 것, API SHA 노출, 2→3→2와 receipt 유지까지 통과했다. 프런트 컨테이너 전체 실행 및 운영 edge 전환은 별도 검증해야 한다.
- 실패 이력: v2는 303 passed / 1 failed(정상 200 응답의 Nginx 내부 redirect 표기 파싱 오류), v3는 330 passed / 1 failed(파일명 escaping에 따른 checksum 비교 오류)였다. 최종 v4에서 원인을 수정하고 회귀·전체 통합 검증했다. 체크섬은 파일명 표기가 아니라 stdin의 실제 내용을 해시한다.
- 다음 작업: **색상 간 공통 Redis·불필요한 색상별 DB/Redis 제거, 준비된 API 복제본만 투입, 색상별 proxy 포트, 전환 rollback·drain·신뢰 ingress**. 실행 본문 보관·점수판 캐시·혼합 부하·전체 E2E·실메일·외부 운영 조건도 남아 있다. 운영 배포/main push/운영 데이터 변경 없음. Goal은 완료가 아니다.

## 이전 검증 이력

- A18 후속 `audit-sha-v2` SHA `da31678270ab7dfb64a76d8426153ed3d0de257a0e009fb9bf797bd6c22a4bab` 전체 서버 회귀 진행 중. 로컬 **253 passed / 63 external-platform skipped**. 서버 호스트의 **실제 Git/flock 검증 12개 통과**(1.258초): 임시 저장소만 사용했고 deploy 본체 대신 마커로 제한했다. Docker·운영 데이터 변경 없음. 아래 265개는 이 변경 전 전체 checkpoint다.
- 새 [배포 무결성 문서](deployment-integrity.md)에 구성·검증과 외부 조건을 기록했다. 자동 updater는 배포와 같은 lock을 먼저 잡고 배포용 SHA 이미지와 다른 stable 태그를 사용한다. 기존 운영 timer를 중지/변경한 것은 아니다. 서브에이전트 정책은 지금부터 적당히 쉬운 작업 Terra ultra, 매우 쉬운 작업 Luna max이며 이전 Sol 결과는 과거 이력으로 유지한다.

- **최신 서버 전체: 265 passed**, skip/warning 없이 230.23초에 완료. `audit-lb-v2` SHA `ddf28596e04a0c962f44d4e9a8c134951d7faf5abfe3436cb63b407f6438bc29`. 실제 PostgreSQL·Redis·Docker와 Nginx LB opt-in을 모두 켰다. 분산/접수 API 종료/작업자 실제 실행/WS 한글/재시작 IP 갱신/공유 제한/2→3→2 및 기존 초기화·복구 회귀가 포함된다. 로컬214passed/51외부skip, 프런트47passed·타입검사·빌드도 통과했다. 대형 번들 경고는 남아 있다.
- 이 checkpoint에서도 **운영 배포·main push는 하지 않았다**. 실제 운영 blue/green 공유 DB·Redis 연결, 검증 SHA/고정 SSH host key, ingress 신뢰·drain, 실행 본문 보관, 점수판 캐시, 혼합10→50→100 부하 및 전체 Compose E2E 등 남은 항목을 계속 진행한다. 테스트 통과 수를 상업 운영 준비 완료로 해석하지 않는다.

- LB 후속 단독 시험: **1 passed, 43.81초**. API 증감 시 DNS peer 세대 변경으로 발생한 502를 발견했고 GET/HEAD에만 한 번 새로운 upstream 선택을 허용한 뒤, 동일 시험을 통과했다. POST/WS 시작은 이 경로에서 재전송하지 않는다. 이전 실패(45.06초)는 이력으로 남긴다.
- 실제 worker는 sandbox 소유 UID/GID와 Docker 소켓 보조 그룹으로 실행하고 쓰기 권한을 확인했다. API는 UID10001·read-only·Docker 소켓/호스트 소스 mount 없음까지 실제 컨테이너에서 검증했다. LB overlay의 `compose config` 및 변경 shell helper `bash -n`은 서버에서 통과(Compose5.1.0). 아직 실제 운영 Compose 실행/배포 검증은 아니다.
- `audit-lb-v2` 전체 서버 회귀는 위 265개 통과로 완료했다. 아래 245개는 이전 전체 checkpoint다.

- **최신 서버 전체: 245 passed**, skip/warning 없이 186.18초에 완료. `initialize-v2` SHA `9a385d437a07383077646b5e9a822ff0e5ffc5be2eb79793a470686110fedbb9`. 실제 PostgreSQL·Redis·Docker를 사용했고, CLI 초기화/동시 초기화/실패 rollback/legacy 복구 및 production-mode API readiness·worker 종료 전환이 포함된다. 프런트 **47 passed**, 타입 검사·빌드 통과.
- 중간 실행에서 readiness 두 건이 실패했다(241 pass/2 fail). Docker 클라이언트 종료 방식 오류를 수정하고 회귀를 추가했으며, 위 최신 전체 실행에서는 모두 통과했다.
- 구형 closure·Redis callback 실행 큐를 제거하고 공개 큐 조회를 별도 thread의 SELECT-only 경로로 유지했다. Compose 최소 마운트·비root API·read-only 파일시스템 설정은 정적 검사 및 실제 `compose config`까지 통과했다. **실제 컨테이너 권한, 프록시 부하 분산, blue/green 공통 Redis와 배포 drain은 아직 미검증/미연결이다.**
- 전환 조건은 [실행 작업자 분리 문서](execution-runtime-migration.md)에 정리했다. 아래는 이전 checkpoint 이력이며 최신 완료 범위를 대체하지 않는다.

- 후속 terminal checkpoint: 서버 **223 passed**(153.84초), WS 한글 입출력/클라이언트 종료/API 강제 종료/worker 강제 종료 및 자동 재실행 방지 확인. frontend **47 passed**, 타입 검사·빌드 통과. 최신 initializer/Compose/readiness 변경은 이 223개 이후이므로 아래 이전 잔여 범위와 구분하며 별도 서버 재검증 중이다.
- Compose의 신규 분리는 아직 기존 blue/green 배포 스크립트와 통합되지 않았다. 특히 initializer의 실제 공유 DB 주소, blue/green 공통 Redis, `/ready` 기반 전환·worker drain, API 최소권한 컨테이너 실증을 마무리하기 전 운영 배포하지 않는다.

- 격리된 배포 호스트에서 전체 backend **206 passed**, skip/warning 없이 완료(113.70초). PostgreSQL/Redis/실제 Docker opt-in 포함. 프런트 **44 passed**, 타입 검사·빌드 및 새 durable 화면 Edge E2E 2개 통과.
- 두 독립 uvicorn API + 별도 `app.worker` 프로세스: 접수 API 종료→다른 API에서 같은 쿠키/요청 ID 조회→재시작 작업자가 실행/일반 점수 지급까지 실제 확인했다. API에는 의도적으로 잘못된 Docker endpoint를 줬으므로 요청 안에서 직접 실행한 결과가 아니다. 이 시험은 reverse proxy 분산 시험이나 운영 Docker 소켓 마운트 분리의 증거는 아니다.
- 컴파일·일반 실행·연습 제출은 202 응답 뒤 private GET으로 결과를 조회한다. 대회는 기존 제출 API 형태를 유지하며 동일 durable 작업/원장 트랜잭션에 연결했다. 레거시 대회 worker는 제거했다.
- 문제 수정 이후 같은 요청 재시도, 동시 정답의 중복 점수 방지, 채점 전에 코드/접수 시각 보존, 한도 거절 시 제출 행까지 rollback, 보관 한도로 일반 이력이 제거된 뒤에도 같은 작업 ID 유지, 합산 sample 진단 UTF-8 256KiB 제한을 검증했다.
- 배포 전 남은 큰 연결: WebSocket 중계/공유 연결 한도, 명시적 DB 초기화·이전 미완료 제출 이관, worker Compose/최소 마운트, 의존성 readiness와 drain, 프록시 신뢰/실제 부하 분산. 새 ExecutionJob payload/result와 공개 queue 기록의 보관 정책도 아직 미완료다. **이 상태는 운영 배포 승인 요청이나 상업 운영 준비 완료 선언이 아니다.**

## 작업 규칙

- 어려운 설계·동시성·보안 테스트는 주 에이전트가 작성한다.
- Terra: 단순·독립 수정 및 테스트. Sol: 중간 난이도 독립 UI/도구 작업 및 테스트.
- 공유 파일 충돌을 막기 위해 파일 소유권을 배정하고 변경 범위 확대 시 먼저 조율한다.
- 운영 장애·봇 부하 시험은 금지. 현재 PC Docker 설치는 이전 사용자 지시로 하지 않으며 격리 실행 환경을 따로 확인한다.

## 1차 로컬 증거 (2026-09-09)

- primary: auth red 3 failures → green, problem integrity red 2 failures → green, queue observation red 2 failures → green. 임시 SQLite DB만 사용.
- 통합 중간 지점: backend 68 passed / frontend 26 passed. 이후 retention 2, durable queue 8, scoreboard projection 1, community count 3을 추가했으므로 최종 전체 재실행 필요.
- SQLite legacy migration 기존 행 보존/default/반복 실행 1 passed. PostgreSQL 실제 migration은 미검증.
- 새 `durable_queue.py`는 기초 모듈이다. 2개 DB engine/동시 스레드에서 멱등 접수, 전체/사용자 한도, claim 한도, lease 만료/갱신/늦은 완료 거부/재시작 입력 보존을 검증했다. 현재 HTTP/WS/대회 실행 경로에 아직 연결하지 않았으므로 공유 큐가 운영 가능해졌다고 판단하지 않는다.
- 다음 필수 연결: 별도 worker 진입점, 접수와 일반/대회 제출 트랜잭션 결합, 오래된 sandbox 회수 후 재시도, 공개 admission/WS 중계, readiness 및 실제 LB 통합. lease 만료 자체는 sandbox 종료를 증명하지 않는다.

## 2차 검증 / 승인된 서버 테스트

- 현재 로컬 checkpoint: backend 108 passed, frontend 30 passed, TypeScript/build passed. backend SQLAlchemy/Pydantic deprecation 2건 및 frontend 대형 번들 경고는 남음.
- 사용자 추가 승인: “배포하는 서버로 테스트 해”. 운영 앱/DB/Redis를 테스트 대상으로 쓰지 않고 같은 호스트의 별도 namespace에 제한된 통합 테스트 환경을 구성했다. 운영 배포/main push 승인은 아님.
- 테스트 root `/home/vulpo/webcompiler-audit-t82HFh`, Compose project `webcompiler-audit-t82h`, image `webcompiler-audit-tests:t82h`. 별도 PostgreSQL/Redis volumes, host port 미노출, 운영 secrets 미사용. CPU/memory/swap/pids 제한과 로그 회전 적용.
- 최초 SCP 전송이 16KiB에서 reset되어 partial archive가 생김. Git OpenSSH SFTP buffer=4096/nrequests=1로 해결, 압축파일 SHA-256 `53cbf2ac33288d47567faf4a4b52abf1c8c303f04b0f6535437f7d6285ee3b92` 일치 후 추출했다. 이후 개별 수정 파일은 같은 전송 경로로 갱신.
- 실제 Linux/Python3.12에서 requirements.lock 43개 해시 설치와 pip check 통과. PyJWT migration으로 python-jose/ecdsa 제거, CI advisory ignore 없음.
- 첫 실제 통합 묶음: 23 passed/1 failed. SQLite/PostgreSQL durable queue 동시성·fencing 16개와 5개 언어·출력 제한·시간 제한은 통과. 실패는 임의 B++ `println(42)` 예제의 ASM receiver diagnostic이며, 실제 제품 템플릿의 `emitln`으로 재검증 중. 이 발견은 지우거나 전체 통과로 집계하지 않음.
- 테스트 중 운영 backend health 정상, load average 1.46(4 cores), 테스트 PG 약39MiB/Redis7MiB/runner71MiB 관측. 테스트 부하를 무제한 올리지 않음.
- 후속 실제 Docker 8/8 통과(제품 emitln 템플릿·6언어·출력/시간한도), 실제 Redis 2/2 통과. PG bootstrap FK flush 순서와 테스트 fixture teardown을 고친 후 전체 PostgreSQL 123 passed/8 opt-in skipped. 이 8개 Docker 테스트는 별도 실행으로 통과했다.
- 이후 HTTP admission+worker/fencing 수정 중이므로 위 숫자는 해당 checkpoint 증거다. 새 worker는 아직 API 실행 경로와 연결하지 않았으며, SIGTERM 복구 실험을 별도 staging에서 준비 중이다.
- 다음 checkpoint: 실제 PG/Redis/Docker 전체 **165 passed**, opt-in skip 없이 실행. SIGTERM worker 재시작 시 두 DB에서 orphan sandbox 회수→다음 작업 성공, claim별 temp 정리도 검증. 기존 3개 backup fixture 실패는 noexec /tmp 때문이었고, 별도 test-only exec tmpfs에서 그대로 통과. 이는 아직 HTTP/WS durable 연결 완료를 의미하지 않는다.
- 브라우저 두 탭 revision 충돌/명시 해결 1 passed, 1440/390px 로컬 Monaco 실제 편집·JS worker same-origin/CDN 0·가로 overflow 없음 2 passed. API는 mock으로 격리했다.
- 실제 백업/복원은 테스트 PostgreSQL `audit_stage`→`audit_restore_t82h_verification`이며, `/tmp/audit-restore-glcEFD/stage.dump` 및 체크섬이 해당 테스트 컨테이너 안에 남아 있다. 운영 데이터를 복제하지 않았다.
