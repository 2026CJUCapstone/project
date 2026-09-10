# 공유 PostgreSQL: 소유권과 운영 전환 조건

이 문서는 미배포 코드의 전환 조건이다. 코드 수정이나 격리 검증은 운영 변경 승인이 아니다.

## 관리 경로

`scripts/deploy_server.sh`는 `scripts/ensure_shared_postgres.py`로 색상과 독립적인 PostgreSQL을 준비한다. 기존 이름이 같다는 이유로 컨테이너를 시작하거나 다른 네트워크에 연결하지 않는다. 배포 디렉터리의 소유권 라벨, 전용 내부 bridge, local volume, 설치된 이미지 ID, 환경 변수, 데이터 경로, 호스트 포트 비공개, 자원 상한을 검사한다. 기존 설정이 다르면 중단하며 삭제·재생성·자동 채택·데이터 초기화를 하지 않는다.

이미지는 사전에 설치된 PostgreSQL 16을 사용한다. 실행 시 registry에서 pull하지 않으며 생성은 검사한 이미지 ID에 고정한다. 기본 예산은 메모리 512MiB(추가 swap 없음), CPU 0.5개, PID 256개다. 데이터 volume 외 root filesystem은 읽기 전용이고 필요한 임시 경로만 tmpfs로 제공한다. readiness 및 기존 앱 테이블 확인은 검증된 컨테이너 ID에 대해 TCP 인증 후 수행한다. `pg_isready`나 인증 없는 local socket 성공을 충분한 증거로 보지 않는다.

## 자격증명

운영자가 보호된 `.deploy/runtime-secrets.env`에 **실제 DB에 맞는** `WEBCOMPILER_POSTGRES_PASSWORD`를 공급해야 한다. 이 파일은 `runtime_secrets.py`의 허용 키·리터럴 파서로 읽으며 현재 사용자 소유의 일반 파일·600 수준 권한을 요구한다. 셸 스크립트로 실행하지 않는다. 값은 현재 관리형 Compose URL의 직접 보간에 맞게 영문 대소문자·숫자·`_`·`-`만 포함하는 24–128자여야 하며, edge prepare와 앱 비밀 생성 전에 검사한다. 길이와 형식 검사는 비밀번호의 무작위성이나 안전한 발급을 증명하지 않는다. 비밀값을 문서·로그·명령행 인자·저장소에 쓰지 않는다.

기존 DB가 다른 비밀번호나 형식을 사용한다면 새 값을 임의 생성해 덮지 않는다. 운영자의 자격증명 확인 또는 승인받은 별도 교체 절차가 필요하다. 이 helper는 비밀번호를 변경하지 않는다. Docker 권한 보유자는 컨테이너 환경을 읽을 수 있으므로 Docker 제어권의 신뢰 경계는 그대로 남는다.

운영 전용 shared/ready overlay는 initializer·pooler·API·worker에 명시적인 공통 자격증명을 요구한다. 개발용 base/deploy 조합의 기본값과 구분한다. 관리형 배포는 외부 `WEBCOMPILER_DATABASE_URL`/`WEBCOMPILER_MIGRATION_DATABASE_URL` 덮어쓰기를 거부한다. 별도 외부 DB 연결 지원을 검증했다고 해석하지 않는다.

## 기존 운영 데이터의 전환

- 소유권 라벨이 없는 기존 DB·volume·network를 자동으로 채택하지 않는다. 실패를 피하려고 운영 리소스에 라벨을 임의 추가하거나 삭제하지 않는다.
- 기존 쓰기 주체의 정지·drain, 백업과 별도 환경 복원, 데이터 및 점수 원장 대조, 자격증명, 새 대상 소유권과 rollback 절차를 확인한 뒤 별도 승인을 받아 전환한다.
- 이전 색상이 있는데 공유 DB가 비어 있으면 온라인 snapshot 복사를 하지 않고 중단한다. 앱 테이블 일부가 있다는 검사는 데이터 이관의 완전성 검증이 아니다.
- 컨테이너와 volume 재사용 검증은 DB·호스트 고가용성, 정기 외부 백업, RPO/RTO, 전체 Compose 배포 검증을 대신하지 않는다.

## 검증 범위

`backend/tests/test_shared_postgres.py`는 외부 자원 거부, 설정 변조, 이름 교체, 비밀 인자 노출 방지, 인증 실패와 재사용을 검사한다. `backend/tests/test_shared_postgres_live.py`는 명시적으로 승인된 격리 호스트에서 고유 이름의 DB/volume/network만 생성하고 두 클라이언트 공유·재시작·데이터 보존 및 변경 거부를 검사한다. 테스트가 만든 DB/volume/network는 소유권 확인 후 제거하므로 복구 대상 운영 데이터가 아니다.

소스별 성공·실패·후속 검증 및 남은 운영 조건은 [감사 후속 수정 진행표](audit-remediation-status.md)에 기록한다. 운영 자격증명 확인과 실제 데이터 이전은 아직 수행하지 않았다.
