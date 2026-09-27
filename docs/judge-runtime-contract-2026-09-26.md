# measured 실행 계약과 활성화 조건

상태: v1 재생 호환과 v2 PID 증거 계약을 로컬에서 구현·회귀 검증했다. 운영 활성화 및 현재 v2의 실제 Linux/cgroup·다언어 수락 전이다. 별도로 설정된 격리 환경이 있다고 가정하지 않는다.

## 접수부터 결과까지

접수 시 문제 정책의 언어별 절대 제한, 테스트 지문, 정책 ID/revision/hash, 실행기 hash, 전체 작업 deadline을 복사한다. 워커는 현재 문제 값을 다시 읽어 제한을 바꾸지 않는다. 자원 큐는 compile/run 중 큰 메모리와 외부 overhead, CPU 1개분을 예약한다.

숨김 `stored-v1` 데이터는 내용 대신 해시/원본 크기/UTF-8 참조를 고정한다. 이 경우만 `testDataBufferBytes = 12 × 최대 케이스(입력+정답 bytes) + 131072`를 영수증에 추가하고 `reservationBytes`에도 더한다. API·큐·워커가 같은 식과 엄격한 정수 타입을 다시 확인한다. 기존 인라인 지문·영수증 필드 집합은 바꾸지 않는다. 측정 정책 없는 참조 실행은 거절한다. 워커는 짧은 DB 세션으로 한 케이스를 복원하고 무결성을 재확인한 뒤 실행한다. 자세한 검증 범위와 아직 미측정인 외부 버퍼 최고치는 [대용량 데이터 기록](judge-test-data-storage-2026-09-26.md)을 따른다.

승인된 런타임에 한해 컴파일 컨테이너를 한 번 실행한다. 성공한 산출물은 최대 8 MiB/512항목의 일반 파일만 허용하며, 경로 이탈·링크·특수 파일·충돌·덮어쓰기를 거부한다. 호스트에서 산출물을 실행하지 않는다. 케이스마다 새 컨테이너에 읽기 전용 산출물과 해당 입력만 제공한다. 숨김 정답이나 다른 케이스 입력은 마운트하지 않는다.

PID 1 감독기는 KILL/SETUID/SETGID만 보유하고, 자식은 UID/GID 65534로 실행한다. 부모만 접근할 수 있는 완료 기록과 출력 파일을 사용하며 참가자 stdout/stderr를 자원 증거로 파싱하지 않는다. cgroup v2의 CPU 누적량, memory peak/OOM kill, `pids.events`의 `max` 누적값과 monotonic wall을 사용하고 자손까지 회수한 뒤 기록을 확정한다. v2에서는 PID counter가 없거나 줄어들면 안전하게 system error로 중단하며, OOM 증거가 PID 증거보다 우선한다. 부모 관측 비용/출력 tmpfs는 측정 범위에 포함되므로 이 실행 방식으로 기준 풀이를 측정해야 한다.

실행 중 Docker exec로 counter를 polling하지 않는다. 완료 신호 후에만 고정된 수집 명령을 실행한다. 취소되면 진행 중 수집/파일 쓰기가 끝나는 것을 확인한 뒤 정리한다. Docker 연결·ping·image 확인도 별도 스레드로 처리해 워커 heartbeat를 막지 않는다.

## 운영자 등록부

`JUDGE_RUNTIME_REGISTRY`는 운영자가 관리하는 JSON 파일의 **절대 경로**다. 기본값은 빈 문자열이며 measured 실행을 거부한다. API에서 등록부를 만들거나 런타임을 자동 승인하지 않는다.

API에도 동일한 승인 등록부를 읽기 전용으로 제공해야 한다. 문제 공개·새 제출 접수 시 모든 언어 프로필을 등록부와 대조하고, 없거나 다른 경우 거절한다. 이미 접수된 동일 요청 ID의 재시도는 기존 영수증을 그대로 돌려준다. 등록부 일치는 설정 승인 확인이며 **실제 워커의 현재 가동 여부나 이미지 존재 확인이 아니다**. 워커는 실행 단계에서 자신의 등급과 실제 이미지 ID를 다시 검사한다.

- 최상위 필드: 정수 `version: 1`, `runtimes` 배열(1–100개).
- 런타임 항목의 정확한 필드: `language`, `runtimeId`, `runtimeVersion`, `imageDigest`, `workerClass`, `toolchainProfile`, `launcherDigest`.
- 이미지와 실행기는 `sha256:`와 64자리 소문자 hex. 현재 구현의 imageDigest는 로컬 Docker image ID와 정확하게 대조한다. 가변 tag는 사용하지 않고 이미지를 자동 pull하지 않는다.
- 동일 language/runtimeId/imageDigest/workerClass 항목 중복, 알 수 없는 필드, JSON 중복 키, 64 KiB 초과 파일을 거부한다.
- 선택한 정책과 등록부의 runtimeVersion/toolchainProfile/workerClass/launcherDigest가 일치해야 한다. 새 접수는 등록부 버전과 `admitNew` 값만 신뢰하지 않고 현재 toolchain profile과 설치된 `linux_phase_launcher.py`의 정확한 바이트 해시를 모두 요구한다. archive의 실행기 해시는 기존 영수증 재생에만 허용한다.
- 정책의 launcherDigest는 초안에서만 생략 가능하다. 공개 gate·실행 receipt에서는 필수다. 실행기가 바뀌면 측정 지문도 바뀌므로 기존 증거를 재사용할 수 없다. 구버전 접수를 새 등록부로 묵시적으로 실행하지 않는다.

명령은 서버 코드의 고정된 toolchain ID로 선택한다. 참가자나 관리자 JSON의 임의 shell/flags/path를 실행하지 않는다. 현재 v2 ID는 `c17-o2-pids-v2`, `cpp17-o2-pids-v2`, `cpython-pyc-pids-v2`, `java-main-pids-v2`, `node-check-pids-v2`, `bpp-native-o1-v3-pids`다. v1 프로필과 B++ tmp-split 프로필은 기존 영수증의 정확한 재생에만 남겨 두고 새 접수에는 사용할 수 없다. 이 목록은 실제 설치 이미지마다 경로/버전/성능을 승인했다는 의미가 아니다. 현재 v2의 실제 격리 실행과 60개 문제×언어 제한 측정은 후속 검증이다.

현재 감독 실행기 SHA-256은 `f0c312fae392b12afde745c59044a03fe05830b7942115475227231081c87fcf`, supervisor record v2 소스는 `c3d6f5f9d6b10e6b007bf8e0f1293909bcf8bac6831af9286beb975fc3fe2d30`, container contract v2 소스는 `0522bdf65dda2a007f86a49a49d823550da59a196960528e1ae002a58f2f5a61`로 고정한다. 이전 감독 실행기 `908bb710244512ea3f655831a7aa84b4fb5d6ec370cd32e558f14944fbc0e505`는 동일 해시의 읽기 전용 archive에서 v1 영수증을 재생할 때만 선택한다. v1/v2 record 또는 container 필드를 섞은 입력은 거절한다.

## 오류 구분과 호환성

- 신뢰된 단계별 CPU/wall 초과는 TLE, OOM kill은 MLE, 제한보다 많은 출력은 OLE, 증가한 `pids.events:max`는 `process_limit_exceeded`다. OOM 증거가 동시에 있으면 MLE가 우선한다.
- 컴파일 단계의 자원 초과는 `compile_resource_error`로 분리하고 대회 오답 패널티에서 제외한다.
- 완료 기록 부재, 등록부/이미지/해시 불일치, RPC/전체 작업 watchdog 만료는 `system_error`다. 참가자에게 증거 없는 TLE를 부과하지 않고 기존 제한된 재처리 정책을 적용한다.
- 기록된 jobDeadlineMs를 사용하되 현재 서비스 안전 상한을 넘으면 거부한다. 단계별 제한을 몰래 줄이지 않는다.
- 기존 NULL 정책/legacy-v1은 기존 실행기를 유지한다. measured 실행 불가 시 legacy 실행기로 대체하지 않는다.

## 아직 활성화하면 안 되는 이유

보호된 단계별 보고서의 영속 저장·공개 합계/최대값 분리와 v15 추가형 마이그레이션은 [자원 측정 기록 검증](judge-metrics-verification-2026-09-26.md)에 기록했다. Java의 한글·Unicode 클래스명은 그대로 보관하며, PAX 경로 확장만 허용한다. 경로 이탈·링크·Windows 예약 이름·대소문자/정규화 충돌·제어문자·그 밖의 확장 메타데이터는 파일을 쓰기 전에 거절한다. 안전한 이식성을 위해 240 UTF-8 바이트보다 긴 전체 경로와 일부 제어/format 문자가 포함된 이름은 지원하지 않는다.

이 구현만으로 공개/배포 준비가 끝나지 않는다. 실제 워커 준비 상태의 공개·접수 gate 연결, 운영 예산/외부 버퍼 overhead 검증, PostgreSQL의 재시작·경쟁·정리 실패 시나리오, 다언어 런타임·기준 풀이 반복 측정과 재채점 감사 이력이 남아 있다. 등록부/정책 승인은 실제 증거를 확인한 뒤 별도로 수행해야 한다.

실제 실행 값과 정리 증거는 [격리 실행기 검증](judge-measured-launcher-verification-2026-09-26.md), 큐 예약의 전제는 [자원 예약 검증](judge-resource-scheduling-2026-09-26.md)을 참고한다.
