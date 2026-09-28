# 계측 채점 접수 기록 재생: 코드 교체 경계

운영 설정이나 사용자 설정을 변경하지 않았다. 이 문서는 격리 테스트에서 확인한 구현 범위와 남은 수락 조건을 구분한다.

## 현재 구현

- 채점 접수 시 확정한 런처 SHA-256에 맞는 파이썬 소스를 현재 파일 또는 `launcher_archive/sha256-<digest>.py`에서 읽는다. 파일 크기·일반 파일 여부·해시를 확인하고, 불일치·누락·심볼릭 링크는 거절한다.
- 런타임 레지스트리 v2의 `admitNew=false` 항목은 기존 접수 기록 재생만 허용하고 신규 접수는 막는다. v1 형식과 현재 런처는 계속 지원한다. 동일성에는 정책·이미지·워커 클래스·런처·언어·빌드/실행 명령이 포함된다.
- 워커는 큐 작업을 가져오기 **전에** 사용 가능한 런처 스냅샷을 준비한다. 과거 접수 기록에 해당하는 신뢰 가능한 스냅샷이 없으면 그 작업을 대기 상태와 시도 횟수 0으로 남겨두고 다음 실행 가능한 작업을 처리한다. 가져온 작업은 고정한 소스 바이트로 단계 실행기를 호출한다.
- 실제 Docker 워커는 같은 데몬 ID에서 등록된 **로컬 이미지 ID**를 선점 전에 읽기 전용 조회한다. ID가 없거나 다르면 해당 계측 작업만 대기시키며, 자동 pull/build는 하지 않는다. 데몬 변경이나 조회 장애는 선점 전에 워커 반복을 실패시킨다. 실행 직전의 두 번째 이미지 확인은 조회와 실행 사이 삭제 경쟁을 막기 위해 유지한다.
- 워커 클래스는 워커 생성 시 고정하고 자원 예산 클래스와 일치해야 한다. 전역 설정값이 이후 바뀌어도 이미 선택한 스냅샷의 클래스를 다시 해석하지 않는다.
- `(언어, toolchainProfile)`을 키로 하는 신뢰된 실행 레시피 카탈로그를 추가했다. 현재 6개 레시피의 소스 파일명, 고정 compile/run 인자, 산출물 계약 ID, tmpfs 배치를 지문으로 고정하고 선점 전에 스냅샷에 담는다. 동일 프로필의 선언을 수정하면 지문 검사가 실패한다. 현재 등록부는 그대로 신규 접수에 사용할 수 있고, 어댑터가 없는 v2 replay-only 항목은 그 작업만 대기시킨다. 과거 B++ v1 레시피를 확인 없이 만들어 카탈로그에 추가하지는 않았다.
- `bounded-tar-v1` 산출물 수집·해제 구현을 `judge_artifact_contract_v1.py`로 분리하고, LF 소스 SHA-256 `10ffee31249f320ec10e0391cd91963324f42a004b07cc2c40e04d28e9d1dc4a`의 일반 파일만 선점 전에 받아들인다. 선택한 두 함수는 런타임 스냅샷에 고정한다. 파일 누락·변조 또는 알 수 없는 계약은 해당 작업을 선점하지 않는다. 이 코드는 기존 v1 동작을 옮긴 것이며 실제 과거 산출물 파일의 독립 재생을 증명한 것은 아니다.
- `measured-container-v1`의 기존 tmpfs·마운트·Docker 생성 옵션을 별도 파일(LF SHA-256 `c9031e0b100ddfdf9a2d839f268fa13ee1ffb2b90b67a313ea408ee259281f01`)로 분리했다. 레시피의 컨테이너 계약 ID를 내부 지문에 포함하고, 선점 전에 구현 파일을 검사해 선택한 생성 함수를 스냅샷에 고정한다. 기존 접수 기록의 프로필 이름과 JSON 형식은 바꾸지 않았다.
- `supervisor-record-v1`의 기존 중복 필드·OOM 증거·CPU/wall/출력 판정 parser를 별도 파일(LF SHA-256 `fdd5f1506d994ea3fab5282d8f540324a19065837117969ca0e23fa2ce4500d9`)로 분리했다. 컨테이너 계약 선택 시 parser 소스도 선점 전에 검사하며, `_read_record`는 선택한 함수로만 기록을 해석한다. 외부에서 쓰는 `decode_report` 이름은 유지했다.
- `measured-collection-v1`의 기존 `/control` 출력 읽기·출력량 대조·컴파일 산출물 전달을 별도 파일(LF SHA-256 `3929e47342808b38aa9b73a8fae4af51a37cce2934ea97521b7deea923cdf87e`)로 분리했다. 선택한 수집 함수를 스냅샷에 담고 파일 변조·누락은 선점 전 거절한다.
- 현재 런처와 동일한 파일의 보관본을 포함했다. 이 보관본만으로 향후 다른 코드/이미지/툴체인에서 과거 작업이 실행된다고 주장하지 않는다.

## 확인한 범위

| 증거 | 결과 | 경계 |
|---|---|---|
| [런처 카탈로그 Linux 원시 결과](evidence/launcher-replay-catalog-linux-2026-09-27.json) | 242 PASS, 1 Java 도구 SKIP | 이전 단계: 보관 런처 선택·해시 검사. 실제 Docker 채점 재시작 수락 아님 |
| [선점 전 검사 첫 결과](evidence/receipt-replay-preclaim-r1-2026-09-27.json) | 294 PASS, 3 FAIL, 1 SKIP | 오래된 워커 테스트 fixture 3개가 등록 파일 없이 측정 작업을 선점한다고 가정해 실패. 실패 기록 보존 |
| [수정 후 Linux 원시 결과](evidence/receipt-replay-preclaim-r2-2026-09-27.json) | 297 PASS, 1 Java 도구 SKIP, 47.59초 | 소스 `59b7d10126fcee6db92501cba95569fec5f57691c82cc5e453fc6801821a5774`, 도구 `3afe33aaaa9ec4855237745e11356eef611ebcd778269bac534cd948f0dd4c18`, 원시 결과 SHA-256 `f50fd8297026b6be8b5cd94a6fff3535f7e72431a2beeccf4053105c543a02f4` |
| [이미지 선점 검사 첫 결과](evidence/receipt-image-preflight-r1-2026-09-27.json) | 299 PASS, 1 Java 도구 SKIP | 보관 런처와 이미지 조회, 정확한 ID·동일 데몬 검사를 포함. 소스 `3545747e25f72932e02c73a9edb555067d2253eb1fd7a9b94bc75f56583dcc25`, 원시 결과 SHA-256 `bb69e0851d5bc3efef3fd5b5711d070548c818724a1b38815f79f56fb066ef63` |
| [워커 클래스 고정 후 결과](evidence/receipt-image-preflight-r2-2026-09-27.json) | 301 PASS, 1 Java 도구 SKIP, 47.28초 | 소스 `a0f0eff536a21fd349a5865c92e5258ede1894374bac88f56b68b410ca25d3bd`, 도구 `3afe33aaaa9ec4855237745e11356eef611ebcd778269bac534cd948f0dd4c18`, 원시 결과 SHA-256 `4ec72d448f8a6deac2444307ddb0e5c751a500be56c69359ea801e1278177926` |
| [어댑터 카탈로그 첫 결과](evidence/receipt-toolchain-catalog-r1-2026-09-27.json) | 304 PASS, 1 Java 도구 SKIP | 소스 `b508b6d2bf67ed7a04ddc4bb0c33ca1725a0c512a117f31e300c706d36e2d399`, 원시 결과 SHA-256 `8acb478aa00c4be02b3ab937488f5d44264c30e894da596fca27392d80eeda91` |
| [replay-only 누락 분리 후 결과](evidence/receipt-toolchain-catalog-r2-2026-09-27.json) | 306 PASS, 1 Java 도구 SKIP, 47.76초 | 소스 `50476906c23194aa37277e6ef3d405d36f759f905a47ef16dc9ccdbf4b18a517`, 도구 `3afe33aaaa9ec4855237745e11356eef611ebcd778269bac534cd948f0dd4c18`, 원시 결과 SHA-256 `9a1a36af3f0eab940d949fbcc6119f47fe42393c8d96b7f019920b20759dfba8` |
| [산출물 계약 첫 결과](evidence/receipt-artifact-v1-r1-2026-09-27.json) | 306 PASS, 1 FAIL, 1 Java 도구 SKIP | 이동 전 모듈의 상수를 바꾸던 기존 테스트가 실패했다. 실패를 보존하고 새 v1 모듈을 대상으로 수정했다. 소스 `2e797d9e96a8bc2c3fb5a40edb76172af38a118efb79db8d852c8c2f6b193194`, 원시 결과 SHA-256 `41b471b5fd7e2ff0927222a92eb7491027531ff872f53a1135dbf5cf26ef23ac` |
| [수정 후 산출물 계약 결과](evidence/receipt-artifact-v1-r2-2026-09-27.json) | 307 PASS, 1 Java 도구 SKIP, 48.28초 | 소스 `1c508b8a57eb277bda2cb2eff24d79907ce2a2ddb396d4aaa842534c1dab9d03`, 도구 `3afe33aaaa9ec4855237745e11356eef611ebcd778269bac534cd948f0dd4c18`, 원시 결과 SHA-256 `53dc0f47ee25679c9f6f251e3a11b0ba68fb9f4f327a808efb0da131a38a169d` |
| [컨테이너 규격 분리 후 결과](evidence/receipt-container-v1-r1-2026-09-27.json) | 310 PASS, 1 Java 도구 SKIP, 47.59초 | 소스 `eb27e3caf1fa3e3de2c38a3fa3e79116b259ed82a7362d3ad8c44393c91b5e3c`, 도구 `3afe33aaaa9ec4855237745e11356eef611ebcd778269bac534cd948f0dd4c18`, 원시 결과 SHA-256 `f35e9d719cb295a224a21305e00dc165a82f338757a0f0f0fa209e48b541ccad` |
| [보고서 parser 고정 후 결과](evidence/receipt-record-v1-r1-2026-09-27.json) | 311 PASS, 1 Java 도구 SKIP, 47.93초 | 소스 `60aa802683a5348bfe31708478bc08beeccc3b05c8cae0cf7052426eb3608a76`, 도구 `3afe33aaaa9ec4855237745e11356eef611ebcd778269bac534cd948f0dd4c18`, 원시 결과 SHA-256 `c28162ff8e7db2cc29737d8ddb94e6cbc3e188aef896751f7ee7788dc6bc6de0` |
| [출력 수집 고정 후 결과](evidence/receipt-collection-v1-r1-2026-09-27.json) | 313 PASS, 1 Java 도구 SKIP, 49.71초 | 소스 `59954fa126256fd4902fcef4f8d09a71368bf57aef772e1b0ee7d48a8dc019cb`, 도구 `3afe33aaaa9ec4855237745e11356eef611ebcd778269bac534cd948f0dd4c18`, 원시 결과 SHA-256 `6faead29d6c0f2372c6ff54067ff19febe8b60d19c5f6c1183f5c7a615fff128` |

이 묶음의 큐/워커 회귀는 SQLite fixture, 모의 Docker 이미지 객체와 합성 채점기를 사용한다. 격리 하네스의 임시 PostgreSQL 서비스가 이 10개 모듈의 DB 실행 경로를 대체하거나 실제 Docker 이미지 preflight를 증명한 것은 아니다. 결과 파일은 서버/로컬 해시를 대조했다. 정확히 소유한 테스트 경로는 실경로·소유권·링크 및 테스트 컨테이너 부재를 확인한 뒤 삭제했고 부재를 재확인했다. 첫 이미지 검증 시도는 임시 경로 이름이 하네스 규칙에 맞지 않아 컨테이너 생성 전 거절됐으며, 검증 규칙을 유지한 채 새 경로에서 재실행하고 두 경로 모두 정리했다.

별도로 [현재 코드의 격리된 실제 Python 채점 경로](evidence/receipt-measured-pipeline-v1-2026-09-27.md)에서 기존 이미지로 컴파일 1회·서로 분리된 케이스 컨테이너 2개를 실행해 AC, 읽기 전용 산출물, 작업 디렉터리/컨테이너 잔여 0개를 확인했다. 출력 수집 분리 후에도 같은 범위를 재실행해 AC였다. 이는 현재 코드의 실제 Docker 실행 확인이지만 DB/Redis 큐 재시작이나 과거 이미지·프로필 재생은 아니다.

## 미완료 수락 조건

- 선점 전 이미지 **존재 확인 코드**는 추가했지만 과거 Docker 이미지와 도구체인을 실제로 보존·선택하는 배포 절차는 없다. 현재 명령·산출물·컨테이너 생성 옵션·보고서 parser·출력 수집은 선택한 계약에 고정되지만, 비동기 타임아웃/정리 흐름은 여전히 현재 코드에 묶여 있다.
- 현재 레시피는 6개 모두 지문으로 고정했지만, 실제 과거 버전의 레시피 파일·이미지는 아직 보유하지 않는다. v1 구현 소스 해시 검사는 변경을 거절하는 장치이지 과거 버전 아카이브가 아니다. Docker 데몬의 암묵적 기본값도 검증·고정해야 한다. 합성 과거 프로필 회귀는 설계 검증이지 실제 이전 릴리스 재생 증거가 아니다.
- 과거 `workerClass`를 실행할 워커 레인과 배포 시 drain/복구 절차가 없으면 오래된 작업은 대기할 수 있다. 지원 불가능한 기록을 새 실행기에서 억지로 처리하거나 시스템 오류로 완료 처리해서는 안 된다.
- 실제 PostgreSQL+Redis 큐, Docker/cgroup 채점, 코드 교체와 워커 강제 종료/복구를 한 시나리오로 묶은 재생 검증이 남아 있다. 현재 테스트 이미지의 Java 도구 부재로 해당 artifact round-trip도 미검증이다.
- 보관본은 현재 런처의 정확한 바이트 하나일 뿐이다. 다른 버전의 런처·도구체인·이미지가 없는데 해시만으로 재현할 수는 없다.
- 현재 `measured-v1` 접수 기록은 제출 코드의 해시를 독립 필드로 묶지 않는다. 실제 접수 코드 보존과 재생 시 동일성 검사를 별도 설계·검증해야 한다.

운영 DB·큐·설정·대회와 배포·push는 변경하지 않았다. 전체 목표는 진행 중이다.
