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

## Outlook.com·Hotmail OAuth2

Outlook.com과 Hotmail은 비밀번호 기반 SMTP 대신 Microsoft OAuth2를 사용한다. 이 저장소는 기존 비밀번호 SMTP와의 호환성을 유지하면서, `scripts/authorize_microsoft_smtp.py`가 만든 버전 지정 자격증명만 `SMTP_PASSWORD`에서 OAuth2로 인식한다. 임의 문자열이나 일반 비밀번호를 OAuth 토큰으로 추측하지 않는다.

Microsoft Entra에 개인 Microsoft 계정을 지원하는 public-client 앱을 등록하고 SMTP delegated scope를 승인한 뒤 운영 서버에서 다음 절차를 실행한다. `<client-id>`는 앱 등록의 Application (client) ID다.

```text
python3 scripts/authorize_microsoft_smtp.py \
  --client-id <client-id> \
  --account creeper0809@hotmail.com \
  --file /home/vulpo/webcompiler/.deploy/runtime-secrets.env
```

도구는 Microsoft의 로그인 주소와 일회용 코드만 표시한다. refresh/access token은 출력하지 않는다. 계정 승인이 끝나면 `smtp-mail.outlook.com:587`에 STARTTLS와 XOAUTH2로 실제 인증하고 NOOP까지 성공한 경우에만 배포 잠금 아래 비밀 파일을 원자 교체한다. 설정되는 발신 주소는 `creeper0809@hotmail.com`, 화면에 보이는 발신자 이름은 `CUHA`다.

앱 등록의 client ID와 사용자 계정 동의는 외부 운영 권한이므로 코드가 임의로 생성하거나 완료 처리하지 않는다. SMTP 검증 뒤에도 실제 재설정 메일 수신과 링크 사용 검증은 별도로 수행한다.
