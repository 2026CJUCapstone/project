# 그래프 릴리스 최종 이미지 검증 — 2026-09-28

## 후속 보안 정비 (진행 중)

사용자의 해결·배포 지시에 따라 Ubuntu 빌더와 실제 제출 실행 환경을 분리했다. 최종 실행 환경은 digest로 고정한 공식 Node 24.21.0 / Alpine 3.24 기반이다. B++는 ELF interpreter가 없는 정적 실행 파일인지 확인하고 옮기며, Node·C/C++·Python·Java는 Alpine 자체 실행 환경을 사용한다. 기존 npm 11.19.1 검증 사본과 B++ 필수 실행 검사는 유지한다. 헤더 삭제, 패키지 목록 은폐, 취약점 예외는 적용하지 않았다.

격리된 시험 이미지 `sha256:0306fc322b17c37fcc2143ce715811b3bdb1f4a5ef5ff9b4f015fb716952bf33`에서 다음을 확인했다. 이 이미지는 정식 소스 빌드/배포 이미지가 아니므로 배포 승인 근거를 대체하지 않는다.

- 여섯 언어 실행과 B++ 배열·포인터 6개 조합 통과.
- 정상 실행, 결과 위조 방지, 분리된 자식 프로세스 정리, CPU/벽시계 시간 초과, 출력 초과, OOM, PID 제한의 실제 launcher 8개 검사 통과.
- 동일 Trivy와 갱신 DB로 232개 package identity 검사: 탐지 행 0개, 기존 엄격 정책 통과. 이는 이미지 검사 결과이며 호스트 커널 전체 안전성을 뜻하지 않는다.
- 증거: `/home/vulpo/webcompiler/.deploy/graph-alpine-probe-rfdm_tpy`; 보고서 SHA-256 `44cce52dc90f80f65024df7623b55201355855a029a2853103a867c81b9a7184`, SBOM SHA-256 `e9a1cd5bd66dfa0fd6367a1fbd6758735463d4ba3ce1a6e623b3b111943fe5ae`.
- 기존 launcher 검사 도구가 구버전 protocol 1을 보내 처음에 거부됐다. 실제 protocol 2로 정정하고 parser와 probe의 일치 회귀 및 PID 제한 검사를 추가했다. 실제 실행기 제한을 완화하지 않았다.
- Node 격리 검사도 실제 최종 Alpine stage를 사용하도록 변경했다. B++ 빌드만 정확하게 제외하며 경계가 달라지면 실패한다.
- 로컬 관련 회귀 55개 및 subtest 17개 통과. 최종 소스 이미지 재빌드·보안 검사·실제 매핑 검사·main CI·배포 확인은 아직 남아 있다.
- 운영 컨테이너의 `SANDBOX_IMAGE`와 별도 채점 등록부 존재 여부만 읽어 확인했다. 이 풀에는 `JUDGE_RUNTIME_REGISTRY` 설정/마운트가 없다. 고정 대회 정책이나 별도 채점 등록부를 임의로 변경하지 않는다.

## 결론

PR #30과 #31은 main에 병합됐고 필수 CI는 통과했다. 최종 실행 이미지의 기능 검증도 통과했으나 보안 정책을 통과하지 못해 운영 교체는 수행하지 않았다. 운영은 기존 `d7b9f1d8978d2f7cde155910ccad034492b014ef`를 유지한다. 보안 예외나 runtime approval을 발급하지 않았다.

## 검증 대상

- 빌드 소스: `bbab622ad0d5d66dc0a66d499fd4081dc3e2d983`
- main 병합: `460e36fb2572134aa09dbd97406672e19c594816` (빌드 소스와 전체 tree diff 없음)
- B++: `9859a2dc783c9346be2ab9447e1569218bcc5093`와 저장소의 출력 확장 패치
- 이미지: `sha256:527023f31ab9a87cf76fdad6f929c16d3e4790afb36c8fb0409623532cd5f597`
- 서버 증거: `/home/vulpo/webcompiler/.deploy/graph-runtime-build-wab886_q`
- main CI: `36429456905` 성공. 선택적 browser-e2e/e2e-stack은 건너뛰었으며 실행 증거로 계산하지 않는다.
- 자동 배포 `36430420689`는 서비스 교체 전에 중단됐다.

## 통과한 검사

- 관련 로컬 회귀 66개.
- 자원 제한 빌더에서 전체 이미지 빌드, 필수 native-O1 회귀와 exploration JSON O0/O1 검사. fast self-host 프로필로 stage2/fixed-point 검사를 새로 수행한 것은 아니다.
- 설치 이미지의 6개 언어(B++, C, C++, Python, Java, JavaScript) 출력 `42` 확인.
- 배열·포인터 O0/O1 및 해당 SSA 조합 6개 실행 회귀.
- 동일 이미지에서 CPU 1개, 메모리 256MiB, 추가 swap 없음, 출력 모드별 30초 제한의 실제 Unicode 소스 매핑 검사:

| 입력 | AST 범위 | SSA 범위 | IR 범위 | ASM 범위 |
|---|---:|---:|---:|---:|
| LF / O0 | 5 | 4 | 4 | 18 |
| CRLF / O1 | 5 | 3 | 3 | 18 |

범위가 존재하는지만이 아니라 UTF-8 오프셋으로 잘라낸 코드가 원래 문장에 대응하는지 검사했다. 작은 회귀 입력의 통과이며 임의 크기의 모든 프로그램이 30초 안에 처리된다는 보장은 아니다.

## 보안 검사 실패

Trivy 0.74.0, 실행 파일 SHA-256 `d89bcc6510a267f11b773398cbf1be5520ce39f9e8b6633178c4487f05b7d791`, DB 갱신 시각 `2026-09-28T13:05:44.359328237Z`로 위 불변 이미지 자체를 검사했다. 별도 768MiB/0.5CPU/추가 swap 없음/128Tasks 단위에서 검사했다.

- 설치 package identity 369개. Critical 1 / High 89 / Medium 2792 / Low 154 보고. 수치는 패키지·권고 조합의 행 수이며 독립적으로 악용 가능한 문제 수가 아니다.
- `linux-libc-dev 7.0.0-34.34`: Critical 1, High 81. 스캐너가 수정 버전을 제시하지 않았다.
- `usr/bin/pebble`의 Go stdlib v1.26.5: High 8. 스캐너가 수정 Go 버전을 제시했다. 실제 Pebble 패키지 업데이트·제거의 영향은 아직 검증하지 않았다.
- Node 패키지 탐지에서 배포 차단 등급 항목은 없었다.
- `policyPassed: false`, 정책은 기존 `reject-unknown-high-critical-and-eol-no-waivers` 유지.

Critical 항목 `CVE-2026-64564`는 [Ubuntu 공식 설명](https://ubuntu.com/security/CVE-2026-64564)상 Linux 커널 SCTP 문제이고 Ubuntu 26.04 linux는 확인 시점에 수정 진행 중으로 표시됐다. 헤더 패키지 탐지만으로 컨테이너에서 해당 커널 취약점이 실행 가능하다고 결론 내리지 않는다. 실제 호스트 커널 영향·완화 및 각 탐지 항목의 적용 가능성은 별도 검토해야 한다. 헤더를 숨기거나 탐지를 예외 처리해 통과시키지 않았다.

증거 파일:

- `sandbox-scan/manifest.json`: 정책 실패를 명시한 완료 보고서.
- `sandbox-scan/report.json`: SHA-256 `a55b6c641d1a4336e83e1ae0fc078fc4e6026f3f57ac4fbccfae47d049d91ba6`
- `sandbox-scan/sbom.cdx.json`: SHA-256 `7482ec1626a6b5eb4eb87901feb5a6ff647d4fe7da58b012c5b269f9e02e8d7f`
- `installed-smoke.json`, `graph-build.log`, `graph-build-receipt.json` 보존.

## 남은 조건

실행 환경의 기반 패키지 보안 정비 또는 근거 있는 적용 가능성 검토가 필요하다. 호스트 설정 변경·보안 예외는 승인 없이 수행하지 않는다. 이후 새 정확한 이미지의 전체 기능·보안 검사, 해당 main CI, runtime approval, 배포 및 운영 API/브라우저 확인이 필요하다. 운영 브라우저의 실제 드래그·변수 흐름·모바일 검증은 준비만 했으며 이번 이미지로 수행했다고 주장하지 않는다.

출력 패치의 내부 dump 종료 시 버퍼링을 끄는 동작은 상위 unified 출력의 ASM 꼬리 부분을 비버퍼 출력으로 만든다. 소스 검토상 출력 순서/JSON 유효성의 오류나 기존 비버퍼 구현 대비 회귀는 아니며, 추가 성능 최적화 여지로 남긴다.

승인된 임시 정리로 탈락한 이전 후보 이미지, 이번 작업의 검사 캐시와 전용 빌더 캐시만 제거했다. 운영·복구용 이미지, DB, 업로드, 검사 보고서는 보존했다. 캐시는 다시 만들 수 있지만 삭제 자체는 되돌릴 수 없다.
