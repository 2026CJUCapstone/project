# 의존성 목록과 취약점 검사 (A17)

## 현재 구현 범위

CI는 프런트 `package-lock.json`과 백엔드 `requirements.lock`에서 CycloneDX JSON 의존성 목록(SBOM)을 생성한다. `scripts/verify_sbom.py`는 목록에 들어 있는 패키지 이름·버전 집합을 잠금 파일과 대조한다. 개발·선택적 의존성도 프런트 잠금 파일에 있으면 포함한다. 같은 버전을 여러 위치에 설치하는 경우 패키지·버전 집합에서는 하나로 계산하며, 서로 다른 버전은 별도로 검사한다.

검증기는 다음을 거부한다.

- 잠금 파일에 없는 패키지, 누락된 패키지, 다른 버전
- 비어 있거나 중복된 컴포넌트 참조, 존재하지 않는 그래프 참조
- 지원하지 않는 잠금 형식, 고정되지 않은 Python 의존성
- 입력당 32MiB 초과, 잘못된 커밋 식별자 형식, 기존 확인 파일 덮어쓰기

통과하면 확인 파일에 잠금 파일 SHA-256, SBOM SHA-256, CI가 전달한 소스 커밋, 컴포넌트 수와 고유 패키지·버전 수를 기록한다. 커밋 값은 CI의 `GITHUB_SHA`다. 검증기가 직접 Git checkout의 청결 상태나 서명을 확인하는 것은 아니다.

## 도구와 CI 동작

| 대상 | 생성·검사 | 결과 |
|---|---|---|
| 프런트 | `npx --yes --package npm@11.19.1 -- npm sbom --package-lock-only --sbom-format cyclonedx --sbom-type application` | CycloneDX 1.5 |
| 프런트 취약점 | `npm audit --audit-level=low` | 발견 또는 검사 실패 시 CI 실패 |
| 백엔드 | 전용 venv의 `pip-audit==2.10.1`, `--requirement backend/requirements.lock --disable-pip --strict --format cyclonedx-json --output ...` | CycloneDX 1.4, 발견 또는 검사 실패 시 CI 실패 |

SBOM 생성용 npm만 별도로 고정한다. 앱 의존성이나 전역 npm을 바꾸지 않는다. 로컬 npm 10.9.3은 동일 버전의 여러 설치 위치에서 중복 참조를 생성했고, 이 목록은 검증에 실패했다. npm 11.19.1의 실제 출력은 중복 참조 없이 검증됐다. [npm SBOM 문서](https://docs.npmjs.com/cli/commands/npm-sbom/), [pip-audit 문서](https://github.com/pypa/pip-audit).

취약점 검사에서 실패해도 이미 생성된 목록의 정합성 검사는 실행한다. **정합성 검증까지 성공한 경우에만** SBOM과 확인 파일을 함께 업로드한다. 업로드 성공이 취약점 검사의 실패를 덮지는 않는다. 검증에 실패한 raw-only SBOM은 업로드하지 않는다. 산출물 이름에는 CI SHA를 붙이고 보관 기간은 14일이다. 이 기간은 CI 산출물 설정이며 운영 제출 데이터의 보관 정책이 아니다.

## 재현·회귀·통합 검증

후속 Node24.21.0/npm11.19.0의 깨끗한 설치에서는 기존 lock의 DOMPurify 선택 의존성 `@types/trusted-types@2.0.7` 누락을 발견했다. 격리 복사본에서 npm이 생성한 차이를 검토해 해당8줄만 보완했고 기존 패키지 버전은 바꾸지 않았다. 최신 프런트 lock SHA-256은 `bfd94453473d4a3bfc15ca07eb5402e094ec04dfdd3c36a9fcba385bbd1e83cc`이며, 실제 SBOM 재생성/대조2개 검사가6.55초에 통과했다(프런트572개/백엔드43개). 아래571개 기록은 수정 전 검증 이력이다.

2026-09-10 로컬 Node 22.19.0에서 고정 npm 생성기를 실제 실행해 **571개** 고유 패키지·버전이 현재 프런트 잠금 파일과 일치함을 확인했다. 백엔드는 별도 감사 venv의 pip-audit 2.10.1로 **43개**가 일치했고, 실행 시점의 공개 advisory 조회에서 알려진 취약점이 없다고 보고했다. 테스트용 확인 파일의 all-ones SHA는 fixture 값이며 실제 릴리스 증명이 아니다.

- `backend/tests/test_sbom_inventory.py`: scope·중첩·alias·dev/optional·다중 버전, Python 이름 정규화, 누락/추가/변조, npm 10 중복 참조 재현, 잘못된 그래프, 지원하지 않는 입력, 입력 상한
- `backend/tests/test_sbom_cli.py`: 실제 CLI의 확인 파일·hash 생성, stdin, 실패 시 미생성, 기존 파일 보존
- `backend/tests/test_sbom_ci.py`: 검사 실패가 무시되지 않는지, 검증 성공 때만 두 파일을 업로드하는지, 도구 버전과 잠금 파일 연결 확인. GitHub Actions를 실제 실행하는 테스트는 아니다.
- `backend/tests/test_sbom_generators_live.py`: 실제 현재 잠금 파일과 실제 도구 출력의 대조, 그 출력의 버전을 바꿨을 때 거부하는지 확인. `RUN_SBOM_INTEGRATION=1`, npm 실행 파일 `SBOM_NPX`, pip-audit 전용 Python `SBOM_AUDIT_PYTHON`을 설정해야 한다. 미설정 skip은 통과가 아니다. 앱 패키지를 다시 설치하지 않지만 도구 다운로드와 advisory 조회에는 네트워크가 필요하다.

현재 집중 회귀와 기존 배포 CI gate 검사는 **91개 통과**, 실제 생성 도구 통합 검사는 **2개 통과**했다. 이 두 범위는 별도 실행이며 전체 서비스 검증을 대신하지 않는다.

최종 현재 소스의 백엔드 전체 로컬 회귀는 **1770개 통과·340개 skip, 66.81초**다. skip에는 플랫폼·외부 인프라·명시적 opt-in 조건이 포함되며 실제 서버 통과로 계산하지 않는다. 프런트 제품 코드는 이번 SBOM 변경에서 수정하지 않았다.

## 남은 범위

이 목록은 **소스 잠금 파일의 의존성 목록**이다. 설치된 이미지·OS 패키지·B++ 컴파일러 툴체인 목록, 전체 CycloneDX 스키마나 dependency edge 정확성, 서명된 provenance, 운영 이미지 취약점 검사를 증명하지 않는다. advisory 미등록 취약점이 없다는 뜻도 아니다.

A17의 외부 기본 이미지 digest는 후속 [이미지 lock 작업](image-lock.md)에서 고정하고 실제 registry manifest를 검증했다. Node24로 설정을 이전했으나 실제 Linux 실행 이미지 검증, 이미지 수준 검사, CI 실제 실행·검사한 SHA와 배포 산출물 연결 확인은 남아 있다. 현재 2GiB 격리 빌더의 프런트 빌드 실패도 별도 미해결 조건이다. 소스 SBOM 통과만으로 이 항목이나 전체 A01–A25/로드밸런싱 목표를 완료 처리하지 않는다. 운영 배포와 main push는 하지 않았다.
