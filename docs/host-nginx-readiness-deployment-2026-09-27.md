# 운영 Nginx readiness 경로 갱신 절차

작성일: 2026-09-27
상태: **실행 전 초안 — 운영 변경·배포·대회 등록·Git 반영은 수행하지 않음**

## 현재 확인된 기준

| 항목 | 기준 |
| --- | --- |
| 현재 운영 배포 ref | `ebd7e367f396dfab20a3a1f1f6ce96a4fdd4c79e` |
| 운영 include | `/etc/nginx/snippets/webcompiler.locations.conf` |
| include 소유권·상태 | 마지막 확인 때 `root` 소유, Nginx active |
| include SHA-256 | 마지막 확인값 `9a83b7a5621a2cc521986401df0f9f5056e23ed27a090e68f73188d0c857ddc8`. 적용 직전 전체 값을 다시 읽어야 함 |
| 로컬 후보 | `deploy/nginx/webcompiler.locations.conf` — 현재 로컬 변경이며 운영에는 아직 반영되지 않음 |
| 로컬 후보 include SHA-256 | 현재 검증 후보 `5ba380ae9e082584cf9faff24dd8fbd400f60f063871fd968edf484d5d20c317`. 배포 archive 생성 뒤 다시 계산해 동일해야 함 |
| 권한 | passwordless sudo는 사용할 수 없음. 사용자 승인 뒤 대화형 root 인증이 필요함 |

직전 운영 확인에서는 `/webcompiler/ready`가 JSON이 아니라 SPA HTML fallback을 반환했다. 내부 API proxy의 `:18000/ready`는 `{ "status": "ready" }` 형태의 JSON을 반환했다. 상태는 바뀔 수 있으므로 이 문서의 실행 전에 모두 재확인한다. 로컬 후보 파일의 존재나 테스트 통과는 운영 반영의 증거가 아니다.

## 적용 전 확인

이 절차는 사용자가 정확한 후보와 운영 변경을 승인한 뒤에만 실행한다. 대화형 SSH 터미널을 열어 sudo 암호를 직접 입력한다. 암호를 명령 인자·파일·로그에 넣지 않는다.

다음 항목을 변경 전에 읽기 전용으로 확인하고 결과를 작업 기록에 남긴다.

1. 배포 ref가 여전히 위의 `ebd7…`인지 확인한다.
2. `stat -c '%U:%G %a %n' /etc/nginx/snippets/webcompiler.locations.conf`로 root 소유권과 모드를 확인한다.
3. `sha256sum /etc/nginx/snippets/webcompiler.locations.conf`의 전체 해시를 기록한다. 전체 해시가 기준 시점의 보관 기록과 다르면 적용을 중단하고 차이를 검토한다. 접두사 `9a83b7a`만으로 동일성을 판단하지 않는다.
4. `systemctl is-active nginx`가 `active`인지 확인한다.
5. `curl -sS --max-time 10 -w '\nHTTP %{http_code}\n' https://cuha.cju.ac.kr/webcompiler/ready`로 현재 외부 응답을 확인한다. 리디렉션은 따라가지 않는다. 기준 동작과 다른 응답, TLS 오류, timeout은 원인을 확인할 때까지 중단 조건이다.
6. 로컬 후보의 변경 내용을 검토하고 전체 SHA-256을 기록한다. 승인한 내용과 호스트로 전달할 후보 바이트가 정확히 일치해야 한다. 후보의 다른 Nginx 경로·제한을 함께 바꾸지 않는다.
7. 이 배포 ref에서 내부 `127.0.0.1:18000/ready`가 JSON 준비 상태를 반환하는지 확인한다. 이 경로가 준비되지 않으면 외부 location을 바꾸지 않는다.

사전 확인 결과, 후보 해시, 승인자, 작업자, 백업 경로를 기록한다. 확인 중 어느 파일이든 예상과 다르면 중단하고 현재 파일을 덮어쓰지 않는다.

## 적용 순서

각 단계는 순서대로 수행한다. 앞 단계가 실패하면 다음 단계로 진행하지 않는다.

1. **읽기 전용 검사:** 배포할 Linux source archive의 저장소 루트에서 아래 명령을 일반 사용자로 실행한다. 출력된 source/target 전체 SHA-256을 승인 기록과 비교한다. `matches=false`는 현재 예상 상태지만, target 해시가 위의 전체 기준값과 다르면 중단한다.

   ```sh
   python3 scripts/install_host_nginx_include.py check
   ```

2. **명시적 root 적용:** 위 출력에서 승인한 두 전체 해시를 그대로 넣어 대화형 sudo로 실행한다. 비밀번호를 인자나 파이프에 넣지 않는다.

   ```sh
   sudo python3 scripts/install_host_nginx_include.py apply \
     --expect-source-sha256 승인된_source_전체_SHA256 \
     --expect-current-sha256 승인된_target_전체_SHA256
   ```

   이 도구는 root 소유·비쓰기 상위 경로와 고정된 두 해시를 다시 확인하고, root 전용 프로세스 잠금을 획득한 뒤 target을 다시 읽는다. 기존 bytes를 content-addressed 0600 rollback 파일로 보존하며, 임시 파일에 root:root/0644를 설정하고 fsync한 뒤 원자 교체한다. 이어서 `/usr/sbin/nginx -t`, reload, 공개 HTTPS JSON/no-store/`200 ready`를 검사한다. source·target drift, symlink, 경쟁 작업, 문법·reload·외부 확인 실패는 성공으로 처리하지 않는다.
3. **도구 결과 보존:** JSON 출력의 `sourceSha256`, `previousTargetSha256`, `rollbackBackup`, `verifiedUrl`을 작업 기록에 남긴다. `changed=false`인 재실행도 Nginx 문법과 공개 readiness를 다시 검사한다.
4. **수동 명령 금지:** 이 절차에서는 `cp`, `install`, 편집기, 임의 `nginx -s reload`로 도구의 해시·잠금·원자 교체·rollback 검사를 우회하지 않는다.
5. **외부 HTTPS 확인:** `https://cuha.cju.ac.kr/webcompiler/ready`를 리디렉션 없이 연속 확인한다. HTTP `200`과 유효한 JSON `{ "status": "ready" }`가 함께 확인될 때만 성공으로 기록한다. HTTP `503` JSON은 서비스가 준비되지 않은 상태이므로 성공으로 처리하지 않는다. HTML, 다른 JSON 상태, redirect, timeout, TLS 오류, 기타 HTTP 코드는 실패다. 응답 본문에 토큰이나 비밀값이 없어야 한다.
6. **기존 서비스 확인:** `/webcompiler/health`의 HTTPS 응답과 배포 ref를 다시 확인하고 Nginx 오류 로그에 새 설정 관련 오류가 없는지 확인한다. 확인 결과와 후보/운영 파일 해시를 작업 기록에 남긴다.

## 실패 시 복구

문법 검사 실패, reload 실패, readiness가 `503`이거나 응답이 JSON `200/ready` 계약과 다르면 도구가 원본 bytes·소유권·모드를 복원하고 원래 설정을 검사·reload한 뒤 적용 실패로 종료한다. 복구 후 공개 응답 fingerprint가 적용 전과 다르면 `rollback verified`로 표시하지 않는다.

- 자동 rollback까지 성공했다면 JSON 오류의 `rollback verified`와 rollback 파일 경로·해시를 기록한다. 기존 운영 include는 현재 mode 0755이므로 실패 복구는 그 기존 mode까지 되돌리고, 성공한 새 설정만 root:root/0644로 정규화한다.
- `restore failed`, `rollback command failed`, `rollback public verification failed` 또는 `rollback public response differs`가 있으면 수동 명령을 즉흥적으로 이어 실행하지 않는다. 원본 rollback 파일을 보존하고 운영 담당자에게 현재 target/backup 해시와 오류를 넘긴다.

  ```sh
  sudo sha256sum /etc/nginx/snippets/webcompiler.locations.conf \
    /etc/nginx/snippets/webcompiler.locations.conf.rollback-*
  sudo stat -c '%U:%G %a %n' /etc/nginx/snippets/webcompiler.locations.conf \
    /etc/nginx/snippets/webcompiler.locations.conf.rollback-*
  ```

- 복원한 파일의 해시·소유권·모드를 기록하고 `/webcompiler/health`, `/webcompiler/ready`, 현재 배포 ref를 재확인한다. readiness가 기존 fallback 동작으로 돌아온 경우 이를 숨기지 말고 복구 결과와 함께 기록한다.
- 백업 무결성 확인, `nginx -t`, 복원 reload 가운데 하나라도 실패하면 다른 설정 변경이나 restart를 추가로 시도하지 않는다. 현재 증거와 함께 운영 담당자에게 넘긴다.

백업은 원인 분석과 복구 확인이 끝날 때까지 보존한다. 자동 삭제하지 않는다.

## 완료 기록 형식

- 승인된 후보 경로와 전체 SHA-256
- 변경 전·후 운영 파일의 전체 SHA-256, 소유권과 모드
- 변경 전·후 배포 ref
- `nginx -t`, reload 결과와 UTC 시각
- `/webcompiler/ready`의 HTTP 상태와 JSON 판정, `/webcompiler/health` 결과
- 실패 또는 복구가 있었다면 백업 경로, 복원 해시와 최종 상태

이 문서는 runbook 초안이다. 작성만으로 운영 권한, 배포 승인, 대회 등록 승인이 생기지 않는다.
