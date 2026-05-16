# 오픈소스 활용 보고서 (캡스톤 연계)

## 1. 프로젝트 기본 정보

| 항목 | 내용 |
|---|---|
| 프로젝트명 | B++ Online Compiler / Web Compiler |
| 프로젝트 개요 | 사용자가 웹 브라우저에서 B++, Python, C, C++, Java, JavaScript 코드를 작성하고 컴파일·실행할 수 있는 온라인 컴파일러 서비스 |
| 주요 기능 | 코드 편집기, 컴파일/실행 API, AST/SSA/IR/ASM 시각화, 문제 풀이 및 채점, 리더보드, Docker 기반 격리 실행 환경, 서버 배포 자동화 |
| 팀명 / 팀원 | [제출 전 팀명 및 팀원명 작성] |
| GitHub 저장소 | https://github.com/2026CJUCapstone/project |
| 작성 기준 | `frontend/package-lock.json`, `frontend/package.json`, `backend/requirements.txt`, `Dockerfile`, 주요 소스 코드 import 및 사용 위치 기준 |

## 2. 프로젝트 기본 정보

본 프로젝트는 컴파일러 학습 및 실습을 웹 환경에서 수행할 수 있도록 설계한 캡스톤 프로젝트이다. 프론트엔드는 React 기반 단일 페이지 애플리케이션으로 구성하였고, 백엔드는 FastAPI를 통해 컴파일·실행·문제 관리·리더보드 API를 제공한다. 사용자 코드 실행은 서버 프로세스에서 직접 수행하지 않고 Docker 컨테이너 내부에서 제한된 권한으로 실행하여 보안성과 재현성을 확보하였다.

서비스 구조는 다음과 같다.

| 모듈 | 역할 |
|---|---|
| `frontend/` | 웹 IDE, 코드 편집기, 그래프 뷰어, 문제/리더보드 화면 |
| `backend/` | REST API, WebSocket 터미널, 문제/점수 저장, Docker 실행 제어 |
| `runtime/` | B++ 컴파일러와 C/C++/Java/Python/JavaScript 실행 도구가 포함된 샌드박스 이미지 |
| `.github/workflows/` | CI 성공 후 원격 서버 배포 자동화 |

## 3. 오픈소스 사용 목록

프론트엔드 JavaScript/TypeScript 패키지는 `package-lock.json` 기준의 실제 해석 버전을 기재하였다. 백엔드 Python 패키지는 현재 `requirements.txt`에 버전이 고정되어 있지 않으므로 "미고정"으로 표시하였다. 이는 배포 시점의 최신 버전이 설치될 수 있음을 의미하며, 재현 가능한 빌드를 위해 추후 버전 pinning이 필요하다.

| 오픈소스명 | 버전 | 사용 목적 | 적용 기능 | 라이선스 |
|---|---:|---|---|---|
| React | 18.3.1 | 프론트엔드 UI 구성 | IDE, 문제 목록, 관리자, 리더보드 화면 컴포넌트 | MIT |
| React DOM | 18.3.1 | 브라우저 렌더링 | `createRoot` 기반 SPA 렌더링 | MIT |
| Vite | 6.3.5 | 프론트엔드 개발/빌드 도구 | 개발 서버, 번들링, `/webcompiler/` 배포 base path 처리 | MIT |
| TypeScript | 6.0.2 | 정적 타입 기반 개발 | API 타입, 컴파일 결과 타입, 컴포넌트 타입 안정성 | Apache-2.0 |
| Monaco Editor / @monaco-editor/react | 0.55.1 / 4.7.0 | 웹 코드 편집기 | 코드 입력, B++ 언어 등록, 다크/라이트 테마 | MIT |
| React Router | 7.13.0 | SPA 라우팅 | IDE, Challenges, Leaderboard, Admin 화면 이동 | MIT |
| Zustand | 5.0.12 | 전역 상태 관리 | 코드, 실행 결과, 터미널 상태, 테마, 자동저장 상태 관리 | MIT |
| @xyflow/react | 12.10.2 | 그래프 시각화 | AST/SSA 노드·엣지 렌더링, 줌/패닝/미니맵 | MIT |
| Dagre | 0.8.5 | 그래프 자동 배치 | AST/SSA 그래프 노드 위치 자동 계산 | MIT |
| Lucide React | 0.487.0 | 아이콘 시스템 | 실행, 저장, 테마, 문제, 리더보드 등 UI 아이콘 | ISC |
| React Resizable Panels | 2.1.7 | 화면 분할 레이아웃 | 에디터·출력 콘솔·그래프 패널 크기 조절 | MIT |
| Recharts | 2.15.2 | 차트 시각화 | 관리자 페이지 통계 차트 | MIT |
| Tailwind CSS | 4.1.12 | CSS 유틸리티 스타일링 | 전체 UI 레이아웃, 색상, 반응형 스타일 | MIT |
| Radix UI | 1.x 계열 | 접근성 기반 UI primitive | Dialog, Dropdown, Tabs, Tooltip, Select 등 UI 컴포넌트 기반 | MIT |
| clsx / tailwind-merge | 2.1.1 / 3.2.0 | 조건부 class 병합 | UI 컴포넌트 className 조합 및 충돌 제거 | MIT |
| class-variance-authority | 0.7.1 | 컴포넌트 variant 관리 | Button, Badge 등 스타일 variant 구성 | Apache-2.0 |
| Vitest | 3.2.4 | 프론트엔드 단위 테스트 | 라우팅, 상태 저장소 테스트 | MIT |
| Playwright | 1.59.1 | E2E 테스트 | 웹 컴파일러 사용자 플로우 검증 | Apache-2.0 |
| FastAPI | 미고정 | 백엔드 웹 프레임워크 | 컴파일, 실행, 문제, 리더보드 API | MIT |
| Uvicorn | 미고정 | ASGI 서버 | FastAPI 앱 실행 | BSD-3-Clause |
| Pydantic / pydantic-settings | 미고정 | 데이터 검증 및 설정 관리 | 요청/응답 스키마, 환경변수 기반 설정 | MIT |
| SQLAlchemy | 미고정 | ORM 및 DB 접근 | 문제, 사용자, 점수 테이블 모델링 | MIT |
| HTTPX | 미고정 | HTTP 클라이언트 및 테스트 지원 | API 테스트 및 비동기 HTTP 처리 기반 | BSD-3-Clause |
| Docker SDK for Python | 미고정 | 백엔드에서 Docker 제어 | 사용자 코드 실행 컨테이너 생성·시작·로그 수집 | Apache-2.0 |
| pytest / pytest-asyncio | 미고정 | 백엔드 테스트 | API, 컴파일 서비스, 리더보드 테스트 | MIT / Apache-2.0 |
| Docker / Docker Compose | Compose 파일 기준 | 컨테이너 기반 실행·배포 | frontend/backend/sandbox 서비스 구성 | Apache-2.0 계열 |
| Nginx | 1.27-alpine | 정적 파일 서빙 및 프록시 | 프론트엔드 production 서빙 | BSD-2-Clause 계열 |
| Ubuntu | 24.04 | 샌드박스 베이스 이미지 | 컴파일러·런타임 도구 설치 기반 | 구성 패키지별 상이 |
| Node.js | 20.x | JavaScript 실행 환경 | JavaScript 코드 문법 검사 및 실행 | MIT |
| GCC/G++ | Ubuntu 패키지 | C/C++ 컴파일 | C11, C++17 컴파일 및 실행 | GPL 계열, 런타임 예외 포함 |
| OpenJDK | Ubuntu 패키지 | Java 컴파일/실행 | `javac`, `java` 실행 | GPL-2.0 with Classpath Exception |
| B++ Compiler | `main`, bootstrap-v12 | B++ 언어 컴파일 | B++ compile/run, IR/SSA/ASM dump | GitHub 라이선스 미감지 |
| GitHub Actions checkout / ssh-agent | v4 / v0.9.0 | 배포 자동화 | CI 성공 후 서버 배포 워크플로 | MIT 계열 |

## 4. 오픈소스 선택 이유

본 프로젝트는 온라인 컴파일러라는 특성상 웹 UI, 실시간 실행 결과 표시, 코드 실행 보안, 배포 자동화가 모두 필요하다. 모든 기능을 직접 구현하면 개발 기간이 길어지고 안정성 검증 비용이 커지므로, 검증된 오픈소스를 조합하여 핵심 목표인 "컴파일러 학습 경험"에 개발 역량을 집중하였다.

React, Vite, TypeScript는 빠른 화면 개발과 타입 안정성을 동시에 제공하기 때문에 선택하였다. 특히 IDE 화면은 코드 에디터, 출력 콘솔, 그래프 뷰어, 문제 패널이 함께 동작하므로 컴포넌트 기반 구조가 적합했다.

Monaco Editor는 VS Code 기반 편집 경험을 웹에서 제공할 수 있어 온라인 IDE에 적합하다. 단순 textarea로 구현할 경우 코드 편집 UX가 부족하지만, Monaco를 사용하면 줄 번호, 테마, 언어 모드, editor API를 안정적으로 활용할 수 있다.

FastAPI와 Pydantic은 API 서버를 빠르게 구성하면서도 요청/응답 타입 검증을 명확히 할 수 있어 선택하였다. 컴파일 요청, 실행 요청, 문제 등록, 리더보드 점수 제출처럼 데이터 형식이 중요한 기능에서 오류를 조기에 차단할 수 있다.

Docker는 사용자 코드 실행이라는 고위험 기능을 격리하기 위해 선택하였다. 사용자 코드를 서버에서 직접 실행하면 파일 접근, 네트워크 접근, 무한 루프, 메모리 과다 사용 등 보안 문제가 발생할 수 있다. 본 프로젝트는 컨테이너 생성 시 네트워크 차단, 읽기 전용 파일 시스템, 메모리/CPU/PID 제한, capability 제거를 적용하여 실행 위험을 줄였다.

React Flow와 Dagre는 컴파일러 내부 구조를 시각화하기 위해 선택하였다. AST, SSA, IR, ASM은 텍스트만으로 이해하기 어렵기 때문에 그래프 형태로 보여주는 것이 교육적 효과가 크다. React Flow는 상호작용 가능한 그래프 UI를 제공하고, Dagre는 노드 위치를 자동 계산해 겹침을 줄여준다.

라이선스 측면에서도 대부분 MIT, Apache-2.0, BSD, ISC 계열로 상업적 사용과 수정·배포가 비교적 자유로운 오픈소스를 중심으로 선택하였다. 다만 B++ Compiler 저장소는 GitHub API 기준 라이선스가 감지되지 않아, 최종 제출·배포 전 원저작자 허가 또는 라이선스 명시 확인이 필요하다.

## 5. 오픈소스 적용 상세

| 오픈소스명 | 사용 위치(모듈/기능) | 적용 방식(사용/수정/확장) | 코드 설명 |
|---|---|---|---|
| React / React DOM | `frontend/src/main.tsx`, `frontend/src/app/` | 사용 | `createRoot`로 SPA를 렌더링하고, IDE·문제·리더보드·관리자 화면을 컴포넌트 단위로 구성 |
| Vite | `frontend/vite.config.ts`, `frontend/Dockerfile` | 사용/설정 확장 | 개발 서버와 production build를 담당하며, Docker build 단계에서 정적 파일을 생성 |
| TypeScript | `frontend/src/app/services/compilerApi.ts`, 컴포넌트 전반 | 사용 | 컴파일 요청/응답, AST/SSA/IR/ASM 타입을 정의하여 프론트엔드와 백엔드 계약을 명확화 |
| Monaco Editor | `frontend/src/app/components/CodeEditor.tsx` | 사용/확장 | B++ 언어 ID를 등록하고, 프로젝트 전용 `bpp-dark`, `bpp-light` 테마를 정의하여 웹 IDE 편집기로 활용 |
| Zustand | `frontend/src/app/store/compilerStore.ts` | 사용/확장 | 코드, 실행 상태, 컴파일 결과, 터미널 WebSocket, 자동저장, 테마를 하나의 store에서 관리 |
| React Router | `frontend/src/app/routes.ts`, `Layout.tsx` | 사용 | IDE, Challenges, Leaderboard, Admin 화면을 route 단위로 분리하고 challenge state 전달에 활용 |
| React Flow / @xyflow/react | `frontend/src/app/components/CompilerGraphViewer.tsx` | 사용/확장 | 백엔드에서 받은 AST/SSA 데이터를 React Flow의 node/edge 구조로 변환하여 시각화 |
| Dagre | `frontend/src/app/components/CompilerGraphViewer.tsx` | 사용/확장 | AST/SSA 노드 크기와 엣지를 기반으로 top-bottom 그래프 레이아웃을 자동 계산 |
| Lucide React | `frontend/src/app/components/`, `frontend/src/app/pages/` | 사용 | 실행, 정지, 저장, 그래프, 리더보드, 설정 등 주요 UI 동작을 아이콘으로 표현 |
| Tailwind CSS / Radix UI | `frontend/src/styles/`, `frontend/src/app/components/ui/` | 사용/확장 | 접근성 primitive 위에 프로젝트 스타일을 적용해 재사용 가능한 UI 컴포넌트 구성 |
| FastAPI | `backend/app/main.py`, `backend/app/api/routes/` | 사용/확장 | `/api/v1/compiler`, `/api/v1/problems`, `/health`, terminal route를 등록하고 CORS middleware 적용 |
| Pydantic | `backend/app/models/schemas.py` | 사용/확장 | `CompileRequest`, `CodeResponse`, `ProblemCreate`, `LeaderboardScoreCreate` 등 API 스키마 정의 |
| SQLAlchemy | `backend/app/core/database.py`, `backend/app/models/database.py` | 사용 | SQLite 기반 Problem, User, UserProblemScore 테이블 모델과 DB session 관리 |
| Docker SDK for Python | `backend/app/services/compiler.py` | 사용/확장 | 백엔드에서 샌드박스 컨테이너를 동적으로 생성하고, 실행 결과 stdout/stderr/exit code를 수집 |
| Docker / Ubuntu / GCC / OpenJDK / Node.js | `runtime/docker/Dockerfile`, `runtime/sandbox/run.sh` | 사용/설정 확장 | B++, Python, C, C++, Java, JavaScript별 compile/run 함수를 구성하여 다중 언어 실행 지원 |
| Nginx | `frontend/Dockerfile`, `frontend/nginx.conf`, `deploy/nginx/` | 사용/설정 확장 | Vite build 산출물을 정적 서빙하고 `/webcompiler/` 배포 경로에 맞춰 서비스 |
| GitHub Actions | `.github/workflows/deploy-webcompiler.yml` | 사용/확장 | CI 성공 후 checkout, SSH agent, 원격 저장소 동기화, 원격 deploy script 실행 자동화 |
| Vitest / Playwright / pytest | `frontend/src/**/*.test.tsx`, `frontend/e2e/`, `backend/tests/` | 사용 | 프론트 상태/라우팅, E2E 플로우, 백엔드 API 및 컴파일 서비스 회귀 테스트 |

## 6. 오픈소스 수정 및 확장 내용

본 프로젝트는 `node_modules`나 Python site-packages 내부의 오픈소스 원본 코드를 직접 수정하지 않았다. 대신 오픈소스가 제공하는 public API, 설정 파일, wrapper 코드를 활용하여 프로젝트 요구사항에 맞게 확장하였다. 이는 업스트림 업데이트와 라이선스 관리 측면에서 안전한 방식이다.

주요 확장 내용은 다음과 같다.

| 구분 | 수정·확장 내용 |
|---|---|
| Monaco Editor 확장 | 기본 언어 목록에 없는 B++를 `bpp` 언어 ID로 등록하고, 프로젝트 전용 다크/라이트 테마를 정의하였다. B++ 문법 전체를 새로 구현하지는 않았지만 C/C++ 계열 편집 경험을 제공하도록 editor language를 매핑하였다. |
| React Flow 확장 | 백엔드 컴파일 결과를 그대로 표시하지 않고 AST/SSA 전용 node, edge, custom node component로 변환하였다. 선택된 텍스트와 일치하는 노드를 highlight하여 코드와 그래프의 연결성을 높였다. |
| Dagre 레이아웃 확장 | AST/SSA 그래프의 노드 크기, rank separation, node separation을 조정하여 노드 겹침을 줄이고 top-bottom 흐름으로 배치하였다. |
| FastAPI 확장 | 기능별 router를 분리하고 `/api/v1/compiler`, `/api/v1/problems`, terminal route를 구성하였다. CORS 설정을 환경변수로 분리하여 로컬·배포 환경 모두 대응하였다. |
| Pydantic 확장 | snake_case와 camelCase 혼용 문제를 줄이기 위해 alias generator와 validation alias를 적용하였다. 프론트엔드 TypeScript 타입과 백엔드 Pydantic schema가 대응되도록 응답 변환 함수를 구현하였다. |
| Docker 실행 정책 확장 | 컨테이너 실행 시 `network_disabled=True`, `read_only=True`, `mem_limit`, `nano_cpus`, `pids_limit`, `ulimits`, `cap_drop=["ALL"]`, `security_opt=["no-new-privileges"]` 등을 적용하였다. 단순 실행이 아니라 온라인 저지/컴파일러 서비스에 맞춘 제한 실행 환경으로 확장한 점이 핵심이다. |
| Runtime script 확장 | B++, Python, C, C++, Java, JavaScript 언어별 compile/run 함수를 분기 처리하고, B++의 경우 AST/SSA/IR/ASM 시각화에 필요한 dump 기능을 제공하도록 실행 모드를 확장하였다. |
| 배포 자동화 확장 | GitHub Actions에서 CI 성공 후 원격 서버에 SSH로 접속하여 저장소 동기화와 배포 스크립트를 실행하도록 구성하였다. |

## 7. 라이선스 분석

| 오픈소스명 | 라이선스 유형 | 상업적 사용 가능 여부 | 주의사항 |
|---|---|---|---|
| React, React DOM | MIT | 가능 | 저작권 및 라이선스 고지 유지 필요 |
| Vite, Vitest | MIT | 가능 | 번들 결과물 배포 시 dependency license 고지 권장 |
| TypeScript | Apache-2.0 | 가능 | 라이선스 및 NOTICE 조건 확인 필요 |
| Monaco Editor | MIT | 가능 | Microsoft 저작권 고지 유지 필요 |
| React Router, Zustand, React Flow, Dagre, Recharts, Tailwind CSS | MIT | 가능 | 수정·배포 가능하나 라이선스 전문 보관 권장 |
| Lucide React | ISC | 가능 | MIT와 유사하게 자유로운 사용 가능, 고지 유지 필요 |
| Radix UI, clsx, tailwind-merge | MIT | 가능 | UI primitive 자체 수정 시 변경 내용 관리 필요 |
| class-variance-authority | Apache-2.0 | 가능 | Apache-2.0 고지 및 특허 조항 확인 필요 |
| Playwright | Apache-2.0 | 가능 | 테스트 도구로 사용하므로 배포물 포함 여부 확인 |
| FastAPI, Pydantic, SQLAlchemy | MIT | 가능 | 백엔드 배포 이미지에 라이선스 고지 포함 권장 |
| Uvicorn, HTTPX | BSD-3-Clause | 가능 | 저작권, 라이선스, 면책 조항 유지 필요 |
| Docker SDK / Docker Engine 계열 | Apache-2.0 | 가능 | Docker Desktop 사용 시 별도 약관이 적용될 수 있음. 서버에서는 Docker Engine/Moby 계열 라이선스 확인 필요 |
| Nginx | BSD-2-Clause 계열 | 가능 | Nginx 라이선스 고지 유지 필요 |
| Ubuntu base image 및 apt 패키지 | 패키지별 상이 | 대체로 가능 | 이미지 안에 GPL, LGPL, Apache, BSD 등 다양한 라이선스가 혼재하므로 배포 시 SBOM 또는 패키지 목록 관리 권장 |
| GCC/G++ | GPL 계열, 런타임 예외 포함 | 가능 | 컴파일러 도구로 사용하는 것은 일반적으로 가능하나, GCC 자체를 수정·배포할 경우 GPL 의무 검토 필요 |
| OpenJDK | GPL-2.0 with Classpath Exception | 가능 | JDK 자체 재배포 시 라이선스 고지 및 소스 제공 조건 검토 필요 |
| Node.js | MIT | 가능 | 런타임과 npm dependency license를 별도 관리해야 함 |
| B++ Compiler | 라이선스 미감지 | 불명확 | GitHub API 기준 license가 `NOASSERTION`으로 확인됨. 외부 저장소를 clone하여 빌드하므로 최종 배포 전 원저작자 허가 또는 명시 라이선스 확인이 필요함 |
| GitHub Actions actions/checkout, webfactory/ssh-agent | MIT 계열 | 가능 | 워크플로에서 사용하는 action의 버전 고정과 보안 업데이트 확인 필요 |

라이선스 관점에서 본 프로젝트의 가장 큰 장점은 핵심 웹 프레임워크와 UI 라이브러리 대부분이 MIT, Apache-2.0, BSD, ISC처럼 허용적 라이선스라는 점이다. 반면 가장 큰 리스크는 외부 B++ Compiler 저장소의 라이선스가 명확히 감지되지 않는다는 점이다. 캡스톤 시연·학습 목적 사용에는 문제가 없을 가능성이 높지만, 공개 배포 또는 상용화 단계에서는 라이선스 명시 확인이 반드시 선행되어야 한다.

## 8. 오픈소스 활용 중 문제 및 해결

### 문제 상황 1: 사용자 코드 실행에 따른 보안 위험

온라인 컴파일러는 사용자가 입력한 임의의 코드를 서버에서 실행해야 한다. 이때 코드를 서버 프로세스에서 직접 실행하면 파일 시스템 접근, 네트워크 접근, 무한 루프, 과도한 메모리 사용, 프로세스 폭증 등의 위험이 발생한다.

해결 방법:

Docker SDK for Python을 이용해 요청마다 별도 컨테이너를 생성하고, 실행 컨테이너에 엄격한 제한을 적용하였다. 네트워크를 비활성화하고, 루트 파일 시스템을 읽기 전용으로 설정했으며, `/tmp`만 tmpfs로 제공하였다. 또한 메모리, CPU, PID, 열린 파일 수를 제한하고 Linux capability를 모두 제거하여 실행 위험을 완화하였다.

### 문제 상황 2: 컴파일러 내부 구조 시각화의 가독성 문제

AST와 SSA는 노드와 엣지 수가 늘어나면 단순 JSON이나 텍스트 출력만으로 이해하기 어렵다. 초기 형태의 시각화는 노드가 겹치거나 흐름이 직관적으로 보이지 않을 가능성이 있었다.

해결 방법:

React Flow를 사용하여 그래프를 상호작용 가능하게 렌더링하고, Dagre를 결합해 노드 위치를 자동 계산하였다. AST와 SSA에 대해 별도 node type과 edge style을 정의하고, 선택 텍스트 기반 highlight 기능을 추가하여 코드와 그래프 사이의 대응 관계를 쉽게 확인할 수 있도록 개선하였다.

### 문제 상황 3: 프론트엔드와 백엔드의 데이터 표기 방식 차이

백엔드는 Python 관례상 `snake_case`를 사용하고, 프론트엔드는 TypeScript/JavaScript 관례상 `camelCase`를 사용한다. 이 차이를 방치하면 컴파일 결과의 `execution_time`, `node_count` 같은 필드가 화면에서 누락될 수 있다.

해결 방법:

백엔드에서는 Pydantic schema와 alias 설정을 사용하고, 프론트엔드에서는 `compilerApi.ts`에서 백엔드 응답을 프론트엔드 타입으로 변환하는 mapping 함수를 구현하였다. 이로써 API 계약을 유지하면서도 각 언어 생태계의 관례를 지킬 수 있었다.

### 문제 상황 4: 배포 경로와 로컬 개발 경로의 차이

로컬 개발에서는 루트 경로(`/`)를 사용하지만, 서버 배포에서는 `/webcompiler/` base path를 사용한다. base path 처리가 없으면 정적 파일, API, WebSocket 경로가 깨질 수 있다.

해결 방법:

Vite 환경변수와 Docker build argument를 통해 base path를 주입하고, Nginx 및 배포 스크립트에서 프론트엔드와 백엔드 포트, 경로를 분리하였다. GitHub Actions는 CI 성공 후 원격 서버에서 배포 스크립트를 실행하도록 구성하여 수동 배포 오류를 줄였다.

## 9. 오픈소스 활용 평가

### 장점

오픈소스를 적극적으로 활용한 결과, 짧은 캡스톤 개발 기간 안에 웹 IDE, 컴파일 API, 그래프 시각화, 문제 풀이, 리더보드, 컨테이너 샌드박스, 자동 배포까지 포함한 완성도 있는 서비스를 구현할 수 있었다. 특히 Monaco Editor, FastAPI, Docker, React Flow는 프로젝트의 핵심 기능을 직접적으로 가능하게 한 기술이다.

또한 대부분의 주요 라이브러리가 문서화와 커뮤니티가 잘 되어 있어 문제 해결 속도가 빨랐다. MIT, Apache-2.0, BSD, ISC 등 허용적 라이선스가 많아 학습·시연·확장 측면에서 부담이 적었다. TypeScript와 Pydantic을 함께 사용함으로써 프론트엔드와 백엔드 사이의 데이터 계약도 비교적 명확하게 유지할 수 있었다.

### 단점

오픈소스 의존성이 많아질수록 버전 충돌, 보안 업데이트, 라이선스 고지 관리가 필요하다. 특히 현재 Python `requirements.txt`에는 버전이 고정되어 있지 않아, 같은 코드라도 설치 시점에 따라 다른 버전이 설치될 수 있다. 이는 재현 가능한 빌드와 장기 유지보수 측면에서 단점이다.

또한 Docker 샌드박스를 사용하더라도 사용자 코드 실행은 본질적으로 보안 리스크가 크다. 현재 메모리, CPU, 네트워크, 파일 시스템 제한을 적용했지만, 운영 환경에서는 seccomp/AppArmor 정책, 이미지 취약점 스캔, 실행 로그 감사, 컨테이너 정리 정책을 추가로 강화할 필요가 있다.

B++ Compiler 외부 저장소의 라이선스가 명확하지 않은 점도 주의해야 한다. 프로젝트의 핵심 언어 컴파일 기능과 관련된 의존성이므로, 최종 제출 전 원저작자에게 사용 허가를 받거나 라이선스 파일이 추가되었는지 확인하는 것이 바람직하다.

## 10. 종합 결론

본 프로젝트는 오픈소스를 단순히 설치한 수준이 아니라, 각 오픈소스의 강점을 프로젝트 목적에 맞게 조합하고 확장하였다. React와 Monaco Editor는 웹 IDE 경험을 제공하고, FastAPI와 Pydantic은 안정적인 API 계약을 구성하며, Docker는 사용자 코드 실행을 격리하고, React Flow와 Dagre는 컴파일러 내부 구조를 교육적으로 시각화한다.

따라서 오픈소스 활용의 적절성, 기능 적용도, 확장성, 라이선스 인식 측면에서 캡스톤 프로젝트와의 연계성이 높다. 향후 개선점은 Python 의존성 버전 고정, SBOM 생성, B++ Compiler 라이선스 확인, 컨테이너 보안 정책 강화이다. 이 보완을 수행하면 학습용 캡스톤을 넘어 실제 운영 가능한 온라인 컴파일러 플랫폼으로 발전할 수 있다.

## 참고 자료 및 확인 근거

| 구분 | 근거 |
|---|---|
| 프로젝트 저장소 | https://github.com/2026CJUCapstone/project |
| B++ Compiler 저장소 | https://github.com/Creeper0809/Bpp |
| GitHub 라이선스 확인 방식 참고 | https://docs.github.com/en/rest/licenses/licenses |
| 라이선스 부재 시 주의사항 참고 | https://docs.github.com/github/creating-cloning-and-archiving-repositories/licensing-a-repository |
| 로컬 확인 파일 | `frontend/package-lock.json`, `frontend/package.json`, `backend/requirements.txt`, `backend/app/services/compiler.py`, `frontend/src/app/components/CodeEditor.tsx`, `frontend/src/app/components/CompilerGraphViewer.tsx`, `runtime/docker/Dockerfile`, `runtime/sandbox/run.sh`, `.github/workflows/deploy-webcompiler.yml` |
