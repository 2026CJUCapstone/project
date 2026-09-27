# 격리된 실제 Python 채점 경로 — 2026-09-27

운영 DB·큐·대회·배포 설정을 쓰지 않고, 기존 서버의 이미지 `sha256:d7ab3494aad02142fe7fc4abee8175283a2ce68e57cfc7bb24da034753065930`로 `run_isolated_measured_pipeline.py` → `verify_measured_pipeline.py`를 실행했다. 소스 아카이브는 현 작업트리 `backend/app`의 Python 파일 102개(아카이브 109개 항목, 압축 173247바이트)다. 아카이브 SHA-256 `683a13c6c50b0c70833032fa61dfc6c9b9f19354b93e256eadbd848ce2275c3e`; 컨트롤러 `2c07fee4752ba66fb451d40ba0dedc80b86d3a607f93ee40ec9cdcb0a7d249ec`; 앱 검증기 `d52913387229be0f30fcc526166450759e9accc9bfdf5e700570369c2c107c12`; 런처 검증기 `dfbbcc884394bf07f6b3306762f99455031db9b28865929e330dcfcc8e718a05`. 이 네 파일의 서버/로컬 해시가 일치했다.

기존 컨트롤러의 상한은 256 MiB, 0.5 CPU, 네트워크 없음, 읽기 전용 루트이며, 소켓은 이 신뢰된 컨트롤러에만 있다. 제출 단계는 128 MiB, 1 CPU, PID 16, 네트워크 없음, 읽기 전용 루트, swap 없음이다. 실제 `DockerCompilerRunner`/`MeasuredSubmission`/`judge_code`를 통과했지만 SQLite URL은 방어용 `:memory:`이고 DB 초기화·API·큐·워커 프로세스는 실행하지 않았다.

컨트롤러가 출력한 결과:

```json
{
  "scope": "actual Python adapter, not full worker/policy acceptance",
  "image": "sha256:d7ab3494aad02142fe7fc4abee8175283a2ce68e57cfc7bb24da034753065930",
  "runtime": "Python 3.12.3",
  "launcherDigest": "sha256:908bb710244512ea3f655831a7aa84b4fb5d6ec370cd32e558f14944fbc0e505",
  "phases": [
    {"version": 1, "phase": "compile", "exitCode": 0, "failureReason": null, "cpuUsec": 34704, "wallNs": 31705168, "peakMemoryBytes": 12328960, "oomKills": 0, "outputBytes": 0, "treeReaped": true},
    {"version": 1, "phase": "run", "exitCode": 0, "failureReason": null, "cpuUsec": 18821, "wallNs": 16266581, "peakMemoryBytes": 10207232, "oomKills": 0, "outputBytes": 3, "treeReaped": true},
    {"version": 1, "phase": "run", "exitCode": 0, "failureReason": null, "cpuUsec": 15306, "wallNs": 12916069, "peakMemoryBytes": 9928704, "oomKills": 0, "outputBytes": 4, "treeReaped": true}
  ],
  "verdict": "accepted",
  "compileCount": 1,
  "caseContainerCount": 2,
  "freshWorkspaces": true,
  "readOnlyArtifact": true,
  "storedData": false,
  "caseInputBytes": 3,
  "manifestBytes": 45,
  "phaseInputsReaped": true,
  "remainingContainers": 0,
  "remainingJobDirectories": 0
}
```

테스트 직전 RAM 가용 6419230720바이트·디스크 가용 5050695680바이트, 직후 각각 6488367104·5049622528바이트였다. 서버 임시 경로 `/tmp/webcompiler-launcher-test.JwIhMf`의 실경로·소유 UID 1002·링크 부재·소유 라벨 컨테이너 0개를 확인하고 해당 경로만 삭제했으며 부재를 확인했다. 이미지 빌드·pull·설치, 운영 데이터·설정·대회·배포·push는 없었다.

이 검사는 현재 Python 경로의 실제 Docker 실행이다. 역사적 이미지 선택, 코드 교체 후 접수 기록의 실제 큐 재생, PostgreSQL/Redis 워커 복구, 6개 언어·A–J 전체·시간/메모리 제한 승인은 증명하지 않는다.

격리의 한계: 테스트 컨트롤러는 서버의 **공유 Docker 데몬 소켓**을 받는다. 제출 컨테이너에는 소켓이 없고 이 실행에서 운영 컨테이너·데이터 접근은 하지 않았지만, `--network=none`만으로 소켓 사용 권한이 제한되는 것은 아니다. 전용 테스트 데몬 또는 엄격한 소켓 정책이 없으므로 이 결과를 운영과 권한까지 완전히 분리된 검증으로 해석하지 않는다.

## 출력 수집 분리 후 재실행

`measured-collection-v1`로 출력 수집을 분리한 소스 아카이브 SHA-256 `5e8f4845ca984a64951d0962ae4eaa84c4e162a5747b9c06c802194731b6b69f`(111항목, 173563바이트)를 같은 기존 이미지로 다시 실행했다. 컨트롤러와 검증기 세 파일은 위 해시와 동일하게 서버/로컬 대조했다. 이 재실행 역시 `accepted`, 컴파일 1회, 독립 케이스 컨테이너 2개, 산출물 읽기 전용, 이전 케이스 파일 없음, 남은 컨테이너·작업 디렉터리 0개였다. 세 단계의 `treeReaped=true`, `exitCode=0`, `failureReason=null`을 확인했다.

| 단계 | CPU µs | wall ns | peak bytes | 출력 bytes |
|---|---:|---:|---:|---:|
| compile | 39282 | 35302158 | 12292096 | 0 |
| run 1 | 17717 | 15339907 | 10006528 | 3 |
| run 2 | 15196 | 13217803 | 10149888 | 4 |

실행 전 RAM 가용 6215114752바이트·디스크 가용 5049909248바이트, 실행 후 각각 6165323776·5048827904바이트였다. 두 번째 임시 경로 `/tmp/webcompiler-launcher-test.dRUISK`도 실경로·UID 1002·링크 부재·소유 라벨 컨테이너 0개를 확인하고 약 2 MiB의 재생성 가능한 테스트 파일만 삭제한 뒤 부재를 확인했다. 이번에도 실제 과거 접수의 큐 재시작 재생이나 다른 언어·문제의 성능 수락을 주장하지 않는다.
