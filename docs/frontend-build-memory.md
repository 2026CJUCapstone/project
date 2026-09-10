# 프런트엔드 Monaco 빌드 메모리

이 문서는 Monaco의 현재 local AMD distribution 방식과 제한된 검증 기록을
구분해 남긴다. 전체 Compose 수명주기와 운영 배포의 성공 기록은 아니다.

실제 Linux 검사 `31244`는 별도 `app-amd-A1q9vO`에서 **1039.180초 통과**로 종료했다.
소스 archive `8c0d22c17763ff9d5e76d48a27291b15e389c4d8cb9399c7b8cf565e9dbf6d3e`
와 packaging delta `c0327ccbf05c69298cea893ee0f5ff2f12c720dc522abce97d2086d065e0d131`
를 hash 검증했다. 앞선 `31938`은 Nginx 설정을 archive에서 누락해 28.522초에
실패했으며 npm/build에 도달하지 않았다. 누락을 보완한 현재 실행의 실제 RUN에
2GiB/no-extra-swap·1CPU·512PID 제한이 적용됨을 확인했다. **실제 frontend와 backend
이미지 build/export/load이 합계85.0초에 통과했다.** B++ sandbox 빌드도922.2초에
통과해 세 실제 이미지 검사와 전용 자원 정리가 완료됐다. 전용 빌더·이미지·캐시
volume의 부재와 unit 비활성도 별도로 확인했다. 운영 배포는 하지 않았다.

## 현재 방식: 전체 local AMD distribution

frontend/build/localMonacoAssets.ts는 lock된 monaco-editor 0.55.1의 min/vs
전체와 LICENSE를 byte-for-byte snapshot한다. 파일명·길이·내용의 SHA-256으로
assets/monaco-&lt;SHA&gt;/vs directory를 만들고 production build에는 그대로
emit한다. development server도 같은 메모리 snapshot의 allowlisted path만
GET/HEAD로 제공한다. path miss와 raw/encoded traversal은 404, 허용하지 않는
method는 405로 끝나며 임의 filesystem path를 열지 않는다.

virtual:local-monaco는 현재 Vite base 아래의 same-origin vs URL을
@monaco-editor/react loader에 전달한다. 외부 CDN이나 별도 ESM Monaco
instance는 사용하지 않는다. slash root와 /webcompiler/ 모두
content-addressed directory를 쓰므로 다른 Monaco snapshot이 immutable cache에서
섞이지 않는다.

AMD editor.main은 native MonacoEnvironment worker factory를 직접 설치한다.
따라서 localMonaco.ts는 이를 수동 getWorker로 덮어쓰지 않는다. native factory는
blob bootstrap에서 local importScripts와 vscode-worker-ready handshake를
사용한다. top-level Worker URL은 blob일 수 있으므로 filename을 page worker
event에서 요구하지 않는다. browser 회귀는 context request에서 실제 local
ts.worker-*.js 요청을 확인하고 모든 HTTP/importScripts 요청이 same-origin이며
CDN이 없음을 확인한다.

전체 min/vs를 제공하므로 기존 editor contribution과 언어 서비스를 제거하지
않는다. editor, CSS, HTML, JSON, TypeScript worker 다섯 개가 정확히 남고,
JavaScript diagnostic/completion과 C, C++, Python, Java, JavaScript, B++의
template/tokenization을 유지하는 것이 기능 계약이다.

Microsoft Monaco Editor MIT 고지는 frontend/public/licenses/monaco-editor.txt에
포함했다. 현재 파일 SHA-256은
33e4ff1a06ef62ba21788ea162564ee8165269a24a9ce6ef301837447eab0ac6이다.
92280b87c07417bb390f25df1382893766852ae8ae734c95f82c40b00f3a8bb0는 notice
파일 hash가 아니라 함께 기록된 license TAR hash다.

## 최신 로컬 검증

Node 24.21.0에서 현재 AMD variant를 V8 old-space 1024 MiB로 실행한 21128은
**13.042초 통과, 최대 RSS 831,008 KiB**였다. 이후 사용하지 않는 worker factory를
제거한 동일 variant build는 **5.965초 통과, 최대 RSS 778,612 KiB**였다.

- Vite plugin 실제 3개 검증은 emit된 모든 Monaco byte parity, 정확히 다섯
  worker만 존재하고 Monaco min/vs source를 ESM transform하지 않음, root와
  /webcompiler/ development HTTP의 GET/HEAD/path miss/405 처리를 확인했다.
- snapshot 관련 7개 회귀는 독립 검토를 거쳤다.
- 최종 frontend unit test 70개는 **2.52초**, 별도 typecheck도 통과했다. 이 둘에는
  V8 old-space나 Linux cgroup build limit을 적용하지 않았다.
- build output을 Edge로 제공한 최신 93017은 **10개 통과, 23.3초**였다. root와
  /webcompiler/ 각각에서 desktop/mobile
  실제 편집, local worker/CDN 차단, JavaScript diagnostic/completion, 여섯 언어
  template의 tokenization을 확인했다. 추가로 script-src self/unsafe-eval 금지를
  실제 enforce한 문서에서도 편집기와 JS 오류 표시가 동작했다. 전체 사이트의
  운영 CSP 검증이나 실제 API 채점을 뜻하지 않는다.

그 전 browser run 31504의 두 실패는 blob worker인데 page worker URL이
ts.worker-*.js여야 한다고 가정한 오래된 assertion 때문이었다. 실제
diagnostic/completion과 여섯 template 검사는 그 실행에서도 통과했다. assertion을
context-level local worker request로 고친 24301은 4개/9.5초, CSP 추가 69250은
5개/11.5초였고, 현재는 두 base를 검사한 93017이 최종 결과다.

최소 frontend 재현 순서는 다음과 같다.

~~~sh
cd frontend
npm ci
VITE_APP_BASE_PATH=/ NODE_OPTIONS=--max-old-space-size=1024 npm run build -- --outDir dist-profile-root
VITE_APP_BASE_PATH=/webcompiler/ NODE_OPTIONS=--max-old-space-size=1024 npm run build -- --outDir dist-profile-subpath
npx playwright test --config=playwright.monaco-build.config.ts
npm run test:run
npm run typecheck
~~~

## 이전 URL-worker 시도와 Linux 이미지 실패

아래는 현재 AMD 방식의 증거가 아닌 역사 기록이다. 이전 ESM ?worker imports는
1536 MiB old-space에서 약 38.8초 후 OOM이었다. 첫 local prebuilt-worker URL
variant는 같은 조건에서 22.89초/최대 RSS 1,960,644 KiB, /webcompiler/에서는
20.287초/1,951,900 KiB였지만 1024 MiB에서는 약 6.5초 후 OOM이었다.

그 첫 variant output에는 byte-identical prebuilt worker 다섯 copy와 full Monaco
workerManager의 new URL ESM fallback worker 네 개가 함께 남았다. 이 중복과 ESM
parsing 경로 때문에 현재 full AMD snapshot 방식으로 교체했다. 이전 source input
SHA-256은 4fa5f28dc0a27c3ece1579c56568c3fd4d32c89fc4295d8eef888df0eb2d814f다.

이전 actual server 3-image build 26217은 fresh app-workers-vxymLf checkout에서
**164.606초, exit 1**로 끝났다. backend full build의 pip check/export/load은
통과했지만 frontend는 npm ci의 500 packages/0 vulnerabilities 뒤 1536 MiB build
약 70초에서 SIGKILL/ResourceExhausted: cannot allocate memory로 실패했다. B++
build는 시작하지 못했고 fixture cleanup은 완료됐다. 이 실패는 보존하지만 현재
AMD variant의 Linux image 결과로 해석하지 않는다.

## 남은 조건

- 세 실제 이미지 빌드는 기존2GiB조건에서 통과했다. 전체 이미지 취약점 검사와
  실제 서비스/큐/채점/managed LB 통합 검증은 별도 조건이다.
- build budget을 3 GiB로 올리지 않았고, 운영 배포나 main push도 하지 않았다.
- 전체 B++ compiler build, managed Compose 최초 기동·전환·rollback/drain,
  부하·외부 서비스 및 전체 browser workflow 검증은 별도 작업이다.
