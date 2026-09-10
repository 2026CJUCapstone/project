# Basic 2-API 자동 배포

`deploy_server.sh`는 배포 lock/정확한 SHA/깨끗한 tracked checkout을 먼저 확인한다. 서버 `.deploy/basic-pool.json`이 있으면 `basic_pool_deploy.py`로만 진입하며 관리형 blue/green 배포로 넘어가지 않는다. config가 없을 때만 기존 관리형 경로를 사용한다.

현재 운영 선택 파일(version1)은 다음 비밀 없는 구조다. 운영 데이터와 비밀이 들어 있는 `operator-state.json`은 기존 pool 안에 유지한다.

```json
{
  "version": 1,
  "pool_root": "/home/vulpo/webcompiler-basic-lb-EIXszgyU",
  "project": "webcompiler-basic-eixszgyu",
  "postgres": "webcompiler-postgres",
  "backend_port": 18003,
  "frontend_port": 15176
}
```

## 자동 실행 순서

1. main의 정확한 commit이 CI에 통과했는지 확인한다. fork PR/다른 branch/실패 CI는 SSH 전에 거절한다. SSH는 사전에 신뢰한 해당 host:port 키를 고정한다.
2. 같은 commit을 checkout한 GitHub runner에서 Node24/npm ci로 `/webcompiler/` 프런트를 빌드한다. package helper가 정확한 SHA marker를 넣는다.
3. 단일 SSH stdin으로 gzip bundle을 전달한다. 기존 remote deploy lock을 잡은 다음 임시0600 파일에 수신하고 digest를 확인한다. 같은 lock을 fetch→checkout→image build→전환까지 유지한다.
4. 원격 Git archive만 source로 사용한다. 이전 release와 schema/bootstrap/dependency lock/Dockerfile/nginx/Compose/runtime 계약을 비교한다. 변경된 계약이나 삭제된 backend module은 자동 overlay를 거절한다. 승인된 migration/clean image 준비 후 별도 절차가 필요하다.
5. 정확한 기존 dependency image 위에 앱·sandbox launcher·새 프런트만 COPY한다. Docker context는 역할별 허용 파일만 복사한 별도 디렉터리이며 비밀을 포함한 journal/DB dump는 전송하지 않는다. CPU1/2GiB/no network/no pull 빌드이며 8GiB 가용공간이 필요하다. 이것은 clean dependency build나 새 이미지 SBOM attestation이 아니다.
6. edge 일시503 → 신규 접수 차단 → 접수 작업 drain → DB dump/목록 검증 → API2개·worker·frontend만 교체한다. PostgreSQL/Redis/PgBouncer/proxy 컨테이너를 재생성하지 않는다.
7. health/release SHA/관리자 인증6언어 실제 실행/보호 데이터 fingerprint/기존 stateful IDs를 검사한 후 공개한다. 실패 시 이전 이미지와 새 runtime incarnation으로 rollback하며 DB dump를 덮어쓰지 않는다.

## 복구와 한계

`.deploy/basic-pool-pending.json`은 private release journal 경로를 가리킨다. journal은0600이며 자격증명을 포함하므로 출력·Git 업로드하지 않는다. `deployed`/`rolled-back`이 아닌 중단 상태에서는 다음 자동 배포를 막는다. 관리자가 해당 journal·실제 컨테이너·lock/edge 상태를 확인하고 복구해야 한다. 무조건 marker 삭제나 DB restore로 해결하지 않는다. 이전 이미지·dump를 자동 prune하지 않는다.

현재 topology에서 동일한 코드/설정 계약의 업데이트를 자동화한다. DB migration·dependency/컴파일러 toolchain 갱신·topology 변경·다중 호스트 HA를 자동화했다고 주장하지 않는다. SMTP 미설정은 이번 배포 범위에서 제외되며 그대로 남는다. 동시 사용자 데이터 변경 때문에 fingerprint 검사가 실패하면 데이터 삭제 없이 rollback하고 원인을 확인한다.
