# 신입생 대회 오프라인 출제 자료

이 디렉터리는 개발 중인 출제 자료다. 실행해도 운영 대회나 문제를 등록하지 않는다. 난이도·원문 이용 조건·공개 일정·언어별 제한은 아직 확정되지 않았다.

## 구성

- `a_i.py`: A–I 입력 검증, Python 기준 풀이, 재현 가능한 소규모 입력 생성, 미검수 출처 상태.
- `banks.py`: J 입력 검증과 O(n log n) 기준 풀이·생성기. 증명은 `docs/banks-reference-proof-2026-09-26.md`에 있다.
- `wrong_solutions.py`: A–I 기능 오답 18종과 검출 입력. 무한 반복·메모리 폭탄 실행 도구가 아니다.
- `banks_wrong.py`: J 기능 오답 6종과 결정적인 반례. 중복 이웃, 음수 나눗셈, 순서 보정 누락, 같은 누적합, 주기 누락, 32비트 오버플로를 검사한다. 작은 반례는 제한된 BFS로 별도 비교하며 실제 TLE/MLE 측정이 아니다.
- `solutions/c/{A..J}.c`: C17 기준 풀이.
- `solutions/cpp/{A..J}.cpp`: C++17 기준 풀이.
- `solutions/java/{A..J}/Main.java`: Java17 호환 기준 풀이.
- `solutions/javascript/{A..J}.js`: Node.js 기준 풀이. J의 큰 정수 합계는 BigInt를 사용한다.
- `solutions/python/{A..J}.py`: Python 3 독립 제출형 기준 풀이. J는 Python의 임의 정밀도 정수를 사용한다.
- `solutions/bpp/{A..J}.bpp`: B++ 독립 제출형 기준 풀이. 입력은 4096-byte 버퍼로 읽고, F는 heapsort/이진 탐색, H/I는 반복 BFS, J는 signed 64-bit 주기적 역전쌍 계산을 사용한다.
- `stress_cases.py`: A–I의 결정적 최대·적대 입력 23개를 `iter_cases(letter)`로 지연 생성하는 불변 descriptor 묶음이다. 디스크·DB·네트워크·런타임 쓰기를 하지 않으며, 한 번에 한 case만 만든다.
- `banks_stress_cases.py`: J의 결정적 경계·최대 입력 8개를 지연 생성한다. n=1/2, 중복 누적합, 음수 floor 나머지, ±31999, 최대 n=9999, 총합 1, 32-bit를 넘는 답을 포함한다. 기대값은 기존 O(n log n) 풀이 호출이 아닌 닫힌 식으로 만들며 작은 BFS/이차식으로 별도 대조한다.

A–I 23개와 J 8개, 합계 31개 descriptor는 있지만 검수된 최종 대회 데이터 전체를 뜻하지 않는다. `scripts/verify_freshman_measurements.py`는 한 언어의 A–J 고정 소스와 이 입력 묶음을 실제 measured-v1 실행기에 연결하고 소스·입력·기대값 해시와 compile/case 계측을 기록한다. `scripts/run_isolated_runtime_matrix.py --suite freshman`은 이미 존재하는 이미지와 검증된 임시 경로에서만 실행하며 명시적 `--execute`가 필요하다. 한 실행은 언어 하나의 반복 번호 하나이며 최종 제한 승인이나 운영 대회 등록을 하지 않는다.

`coverage_cases.py`는 별도 보충 입력이다. B의 세 기존 사례와 보충 213개를 합치면 가능한 순서 있는 세 값 216개를 로컬에서 모두 검사한다. 다만 채점기는 한 문제에 최대 200개 사례만 허용하므로 이 216개를 그대로 대회 숨김 테스트나 반복 측정 입력으로 취급하지 않는다. 나머지 A/C–I는 지문에 적힌 경계 범주를 보강한다.

`corpus-manifest-draft-v1.json`은 첫 격리 측정에 사용한 공개 예제 26개+숨김 후보 52개, 총 78개 입력의 **역사적 미승인 초안**으로 보존한다. `corpus-manifest-draft-v2.json`은 I에 초기 설치 컴퓨터가 거의 가득 찬 1000×1000 격자를 추가한 79개(공개 26개+숨김 53개)의 새 미승인 초안이다. 이 사례는 올바르지만 `list.pop(0)`으로 큐 앞을 반복 삭제하는 풀이를 구분하기 위해 만들었다. B의 보충 입력 중 대표 6개만 두 초안에 넣었다. `py scripts/generate_freshman_corpus_manifest.py --verify`는 **현재 v2**의 지문·생성기·검사 코드와 목록이 달라지면 실패한다. 새 초안으로 이전 v1의 78개 실측을 소급해 79개 통과라고 주장하지 않는다.

격리 측정 경로 `--suite freshman-draft`는 기존 31입력 `freshman`과 별개다. 현재 실행기는 v2의 공개 예제 26개를 sample, 숨김 후보 53개를 hidden으로 전달한다. `freshman-draft-candidate`는 설치 이미지 검증과 합산되지 않는 B++ 진단용이다. 생성기 원본·각 사례·초안 해시가 고정 목록과 다르면 실행 전 거절하고, 결과 합산도 `--suite freshman-draft --manifest tools/freshman_contest/corpus-manifest-draft-v2.json`으로 동일성을 확인한다. 합산기는 이전 v1 보고서를 v1 manifest와 함께 검증할 수 있지만 두 버전을 혼합하지 않는다. `scripts/build_freshman_measurement_package.py`가 고정 기준 소스 60개와 생성기·v2 초안만 담은 전용 아카이브를 만들며, 이것은 운영 채점 데이터나 배포 이미지가 아니다.

[v1의 실제 Linux 측정](../../docs/freshman-draft-measurements-2026-09-27.md)은 Python·C·C++·Java·JavaScript에서 각각 78/78 AC, 설치 B++에서 G TLE/J CE, 격리 적용 B++ 후보에서 78/78 AC였다. v2는 Python·C·C++·Java·JavaScript 기준 풀이가 각각 79/79 AC인 첫 실행을 추가로 확인했고, 설치 B++은 다시 G CPU TLE/J CE로 8/10만 통과했다. 수정 B++ 후보를 컴파일 단계에만 읽기 전용 적용한 별도 v2 첫 실행은 79/79 AC였으나 설치 이미지 수락은 아니다. F/I/J의 `slow_solutions/python`은 기준 풀이가 아닌 ‘정답이지만 느린’ 제한 분리용 독립 제출 소스다. `--suite freshman-slow`는 이 세 소스만 포함하는 별도 진단 아카이브로 고정된 v2 입력 하나씩에서 빠른 풀이와 비교하며, 첫 실제 Linux/cgroup 검사에서 빠른 풀이 3 AC·느린 풀이 3 CPU TLE였다. 최종 설치 이미지, 모든 언어의 반복 측정과 최종 제한 승인은 남아 있다. 어느 초안도 운영 등록 승인을 뜻하지 않는다.

`scripts/summarize_freshman_measurements.py`는 원시 보고서의 중복 반복 번호, 바뀐 소스·입력·실행 이미지·측정 도구·호스트·한도를 섞어서 세지 않는다. 최소 10회 자료가 모두 모여도 `policyApproved=false`다. 최종 데이터 검수, 여러 정상·느린 풀이의 구분, 정상 동시성·기동 조건 및 외부 승인은 별도다. 첫 언어별 실행 결과는 별도 측정 보고서에 기록한다. 비공개 등록 API와 기본 검증 전용 CLI는 `scripts/import_private_contest.py` 및 `docs/contest-authoring-workflow-2026-09-26.md`를 참고한다. 등록 도구의 존재는 운영 등록 승인이 아니다.

`scripts/build_freshman_private_package.py`는 이 v2 초안으로 A–J 비공개 묶음과 내용 주소 hidden blob을 오프라인에서 만드는 별도 단계다. 설정 틀에는 일정·세부 난이도·배점을 비워 두며, 출처는 `pending`, 공개는 `forbidden`, 자원 제한은 `unmeasured`로만 둔다. 공개 예제 26개는 inline, 숨김 후보 53개는 모두 `stored-v1` 참조로 생성한다. 네트워크·DB·업로드·등록·검수 승인은 수행하지 않으며 자세한 절차와 차단 조건은 출제 워크플로 문서에 있다.

생성한 POSIX owner-only 묶음은 `scripts/apply_private_contest_bundle.py 묶음디렉터리`로 전체를 다시 검증한다. 기본 모드는 3개 메타데이터 파일과 package의 stored 참조, index, 모든 blob의 exact closure·해시·크기·UTF-8·권한만 확인하며 토큰이나 네트워크를 사용하지 않는다. 별도 승인 뒤 `--apply`를 주었을 때만 검증된 blob 전부의 identity 영수증을 받은 다음 같은 package를 비공개로 등록한다. 이 도구도 공개, 검수 승인, 일정·배점·난이도 확정을 대신하지 않는다.

## 정답 비교 근거

저장소의 `backend/tests/test_freshman_*_sources.py`, `test_banks_*_reference.py`가 설치된 로컬 도구만 사용해 소스를 컴파일·실행한다. 도구가 없으면 설치하지 않고 명시적으로 skip한다.

| 언어 | A–I | J |
| --- | --- | --- |
| C / C++ | 지문 예제 22개 + seed 71/1847 입력 126개 | 89개: 지문·seed 0/73/1926·무작위 50개·음수 나눗셈·최대 N 포함 |
| Java | 위 148개 + 부호 입력 회귀 8개 | 89개 |
| JavaScript | 위 148개 + 부호 입력 회귀 8개 | 위 89개 + 명시적 `+` 부호 입력 1개 |
| Python | 156개: 지문 예제 22개 + seed 71/1847 입력 126개 + 부호 입력 회귀 8개 | 90개: 지문·seed 0/73/1926·무작위 50개·음수 floor 나눗셈·최대 N·명시적 `+` 부호 입력 포함 |
| B++ | 114개: A–D39/E–G34/H–I41. 예제22개, 지정 seed 입력, `+`/공백/버퍼 경계, E100만 글자·F10만 등록(조회3)·G1000명·H100×100·I1000×1000의 일부 최대 입력 포함 | 90개: 다른 언어와 같은 J oracle 묶음, 음수 floor·중복 누적합·큰64-bit 답·최대N·명시적 `+` 포함 |

## A–I 최대·적대 corpus와 Python 회귀

`backend/tests/test_freshman_stress_cases.py`는 A2/B3/C2/D2/E3/F2/G3/H3/I3, 합계 23개 descriptor를 validator·실제 입력에서 다시 계산한 closed-form 기대값·작은 구조 oracle으로 확인한다. 이어서 standalone Python A–I 기준 소스를 descriptor 하나씩 순차 실행해 23개 출력을 모두 대조한다.

이 묶음은 로컬에서 **3 PASS**였다. 순차 Python 실행에는 테스트 안전장치로 case당 10초 deadline과 stdout/stderr 각각 512 KiB 상한을 둔다(D/F 출력도 포괄, 두 버퍼 최대 합계 1 MiB). 이는 대회 제한값이나 Linux 자원 벤치마크가 아니며, 여섯 언어 실측·공식 최대 입력 package/manifest·저장소/API/워커 연결의 수락 증거도 아니다.

B++ 기능 검사는 명시한 기존 Windows `v13_stage1.exe`, NASM2.16.03, MSVC linker14.50 도구를 사용했다. `BPP_COMPILER`, `BPP_NASM`, `BPP_LINKER`를 지정하지 않으면 실행 검사는 skip하며 파일 목록만 확인한다. 신뢰된 출제 소스만 실행하고 stdin·stdout·컴파일 assembly 크기와 시간을 제한한다. 8개 테스트(목록4+실행4)가 30.79초에 통과했다. I의 최대 입력은 모두 갱신된 상태이며, F의 최대 입력은 등록 수만 최대다. 전체 최대 출력·최악 전파·성능 수락으로 확대 해석하지 않는다.

현재 확인한 Windows 도구는 MinGW GCC15.2.0, Java25(`javac --release 17`), Node22.19.0, Python 3.13.7이다. Python 검사는 pytest를 실행한 `sys.executable`을 그대로 사용하므로 Linux CI에서도 별도 설치 없이 같은 비교를 수행한다. 배포 이미지의 런타임 버전과 같다고 가정하지 않는다. **위 비교는 함수 정답 검증이며, 실제 Linux 자원 측정 또는 실행 시간·메모리 제한을 확정하는 벤치마크가 아니다.** 실행별 안전 timeout 역시 대회의 제한값이 아니다.

J의 정답 기준은 독립적으로 유도한 주기적 역전 수 알고리즘이다. C/C++/Java/JS 포트는 같은 증명을 따르므로 서로 독립적인 알고리즘 네 개로 세지 않는다. Python 버전의 작은 입력 BFS와 이차식 비교 검사가 별도로 있다. 검증되지 않은 코드나 참가자 제출을 로컬 프로세스 테스트 helper에 넣으면 안 된다.

최신 종합 상태는 `docs/freshman-contest-implementation-matrix-2026-09-26.md`를 기준으로 한다. 모든 언어·모든 경계·실제 Linux 채점이 완료된 출제 패키지라는 뜻은 아니다.
