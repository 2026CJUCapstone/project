# 고정 B++ 수정 후보의 격리 빌드 시도

## 현재 결론

추가로 [A–J 후보 실측](bpp-candidate-reference-measurements-2026-09-27.md) 10문제/31입력 전체 AC를 확인했다. 아래 작은 회귀보다 범위가 넓지만 여전히 별도 후보 검사이며, 설치 이미지·최종 전체 출제 데이터·10회 반복·정상 동시성·DB 워커 수락을 대신하지 않는다. 운영 pin/이미지는 변경하지 않았다.

### 최종 후속: 자기 컴파일 동일성 및 stage2 회귀

**후보의 stage1/stage2 ASM·ELF 바이트 동일성과 최종 stage2의 8개 회귀가 통과했다.** 이 결과는 아래 초기 단계 기록보다 우선한다. 운영에 설치하거나 전체 A–J 성능 수락을 완료한 것은 아니다.

첫 자기 컴파일에서는 ASM이 동일했지만 ELF가 한 바이트 달랐다. 비교 위치 5766191(1-based)에 NASM이 넣은 `/output/stage1.asm`과 `/output/stage2.asm`의 파일명 숫자가 들어 있었다. 두 ELF를 내려받아 해당 바이트와 주위 문자열을 확인했다. [첫 결과](evidence/bpp-candidate-9859a2d-fixedpoint-initial-2026-09-27.json)(SHA-256 `7b918aab4a486fbdc3071a08b748c3b2c238208254efa70640e85cfc0de3b186`)는 실패로 보존했다.

바이너리 차이를 무시하거나 strip하지 않고, 각 단계 ASM 원본을 남긴 채 동일한 `/work/candidate/native.asm` 경로로 정확히 복사해 NASM에 입력하도록 검증 도구를 수정했다. 복사 전후 해시를 확인하며 최종 ELF 전체 바이트 비교 조건은 유지했다. 다시 자기 컴파일 두 단계를 실제 실행한 결과:

| 항목 | stage1 | stage2 |
|---|---|---|
| 컴파일 wall | 19.382초 | 21.701초 |
| ASM SHA-256 | `e9923fbc195e710c2c6fabd5f54f92439d361ecf0f7ffb10ee3120736199ecfd` | 동일 |
| ELF SHA-256 | `7f4864362863ddc9daa687d221387e9f2612220521f89e8a9e05b2e3f40b4a23` | 동일 |

[고정점 원시 결과](evidence/bpp-candidate-9859a2d-fixedpoint-2026-09-27.json): `314606967b2c65618f7bd6fe9c303bcb39095345f0ea0ccdff154192cd1f455a`. cgroup peak 745902080 bytes, OOM/oom_kill 0. stage0와 마찬가지로 소스·표준 라이브러리·bootstrap·생성물 지문을 보존했다.

최종 stage2 ELF를 별도의 512 MiB/1 CPU/240초 상한 컨테이너에 읽기 전용으로 넣고 다음 **8개** 검사를 실행했다.

- 큰 지역 배열+호출 뒤 전체 값 보존: native O0/O1.
- 포인터 인자 GC: native O0/O1, SSA O0/O1. 정확한 `std_mem__bpp_gc_root_slot_remove:` 선언과 실행 출력 모두 확인.
- 변경하지 않은 G/J 기준 풀이의 위 작은 입력: native O1.

모두 exit 0 및 정확한 stdout을 확인했고 각 단계 명령·종료값·wall·출력 크기/해시, 생성 ASM/object/ELF 해시를 기록했다. [stage2 회귀 원시 결과](evidence/bpp-candidate-9859a2d-stage2-regressions-2026-09-27.json): `e13e08c9676d8cefa07994c1e0300d9c7f802d8676e9670209dbe0cfd6875542`. cgroup peak 98054144 bytes/OOM 0. 보고서의 `/input/stage0`는 기존 마운트 슬롯 이름이고, 실제 바이너리는 명시된 `candidateStage: 2`와 `candidateBinarySha256`로 식별한다.

실제 출제 패키지 전체·최대 입력·10회 반복·실제 설치 경로/빌드·DB 워커 통합 수락은 **남아 있다**. 런타임 pin은 아직 변경하지 않았다. 관련 로컬 회귀 **101 PASS /2.06초**이며 모의 검사 통과를 실제 성능 수락으로 세지 않았다. 초기 잘못된 테스트 파일명 호출은 실행된 테스트가 없었고, 실제 파일명으로 바로잡아 위 결과를 얻었다.

보고서 및 바이너리의 로컬/서버 해시를 확인하고 생성물·소스 아카이브를 로컬 `.deploy`에 보존했다. 임시 서버 테스트 복사본 다섯 개는 경로·소유권을 확인한 뒤 정리했다. 운영 데이터·설정·이미지·Git 원격은 변경하지 않았다.

### 후속: stage0 빌드 및 작은 회귀 통과

아래 초기 실패 기록 이후, 단일 import의 실제 분석 비용을 근거로 **빌드 전용** 상한을 CPU 600초/wall 660초, 컨테이너 1 CPU/1 GiB/전체 wall 760초로 분리했다. 문제 풀이 제한은 바꾸지 않았다. 고정된 후보 소스로 stage0 빌드가 완료됐다. 컴파일 CPU 320.843초/wall 322.887초, NASM 7.692초, 링크 0.117초였다. cgroup memory peak 844951552 bytes, OOM/oom_kill 0이다. 따라서 이전 100초 종료를 컴파일러 무한 반복이나 사용자 환경 문제로 해석해서는 안 된다.

- 생성 ASM: 19125014 bytes, SHA-256 `f3d9ef5efaf85c5f9db3c8003e6d3c36fa3501cfafdc2a41cda6021198525672`.
- 생성 stage0 ELF: `2e29c5077bd1a7b299ea1d06e80dcb871429a594c92bc79fac57121be19dff6a`.
- [빌드 원시 기록](evidence/bpp-candidate-9859a2d-stage0-2026-09-27.json): `a1cb7b7f372fb795a8a4d911798532a95ffdabff6f27c2273499a58b16e98e31`.
- 빌드 probe: `f083bf7f00e0186e10e33494734212eb117987b235f8bc1a7e37a6c3d44251de`.

후보 자신의 표준 라이브러리와 정확한 stage0 바이너리를 사용한 별도 격리 실행에서 네 native-O1 검사가 통과했다. 큰 지역 배열+호출 뒤 전체 값 확인, 포인터 인자 GC 재현, 원본 G의 `1 / 1000` 입력→`1000`, 원본 J의 `3 / -5 4 3` 입력→`5`다. 기준 소스나 생성 ASM은 수정하지 않았다. 두 문제는 고정 소스 해시를 검증하고 사용했다. [작은 회귀 원시 기록](evidence/bpp-candidate-9859a2d-stage0-regressions-2026-09-27.json)의 SHA-256은 `9e3afcc9bf7af17509a3528eed6fbade3f98b09bba45e5cf65c4694f099f2e7d`이며 cgroup peak 90382336 bytes/OOM 0이다.

이는 **stage0의 좁은 의미 검증**이지 전체 출제 패키지/성능/런타임 설치 수락이 아니다. 두 차례 자기 컴파일의 stage1/stage2 ASM·ELF 동일성, O0/SSA 경로 및 GC 심볼 검증, A–J 전체 입력과 반복 측정은 별도로 남아 있다. stage1/stage2는 각각 같은 600 CPU초/660 wall초를 사용하며 한 컨테이너 안에서 순차 실행한다(1 GiB, 1 CPU, 전체 1500초 상한). stage0를 재컴파일하지 않고 이미 검증한 정확한 바이너리에서 이어간다. 운영 pin·이미지·DB·큐는 변경하지 않았다.

이 후속 결과가 아래의 과거 미완료 문장보다 우선한다. 당시 원시 실패 보고서는 덮어쓰지 않는다.

추가 단계 분리 검사에서도 후보와 기존 버전 모두 분석 단계의 CPU 상한에 도달했다. `-dump-ast --ast-no-std --ast-func main`은 어셈블리 생성 전 경로다. 후보 9859a2d는 CPU 99.811초/wall 100.718초, 기존 2d59623 소스는 CPU 99.859초/wall 100.531초였다. 두 검사 모두 stdout/stderr 0 bytes, OOM/oom_kill 0이며 실행 파일을 생성하지 않았다. 따라서 후보의 신규 변경이나 어셈블리 생성만을 원인으로 지목할 수 없다. 다음 컴파일러 작업은 기존 bootstrap의 입력 로딩/분석 경로를 더 작은 고정 입력으로 분리하는 것이다. 단순 예산 증가나 기준 풀이 우회는 하지 않는다.

원시 결과는 [후보 분석](evidence/bpp-candidate-9859a2d-frontend-2026-09-27.json)(SHA-256 `6eff92e7ccfbd66b9eb91b4175ccc7bec76938f94589506026285acf998a64bd`)과 [기존 소스 분석](evidence/bpp-baseline-2d596-frontend-2026-09-27.json)(`dd3ff5b9c2fbe62432a989b0905fb6f01c040a2cee17af73d71fb4a09af1dd30`)에 보존했다. 두 스크립트 모두 `0c7f248da03a7a1fb034f30dd66316b032f9eb9f2c46ca326bdf42648a6127f6`이며 기존 소스 아카이브는 Git 2d596233f45973394a5d951c40b11f78171c8870의 627732 bytes, `1dcc9ac5ace81fae5ec846d87064326a038f8adb700adb5f61386b26cc4002f4`이다. 기존과 같은 컨테이너/CPU/메모리 상한으로 순차 검사했다. 로컬/서버 보고서 해시 일치와 컨테이너 종료를 확인하고 두 임시 테스트 복사본을 제거했다. 복구 가능한 원시 기록과 소스 아카이브는 로컬에 남겼다.

수정 후보의 빌드는 **미완료**다. 기준 풀이나 시간 제한을 우회하지 않고 컴파일러 자체를 검증하려고 했지만, 기존 컴파일러가 후보 소스를 처리하는 단계에서 두 번 모두 지정한 CPU 상한에 도달했다. 이 결과만으로 무한 반복, 문법 비호환, 수정의 정확성 중 어느 것도 단정하지 않는다. 메모리 부족이 아니었다는 증거는 두 번째 시도에서 확보했다.

운영 이미지, `runtime/bpp-ref.txt`, Bpp 저장소의 사용자 수정은 변경하지 않았다. Docker 이미지 빌드/다운로드, 설치, 배포, 운영 DB/큐 변경, Git push는 하지 않았다. 앞서 추가한 필수 빌드 검사는 유지하며 불량 런타임을 통과시키지 않는다.

## 후보의 출처와 실행 방법

- 후보 commit: `9859a2dc783c9346be2ab9447e1569218bcc5093`. G의 프레임 크기 수정과 J에 대응하는 `dedc800fdd6586546a467e5446d04d325243706f`를 모두 포함함을 Git ancestry와 코드로 확인했다.
- 사용자의 dirty working tree가 아니라 Git의 해당 commit에서 `src/`와 `config.ini`를 추출했다.
- 아카이브: 651268 bytes, SHA-256 `010e9abd3e2469b6bd1b4ee006ed142e695ecf8ee8af0b81b62fac764d2355bf`.
- 기존 이미지: `sha256:7a3aa3717f2c62f60ff52f680335ebee414151136d6f836382b1b543a43c5db1`.
- 설치된 raw ELF `/usr/local/libexec/bpp/v13_stage1`에 `-asm /work/candidate/src/main.bpp`를 전달했다. compiler `-O1`로 자체 빌드하지 않는 것은 후보 commit의 `build_and_test.sh`와 같다. NASM 단계는 별도로 `-felf64 -O1`을 사용하도록 준비했지만 도달하지 못했다.
- 명시한 테스트 manifest의 `module_root=src`, `std_root=src`로 후보 자신의 표준 라이브러리를 사용한다. 기존 `bpp` 셸 래퍼가 설치된 구 라이브러리를 주입하는 경로는 사용하지 않았다. manifest 의미는 구버전 parser 소스로 확인했다.

후보 빌드 도구는 고정 아카이브 해시·최대 크기·경로/링크 검사를 거쳐 추출한다. 정상 완료 시 stage 1/2의 어셈블리 및 바이너리가 모두 일치해야 하지만, 이 고정점 역시 의미적 정확성이나 A–J 수락을 대신하지 않는다. 실제 회귀와 measured-v1 입력 실행을 별도로 해야 한다.

## 자원 상한과 실제 결과

한 번에 컨테이너 하나, 메모리 512 MiB/동일 swap 상한, CPU 1개, PID 32, 열린 파일 64개, 작업 tmpfs 128 MiB와 임시 tmpfs 16 MiB다. 네트워크·Docker socket·운영 마운트 없음, 읽기 전용 루트, UID/GID 65534로 실행했다. 컨테이너 전체 wall 상한은 240초, 개별 파일 크기는 32 MiB다. 생성 가능한 바이너리는 해당 테스트의 별도 출력 폴더로만 내보낸다.

| 시도 | 개별 컴파일 CPU/wall 상한 | 결과 | 원시 보고서 |
|---|---|---|---|
| 첫 시도 | 40초/60초 | 40.217초 wall, exit -9, 출력 0 bytes | [40초 예산](evidence/bpp-candidate-9859a2d-budget40-2026-09-27.json) |
| 두 번째 | 100초/120초 | 99.879초 CPU, 100.454초 wall, exit -9, 출력 0 bytes | [100초 예산](evidence/bpp-candidate-9859a2d-budget100-2026-09-27.json) |

두 번째 cgroup CPU 사용량은 100133051 µs, memory peak 196149248 bytes(약 187 MiB), OOM/oom_kill 0이다. 외부 240초 timeout에 걸린 것이 아니라 컴파일 프로세스의 CPU 예산에 도달했다. NASM/링크/자체 재컴파일/수정 회귀는 **실행되지 않았다**. 두 시도를 성공한 빌드나 성능 측정으로 세지 않는다.

첫 원시 스크립트 해시는 `3e58a79a51df8363f50fe5a303729cf0bf8db17e8df45ac34686909730f885f9`다. 같은 시기 로컬 Windows 테스트를 위해 `resource` import를 함수 안으로 옮긴 버전과 해시가 다르며, 원시 기록은 당시 실행한 스크립트 해시를 보존한다. 두 번째는 CPU 계측·cgroup 기록과 상한 변경까지 포함한 `19c0ab43b0937be8ea68f499e7c80be6a03dcfefb6eb2731fb500ef55d63572e`다.

## 런타임 식별 보정

기존 측정 도구는 `which bpp` 결과를 해시했는데 이는 셸 래퍼였다. 예전 기록의 `44940bcd…`를 native binary SHA라고 설명한 것을 정정했다. 실제 ELF 해시는 `8cd02a03dd9f817bc50a644160dd06b70f4dfe8982abac9f61d6faebcfa9e960`다.

발견 도구는 이제 ELF header·크기·고정 설치 경로를 확인하고 네이티브 컴파일러 해시와 래퍼 해시를 별도로 기록한다. 이전 원시 JSON을 덮어쓰지 않았다. 이전 실행은 여전히 고정 이미지 digest에 묶여 있지만, 종전 wrapper 값을 native hash로 재사용해서는 안 된다.

## 로컬 검증과 다음 단계

### 고정된 작은 입력 대조

동일한 구버전 소스 아카이브·manifest·raw ELF를 사용해 빈 `main`과 `compiler.annotations`만 import한 `main`을 순차 분석했다. 빈 입력은 CPU 1.842초/wall 1.873초, 모듈 import 입력은 CPU 61.716초/wall 62.154초에 모두 exit 0으로 끝났다. 출력 AST는 각각 273 bytes이며 같은 지문이다. 필터는 출력을 줄일 뿐 import 파싱과 전체 분석 단계를 생략하지 않으므로, 단일 import가 처리 비용을 크게 늘리는 것이 확인됐다. 실제 전체 컴파일러 분석이 무한 반복이라는 근거는 없으며 100초가 충분한 빌드 예산이라고도 아직 입증되지 않았다.

고정 입력 두 개는 `frontend_reductions()`에 정의된 진단 코드이며, 원본 컴파일러/기준 풀이를 수정하지 않았다. 기존 자원 상한을 그대로 유지했다. cgroup peak 361336832 bytes, OOM/oom_kill 0, CPU 사용 63800252 µs다. 실행 파일은 생성하지 않았고 이 결과를 후보 빌드나 G/J 수정 성공으로 세지 않는다.

[원시 작은 입력 대조](evidence/bpp-baseline-2d596-frontend-reduction-2026-09-27.json)의 로컬/서버 SHA-256은 `878f5a44af158b4e7a9ea3483455ed4edf4eff1e88ae9be821688c3c2349ba0f`, 검사 스크립트는 `d65c05fb364ad36537fb33129cb270de89770682520d13f5f48784256a64e1c4`다. 정확한 임시 폴더 `Fga2q0mm`를 정리했고 테스트 컨테이너 0개/기존 basic 7개 healthy를 확인했다. 원시 결과는 보존되어 있다. 다음 단계는 import별 비용/전체 빌드에 필요한 예산의 근거를 확인하거나 출처가 검증된 더 효율적인 bootstrap을 확보하는 것이다.

추출/경로 거부, 단계별 실패 기록, 전송, 실제 컴파일러 식별, 빌드 회귀 및 기존 측정 도구 집중 검사 **121 PASS /7.70초**. 합성/모의 검사는 실제 후보 빌드 통과가 아니다.

초기 식별 테스트에서 32 MiB 바이트 배열을 직접 pytest parameter로 사용해 과도하게 긴 테스트 이름과 fixture 오류 3개가 발생했다(65 PASS). 작은 문자열 case ID로 바꾸어 다시 실행했고 67개 집중 검사가 통과했다. 데이터 크기는 테스트 함수 안에서만 생성하도록 수정했다.

다음에는 구버전의 `-dump-ast --ast-no-std --ast-func main` 경로와 고정된 구 소스 자체 빌드 대조를 이용해 지연 구간을 분리한다. 단순히 CPU 상한만 계속 올리지 않는다. 필요하면 출처가 고정된 중간 bootstrap 경로를 검증한다. NASM split은 컴파일 결과가 생성된 뒤의 문제이므로 이번 0-byte 출력 문제의 해결책으로 간주하지 않는다.

수정 후보의 고정점·G/J 회귀·A–J 실제 실행이 확인되기 전에는 pin 변경이나 런타임 승인을 하지 않는다. 전체 Goal의 다른 구현·통합·반복 측정 및 외부 승인 조건은 그대로 남아 있다.

두 원시 보고서의 로컬/서버 해시 일치를 확인했다(40초 보고서 `5219961b43417b776ac9ac5d39ed4a76cbdbbab462ac3d43017fb97925c00d6e`, 100초 보고서 `6af611c505310ef102c047c30b2ce8a03aad90c299f6865d2ba09c2a37b31dd8`). 테스트 컨테이너 0개와 출력 바이너리 부재를 확인하고 정확한 임시 경로 `plX9QOZo`/`PyEbQJdq`의 테스트 복사본을 정리했다. 자료와 원시 기록은 로컬에 보존되어 재생성할 수 있다. 기존 basic 서비스 7개 healthy를 다시 확인했다.
