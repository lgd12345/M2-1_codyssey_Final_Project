# Google SMTP 발신 설정

2026-11-11 사용자 요청으로 Resend 대신 Gmail SMTP를 사용한다. 기존 aiosmtplib와 HTTPS/인증/DB/자동배포 구조를 유지하며 새 의존성을 추가하지 않는다. 발신자는 인증한 Google 계정 이메일로 제한한다. 임의 도메인이나 미검증 별칭을 From에 넣지 않는다.

## Google 계정에서 할 일

1. 발신용 Google 계정으로 [보안 설정](https://myaccount.google.com/security)에 접속해 2단계 인증을 켠다.
2. [앱 비밀번호](https://myaccount.google.com/apppasswords)에서 `MORRONO 메일 발송` 등의 이름으로 앱 비밀번호를 만든다.
3. 발급된 16자리 앱 비밀번호를 비공개 설정에 저장한다. 일반 로그인 비밀번호·백업 코드·일회용 로그인 코드를 대신 쓰지 않는다. 앱 비밀번호를 채팅·Git·스크린샷·명령 인수에 넣지 않는다.

앱 비밀번호 항목이 안 보이면 Google 공식 안내에 따라 보안 키 전용 2단계 인증, 조직 계정 정책, 고급 보호 설정 여부를 확인한다. 보안 기능을 임의로 해제하지 않는다. Google 계정 비밀번호를 변경하면 앱 비밀번호가 취소되므로 새로 발급해 교체해야 한다. 가능한 경우 서비스 전용 계정을 사용한다.

## 서버의 비공개 환경설정

| 변수 | 값 |
|---|---|
| `CUSTOMER_SMTP_USERNAME` | 발신 Google 계정의 전체 이메일 주소 |
| `CUSTOMER_SMTP_PASSWORD` | 해당 계정에서 발급한 16자리 앱 비밀번호 |
| `CUSTOMER_MAIL_FROM` | 생략 또는 위 계정과 동일한 주소 |

앱 비밀번호 표시용 ASCII 공백은 코드가 제거한다. 줄바꿈·탭·16자 이외 값은 거절한다. 형식 검사만으로 앱 비밀번호의 진위가 확인되는 것은 아니다. 서버 주소는 `smtp.gmail.com`, 접속은 TLS 465이며 서버 인증서 검증을 유지한다. 현재 구현은 Google OAuth·Workspace SMTP relay·별칭 발신을 제공하지 않는다.

[gmail-smtp.env.example](./gmail-smtp.env.example)은 위 세 변수만 담은 **GitHub 공유용 빈 양식**이다. 참여자는 이 파일을 `backend/private-data/gmail-smtp.env`로 복사한 뒤 자신의 비공개 설정을 입력한다. `private-data/`는 Git에서 제외되지만 양식은 버전 관리한다. [customer-access.env.example](./customer-access.env.example)은 기능 플래그·DB 관리·정책 파일 등 전체 설정의 빈 양식이다. 두 예시에 실제 자격 증명을 넣어 커밋하지 않는다.

로컬 비공개 파일을 작성하는 것과 실제 서버 컨테이너 환경에 주입하는 것은 별개다. 현재 Dockerfile은 해당 환경 파일을 이미지로 복사하지 않으며 변경하지 않는다. 기존 서버의 환경변수/비밀 설정 방식으로 주입하고, 기존 재시작/재빌드 절차를 따른다. GitHub main 푸시만으로 로컬 비밀값이 서버에 전달되지 않는다.

이 단계에서는 `CUSTOMER_ACCESS_ENABLED`, `CUSTOMER_ACCESS_RELEASE_APPROVED`, `CUSTOMER_REGISTRATION_ENABLED`를 켜지 않는다. 실제 DB 스키마·권한·회사 명부·개인정보 고지 및 삭제 운영을 검증한 뒤 기능별로 활성화한다.

## 검증과 장애 처리

- 단위/API 테스트는 가짜 SMTP를 사용해 호스트·계정·TLS·인증서 검증과 실패 시 코드 무효/재시도 없음 동작을 확인한다. 실제 Google 인증이나 메일 수신을 증명하지 않는다.
- 실제 배포 서버에서 발신 계정 인증과 지정 수신함 한 곳으로의 소량 발송을 확인하고, 수신자가 실제 수신함/스팸함과 발신 주소를 확인한다. SMTP 수락은 최종 수신 완료와 구분한다. 인증 실패·전송 실패 시 비밀번호나 SMTP 응답 원문을 공개 API/로그에 내보내지 않는다.
- Gmail SMTP는 공급자 idempotency key를 제공하는 경로로 사용하지 않는다. 애플리케이션의 요청 제한·인증번호 상태 관리를 유지하며 전송 결과가 불명확해도 자동 재발송하지 않는다. 사용자가 다시 요청하면 이전 코드는 무효화된다.
- 개인 Gmail은 발송량 제한과 스팸 판정의 영향을 받는다. 운영 발송량이 늘면 전용 메일 서비스 또는 조직용 계정 정책을 검토한다. 비밀번호 방식보다 Google OAuth를 권장하는 계정 보안 방침도 고려해야 한다. 현재는 사용자가 선택한 앱 비밀번호 방식으로 범위를 제한한다.

## 공식 근거

- [Google 계정: 앱 비밀번호로 로그인](https://support.google.com/accounts/answer/185833?hl=ko)
- [Google 개발자 문서: Gmail SMTP 주소·TLS 및 발송 제한](https://developers.google.com/workspace/gmail/imap/imap-smtp)
- [Google Workspace: 앱에서 Gmail SMTP 사용](https://knowledge.workspace.google.com/admin/gmail/send-email-from-a-printer-scanner-or-app?hl=en)
