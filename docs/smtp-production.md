# 운영 SMTP 설정과 검증

비밀번호 재설정 메일은 운영 서버의 `.deploy/runtime-secrets.env`에만 설정한다. 값은 GitHub Actions, 저장소, 배포 로그에 넣지 않는다.

필수 항목은 `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, `SMTP_STARTTLS`, `PASSWORD_RESET_BASE_URL`이다. 인증을 쓰면 `SMTP_USERNAME`과 `SMTP_PASSWORD`를 반드시 함께 설정한다. 인증 자격 증명이 있으면 검증된 STARTTLS를 끌 수 없다. 재설정 URL은 HTTPS의 `/reset-password` 페이지여야 한다.

```text
SMTP_HOST=<provider host>
SMTP_PORT=587
SMTP_USERNAME=<provider username>
SMTP_PASSWORD=<provider app password>
SMTP_FROM=<verified sender address>
SMTP_STARTTLS=true
PASSWORD_RESET_BASE_URL=https://cuha.cju.ac.kr/webcompiler/reset-password
```

배포는 비밀 파일의 권한과 형식을 검사하고, 후보 백엔드 이미지에서 DNS/TCP 연결, 인증서와 호스트 이름, STARTTLS, SMTP 인증, NOOP 응답을 확인한다. 이 검사는 메일을 보내지 않으며 서비스 점검 모드에 들어가기 전에 끝난다. 실제 수신 검증은 등록된 테스트 계정으로 재설정 요청을 한 뒤 다음 항목을 확인한다.

1. 받은 메일의 링크가 운영 `/webcompiler/reset-password`로 연결된다.
2. 토큰은 한 번만 사용할 수 있고 만료 후 거절된다.
3. 재설정 전 비밀번호와 기존 로그인 토큰은 거절된다.
4. 새 비밀번호로 로그인할 수 있다.

SMTP 공급자 자격 증명과 수신함 확인 없이 위 마지막 검사를 완료로 기록하지 않는다.
