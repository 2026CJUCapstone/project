# 신입생 A–J 고정 초안 격리 채점 기록

2026-09-27 측정 합산 관문 후속: 새 보고서만 최종 10회 자료에 포함되도록 호스트 감시 시간의 언어·계산 근거·경과 시간, 정리 후 재탐색, 정리 전후 용량을 필수로 검사한다. 각 AC 단계도 frozen contract의 CPU/wall 미만, memory/output 이하인지 다시 대조하고, compile/run 한도에서 계산한 전체 deadline과 reservation이 일치해야 한다. 합성 회귀 **44 PASS**이며, 기존 v2 C/C++/Python/Java/JavaScript 50문제의 445단계는 새 자원 대조를 모두 통과했다. 다만 이 과거 원시 보고서에는 새 호스트 정리 envelope가 없으므로 기존 합산 기록은 역사 자료로 보존하되 향후 `tenPassDatasetComplete`의 입력으로 재사용하지 않는다. 다섯 언어와 수정된 B++가 들어간 동일 새 이미지에서 1–10회를 다시 모아야 한다.

작성: 2026-09-27. **미승인 출제 초안의 진단 실행**이며 대회 제한값, 운영 채점기 수락 또는 배포가 아니다.

> 기존 Linux 원시 보고서는 **v1, 78개 입력**에 묶여 있다. 이후 I의 큰 초기 큐를 구분하는 입력 하나를 추가한 [v2 manifest](../tools/freshman_contest/corpus-manifest-draft-v2.json) (`sha256:e5213ca9d1aaf3691c91db22aa021870b532b653c015c58c4bf90fff8a8539fc`, 79개)을 별도로 생성했다. 아래 v1의 78개 통과 수치를 v2의 통과 증거로 재사용하지 않는다. v1 manifest와 원래 전용 아카이브는 이전 결과 재검증용으로 보존했다.

## v2 후속 Python 격리 측정

[v2 Python 원시 보고서](evidence/freshman-draft-v2-python-r1-2026-09-27.json), 파일 SHA-256 `9548a94d27674399c774e58189cbaddb077d91670265c238bf0faa5d29fb7975`: 별도 전용 아카이브 `sha256:053472836c1e7fe5b2652cadb2697dc88046cb16dbba1c6af0ec4ce8b9d18ebc`와 위 v2 manifest의 A–J 10/10, 입력 79/79 AC, 컴파일 10개+케이스 실행 79개=단계 컨테이너 89개, 잔여 0개다. 새 `i-maximum-many-sources-front-delete-discriminator`의 한 번 측정치는 CPU 2,627,715µs, wall 2,621,388,939ns, 단계 메모리 피크 67,846,144바이트였다. 이 정답 풀이 결과만으로는 정답의 10회 안정성이나 느린 풀이 배제를 증명하지 못하므로, 느린 풀이의 별도 비교를 다음 절에 기록했다. v2 합산 결과는 `recordCount=10`, `tenPassDatasetComplete=false`, `policyApproved=false`다. 원격 임시 경로 `/tmp/webcompiler-launcher-test.8Lz6ZCho`는 보고서 해시·정확한 경로·소유자·컨테이너 0개 확인 후 제거했다. 운영 DB/큐/대회/서비스는 바꾸지 않았다.

## v2 F·I·J 빠른/느린 풀이의 첫 비교

[비교 원시 보고서](evidence/freshman-draft-v2-slow-python-r1-2026-09-27.json), 파일 SHA-256 `a3b8d97de0c5d2a1d4dbbe7c10daf80e0c2b3a63a9f5b13fdfac2820a162a790`: 기존 v2 manifest를 바꾸지 않고 느린 풀이 3개만 추가한 **별도 진단 아카이브** `sha256:a90de99a98085194e3d6cd371f76c74fa3727efc60c8f31c1f35aec9fcc596a0`을 사용했다. Python 3.14.4에서 각 문제의 고정된 동일 입력 하나를 빠른 풀이와 느린 풀이로 각각 새로 제출했다. 모두 한 번 컴파일·한 번 실행했으며 빠른 풀이 3/3 AC, 느린 풀이 3/3 CPU 시간 초과, 단계 컨테이너 총 12개/잔여 0개였다.

| 문제 | 빠른 풀이 CPU | 느린 풀이 CPU | 이 진단에서의 결과 |
| --- | ---: | ---: | --- |
| F | 78,086µs | 5,004,694µs | CPU 상한 도달 |
| I | 2,332,905µs | 5,012,179µs | CPU 상한 도달 |
| J | 83,837µs | 5,005,752µs | CPU 상한 도달 |

각 느린 실행의 보호 계측에서 `failureReason=time_limit_exceeded`, `oomKills=0`, `treeReaped=true`이고 CPU 5초 경계를 넘었다. 이는 **진단용 CPU 5초·wall 8초·메모리 512MiB에서의 단 한 번의 분리**다. 느린 풀이의 작은 입력 정답 비교와 최대 입력 기대값 검사는 별개 오프라인 증거이며, 이 한 번으로 정답 풀이의 10회 안정성·다른 언어의 제한·최종 문제별 정책을 승인하지 않는다. 운영 설정을 변경하지 않았다. 컨트롤러는 기존 호스트 Docker 소켓을 사용하므로 별도 데몬 격리도 아니다. 서버 임시 경로 `/tmp/webcompiler-launcher-test.smLE2aKr`는 원시 파일의 로컬/서버 해시 일치, 정해진 경로·소유자·심볼릭 링크 부재·잔여 테스트 컨테이너 0개 확인 후 제거했고 원시 보고서는 보존했다.

## v2 다섯 언어 기준 풀이 첫 실행

같은 v2 manifest(`sha256:e5213ca9d1aaf3691c91db22aa021870b532b653c015c58c4bf90fff8a8539fc`), 기준 아카이브(`sha256:053472836c1e7fe5b2652cadb2697dc88046cb16dbba1c6af0ec4ce8b9d18ebc`), 앱 아카이브(`2e18d203661ac3932f11b965b7ceb0abde190a607a1d27a61bac0b8911e70a68`), 런타임 이미지와 호스트 스크립트로 각각 한 번씩 격리 실행했다. 현재 도구 해시 `fd8fb2c7083884043816927b89a6ef789838a8d7632b8d63c60bb66038fbfacc`의 원시 보고서는 다음과 같다.

| 언어 | 원시 보고서 SHA-256 | 결과 |
| --- | --- | --- |
| [Python](evidence/freshman-draft-v2-python-r1-current-probe-2026-09-27.json) | `728b0ce07e859fee893c99f2545c756e013172491b05d5860e811c9e916ee233` | A–J 10/10, 입력 79/79 AC, 단계 89/잔여 0 |
| [C](evidence/freshman-draft-v2-c-r1-2026-09-27.json) | `af4271d8bd87cdf6b7ebb13c72c900e1888ce02ff6a3a7131c10b7c24e6796b4` | A–J 10/10, 입력 79/79 AC, 단계 89/잔여 0 |
| [C++](evidence/freshman-draft-v2-cpp-r1-2026-09-27.json) | `148b63ab7c39b37d128f1ccf844171f6ec2dc733dcd22b53782a9be79de7ee96` | A–J 10/10, 입력 79/79 AC, 단계 89/잔여 0 |
| [Java](evidence/freshman-draft-v2-java-r1-2026-09-27.json) | `dc5d328755714ae1c2bd40870b0306aedaa472d5a591bd1b7f4e1dfbdab19b9f` | A–J 10/10, 입력 79/79 AC, 단계 89/잔여 0 |
| [JavaScript](evidence/freshman-draft-v2-javascript-r1-2026-09-27.json) | `1b687183ebc93d7b7c43aad8989a21bf61d4bb118efeb25b716090f95978ed0b` | A–J 10/10, 입력 79/79 AC, 단계 89/잔여 0 |

엄격 합산 결과 `.deploy/freshman-draft-v2-five-language-summary-r1.json`은 **50문제·395입력 AC, 총 445단계**, `recordCount=50`, `tenPassDatasetComplete=false`, `policyApproved=false`다. 합산기는 이전 Python 원시 보고서가 호스트 스크립트 `c7aa9e2c…`에서 생성된 사실을 감지해 처음 합산을 거절했다. 그 보고서를 변경하거나 검사 조건을 낮추지 않고 위 현재 도구로 Python을 다시 실행했다. 이전 원본은 위 첫 v2 절의 독립 이력으로 보존한다. J의 9,999개 은행 긴 블록 사례는 기준 풀이/생성기의 출력 계산을 호출하지 않는 별도 정렬·누적합 오라클로도 기대 해시를 대조했다(오프라인 1 PASS).

각 서버 임시 경로 `nJ1Rhbvo`, `yiHsl6ce`, `BUtdj1L6`, `P1iXeqrD`, `a0cXBk3Y`는 정확한 경로·소유자·링크 부재·테스트 컨테이너 0개·보고서의 로컬/서버 해시 일치를 확인한 뒤 제거했다. 운영 대회/DB/큐/설정·이미지 설치·배포는 하지 않았다. **최종 수정 B++ 이미지, 각 언어 2–10회 반복과 최종 제한값 검수는 남아 있다.**

## v2 설치된 B++ 첫 실행: 미통과

[설치 B++ 실패 원시 보고서](evidence/freshman-draft-v2-bpp-installed-r1-failed-2026-09-27.json), 파일 SHA-256 `413134aa98accbdaf70bfc3e110689b06e59e59d7f2adaaae5939b84e996c22f`: 같은 v2 manifest·아카이브·현재 호스트 스크립트에서 설치 컴파일러 바이너리 `sha256:8cd02a03dd9f817bc50a644160dd06b70f4dfe8982abac9f61d6faebcfa9e960`를 수정하지 않고 실행했다. A–F·H·I는 통과했으나 G의 첫 사례는 CPU 5,003,808µs에서 시간 초과(`oomKills=0`), J는 `std_mem__bpp_gc_root_slot_remove` 미정의 심볼로 컴파일 오류가 났다. 총 **8/10문제**, 단계 컨테이너 72개/잔여 0개다. 컨트롤러 종료 코드 1의 원시 실패를 성공 합산에 넣지 않았다. 원격 `/tmp/webcompiler-launcher-test.DMfhkzd1`은 보고서 해시·정확한 경로·소유자·링크 부재·테스트 컨테이너 0개 확인 후 제거했다. 수정 후보가 앞서 v1 78개를 통과했어도, 설치된 B++의 v2 통과나 최종 수정 이미지 수락을 뜻하지 않는다.

## v2 수정 B++ 후보 첫 실행: 격리 적용만 통과

[후보 원시 보고서](evidence/freshman-draft-v2-bpp-candidate-r1-2026-09-27.json), 파일 SHA-256 `bc1568bb77ef4af273cf8b6730b24709f1d4dcc6c3e18d0aa350eb07bdf1eb43`: 같은 v2 manifest·기준 아카이브에서 고정 후보 ELF `sha256:7f4864362863ddc9daa687d221387e9f2612220521f89e8a9e05b2e3f40b4a23`와 해당 소스 아카이브 `sha256:010e9abd3e2469b6bd1b4ee006ed142e695ecf8ee8af0b81b62fac764d2355bf`를 **컴파일 단계에만 읽기 전용으로 덧붙였다.** 각 실행 단계는 기존 이미지에서 후보가 만든 정확한 산출물 해시에 묶어 수행했다. A–J **10/10, 79/79 AC**, 단계 컨테이너 89개/잔여 0개다. 보고서는 컴파일 마운트·실행 단계 비적용·단계별 산출물 일치를 기록하고 `imageAccepted=false`를 명시한다.

전용 전송 경로가 정해진 두 후보 파일의 해시를 먼저 확인했고, 큰 파일은 조각별 전송 후 전체 해시를 검증했다. 원격 `/tmp/webcompiler-launcher-test.VfajOxhf`는 원본 보고서의 서버/로컬 해시 일치, 정확한 경로·소유자·링크 부재·잔여 컨테이너 0개를 확인했다. 읽기 전용 후보 디렉터리 중 이 임시 경로 안의 디렉터리에만 소유자 쓰기 권한을 돌려 제거했고 최종 경로 부재를 확인했다. 이미지 설치·운영 설정·대회 데이터·배포는 없었다. 후보 한 번의 통과를 설치된 B++의 성공 합산이나 최종 제한 승인에 더하지 않는다. 최종 이미지의 실제 설치·반복 수락은 별도로 남는다.

이전 v1 결과와 v2 결과는 corpus identity가 달라 한 합산 자료로 세지 않는다. 현재 v2의 수정 B++ 후보와 최종 설치 이미지 검증, 각 언어 반복 2–10, 느린 풀이 비교의 반복성·다른 오답군 검증이 남아 있다.

## 고정 대상과 실행 경계

- 초안 manifest `sha256:12f0c6f989b9736b0f5784fe29de2400b7cf06bc71d63330629f74a24d20b764`: A–J 총 78개(공개 예제 26개, 숨김 후보 52개). 예전 31-descriptor 측정과 구별한다.
- 전용 소스 아카이브 `sha256:1021333d2822e4849e887e0e4b1847717925918bc1b183f822e4aec18c83020a`, 앱 측정 아카이브 `2e18d203661ac3932f11b965b7ceb0abde190a607a1d27a61bac0b8911e70a68`.
- 기존 불변 런타임 이미지 `sha256:7a3aa3717f2c62f60ff52f680335ebee414151136d6f836382b1b543a43c5db1`, 기존 백엔드 컨트롤러 이미지 `sha256:d7ab3494aad02142fe7fc4abee8175283a2ce68e57cfc7bb24da034753065930`. 이미지 pull/build/install 없음.
- 배포 서버의 임시 경로에만 테스트 파일을 복사했다. 한 번에 하나의 언어, 컨트롤러 384MiB/0.5 CPU, 단계 컨테이너 최대 512MiB/1 CPU, 네트워크 없음, 읽기 전용 루트, swap 증가 없음. 운영 DB·Redis·큐·점수판·대회 데이터에는 연결하지 않았다. **컨트롤러가 호스트 Docker 소켓을 갖는 기존 구조이므로 별도 Docker 데몬 수준의 제어권 격리는 아니다.**
- 이 앱 아카이브는 현재 작업 트리와 8개 비측정 관련 파일이 다르다(`initialize.py`, contest rejudge/authoring/model/DB/contest route). 실제 결과의 정확한 앱 소스는 위 아카이브 해시로 식별한다. 현재 전체 서버·DB 경로를 검증했다고 주장하지 않는다.

## 첫 시도와 수정

첫 [원시 실패 보고서](evidence/freshman-draft-python-r1-failed-2026-09-27.json), 파일 SHA-256 `ef53a2e602e5c78d41988f010d8aefaff6f34080926fbba2011ead2b54acc168`: Python A/C–I 8문제는 통과, B/J는 **실행 전** `Receipt job deadline exceeds the current service ceiling`로 거절됐다. 최대 12사례 × 진단용 10초 wall + 10초 컴파일 + 5초 정리 = 135초가 기존 서비스 상한 120초를 넘은 것이 원인이다. 오답·TLE·MLE로 해석하지 않는다. 62단계 컨테이너가 생성됐고 최종 잔여는 0이었다.

서비스 상한이나 운영 정책을 높이지 않았다. **초안 실측 전용** 케이스 wall 상한만 8초로 정해 최악 12사례도 `10 + 12×8 + 5 = 111`초가 되도록 했다. CPU 5초, 메모리 512MiB 등 다른 진단 상한은 유지한다. 이 수치는 최종 대회 언어별 제한이 아니며, 정답 풀이가 8초 근처에서 흔들리는지 반복 측정해야 한다.

## Python 재실행

[원시 성공 보고서](evidence/freshman-draft-python-r1-2026-09-27.json), 파일 SHA-256 `e20535ba3e2c59ce1fb625c085320b8b937f06b00b2c1fc51e2847647a3353e9`: Python 3.14.4 기준 **A–J 10/10, 초안 입력 78/78 AC**, 컴파일 10개+새 실행 78개=단계 컨테이너 88개, 잔여 컨테이너/작업 디렉터리 0개. 최대 단일 실행 CPU 2,476,495µs, wall 2,470,346,156ns, 단계 메모리 피크 119,054,336바이트다. 이는 서로 다른 입력 중의 최대이며 제한값을 승인하는 통계가 아니다.

## C·C++·Java·JavaScript 첫 실행

[C 원시 보고서](evidence/freshman-draft-c-r1-2026-09-27.json), 파일 SHA-256 `473d612fb9d12700bccbd8c4020436c9bb5b82bbada26119ff4cf124c80e085d`: 동일한 manifest·아카이브·기존 런타임 이미지에서 GCC 15.2.0의 A–J 10/10이 통과했다. 컴파일 10개+실행 78개=단계 컨테이너 88개, 잔여 컨테이너/작업 디렉터리 0개다. Python과 C의 원시 보고서를 함께 검증한 전용 합산기는 `combinationCount=20`, `recordCount=20`, `tenPassDatasetComplete=false`, `policyApproved=false`로 판정했다.

[C++ 원시 보고서](evidence/freshman-draft-cpp-r1-2026-09-27.json), 파일 SHA-256 `0c66af19fae1b7913ce4ce2746c6a7590c8d8c46c7ec66e1dcbab513197f620c`: GCC/G++ 15.2.0의 A–J 10/10, 입력 78/78 AC, 단계 컨테이너 88개/잔여 0개. 아직 각 언어 한 번씩만 실행한 결과이며 제한값 승인 자료가 아니다.

[Java 원시 보고서](evidence/freshman-draft-java-r1-2026-09-27.json), 파일 SHA-256 `0c45b3a266229aedc2d7a28f0353f6dd1ffcd67ee9599d98d25b532e28e36958`: OpenJDK 25.0.4의 A–J 10/10, 입력 78/78 AC, 단계 컨테이너 88개/잔여 0개.

[JavaScript 원시 보고서](evidence/freshman-draft-javascript-r1-2026-09-27.json), 파일 SHA-256 `bc909a091bbda498b1a7725cdeafb424b2e2a76a6d1c21d0d0ce7bff98ee3579`: Node.js 24.21.0의 A–J 10/10, 입력 78/78 AC, 단계 컨테이너 88개/잔여 0개. 다섯 성공 보고서를 하나로 검증한 합산기는 `combinationCount=50`, `recordCount=50`, `tenPassDatasetComplete=false`, `policyApproved=false`다. 각 언어 한 번씩의 진단 결과일 뿐이다.

## 설치된 B++ 첫 실행: 미통과

[B++ 실패 원시 보고서](evidence/freshman-draft-bpp-installed-r1-failed-2026-09-27.json), 파일 SHA-256 `111439c254304e776c7433ac950503cf439349f88779188cfab8a10c73b60426`: 설치된 컴파일러 바이너리 `sha256:8cd02a03dd9f817bc50a644160dd06b70f4dfe8982abac9f61d6faebcfa9e960`에서 A–F·H·I는 통과했으나, G는 첫 부분에서 CPU 시간 초과, J는 `std_mem__bpp_gc_root_slot_remove` 심볼 누락 컴파일 오류가 발생했다. 8/10 문제만 통과했으므로 이 보고서는 성공 합산에 넣지 않았다. 기존 소규모 검사에서 드러난 G/J 결함이 더 큰 초안에서도 반복된 것이다. 이 결과를 예제 문제의 오답이나 최종 제한값 결론으로 해석하지 않는다.

## 수정 B++ 후보 첫 실행: 격리 적용만 통과

[후보 원시 보고서](evidence/freshman-draft-bpp-candidate-r1-2026-09-27.json), 파일 SHA-256 `a60fa591bbf9775d842da2722249a180c8ad94ce580a6a54db894e0d3e89d30d`: 검증된 별도 컴파일러 바이너리 `sha256:7f4864362863ddc9daa687d221387e9f2612220521f89e8a9e05b2e3f40b4a23`와 그 소스 아카이브 `sha256:010e9abd3e2469b6bd1b4ee006ed142e695ecf8ee8af0b81b62fac764d2355bf`를 **컴파일 단계에만 읽기 전용으로 적용**했다. 동일한 초안 입력 A–J 10/10, 78/78 AC, 단계 컨테이너 88개/잔여 0개다. 실행 단계는 기존 이미지에서 후보가 만든 산출물을 돌렸다. 후보 이력·바이너리 해시·컴파일 단계의 읽기 전용 마운트·각 실행 단계 산출물 해시가 보고서에 묶여 있다. 후보는 이미지에 설치하거나 채점 서비스에 등록하지 않았고, 일반 설치 이미지 합산에도 넣지 않았다. 한 번의 격리 통과가 최종 설치 런타임 수락은 아니다.

같은 언어의 반복 2–10과 수정 B++의 최종 설치 이미지 재검증이 남았다. F의 선형 질의, I의 앞 삭제, J의 이차 풀이에 대한 첫 실제 분리는 위 v2 후속 절에 별도로 기록했다. 아직 한 번의 진단 결과여서 최종 제한을 정할 근거가 아니며, 다른 오답군·정상 동시성·기동 조건, 실제 DB/워커/공개 프록시 통합, 최종 데이터 검수·이용 조건/난이도/일정/점수 승인도 남는다.

Python 두 원격 테스트 경로, C `pSBHgHoi`, C++ `foJHDMQJ`, Java `2rWGPSNi`, JavaScript `zFBptWVq`, 설치 B++ `P2BtZ9lj`, 후보 B++ `YJxd895L`의 `/tmp/webcompiler-launcher-test.*` 경로는 각 보고서 파일 해시·소유자·정확한 경로·컨테이너 0개를 확인하고 제거했다. 후보 전송 중 큰 SCP 연결이 끊겨 부분 파일을 확인·삭제하고 해시 검증되는 분할 전송으로 재시도했다. 후보 임시 파일의 읽기 전용 디렉터리 때문에 첫 제거가 거절되어 정확한 소유 경로와 링크 부재를 재확인하고 해당 임시 디렉터리에만 쓰기 권한을 돌린 뒤 제거했다. 로컬 원시 보고서는 남겼다. 운영 등록·배포·Git push는 하지 않았다.
