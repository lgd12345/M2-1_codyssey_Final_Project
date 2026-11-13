# 기존 Docker 배포에서 고객 기능 적용하기

이 절차는 main 갱신 → 서버 pull → Docker 재빌드를 유지한다. 웹 시작·이미지 빌드는 DB migration이나 비밀 설정 주입을 실행하지 않는다. **명령은 실제 DB가 연결된 서버의 승인된 관리 환경에서만 실행한다.** 현재 저장소에는 서버 접속/배포 스크립트가 없으므로 컨테이너명·DB명·네트워크·설정 파일 경로를 추측해 넣지 않는다. 웹 운영진 로그인은 서버 터미널이나 DB 관리 권한을 대신하지 않는다.

2026-11-12 실제 사전 점검에서는 업무 DB 연결/read-only는 성공했으나 신규 `claim_access` 스키마/이력이 없고 고객사·가입 요청 플래그와 `APP_COOKIE_SECURE=1`이 꺼져 있었다. 이 관측은 [운영진 사전 점검](./OPERATOR_DB_PREFLIGHT.md)의 제한된 결과이며 전체 DB 권한/복구 검증이 아니다. 준비가 끝난 항목부터 확인하고 적용 결과를 기록한다.

## 1. 실제 대상과 적용 전 상태

- 기존 관리자가 서버의 현재 기동 명령, 실제 이미지 ID, 내부 DB 연결, 비밀 설정 주입·재시작 경로를 확인한다. 과거 로컬 Compose를 운영 설정으로 복원하지 않는다.
- 실제 DB명·버전, 기존 인증 테이블/제약, 소유자와 별도 migration 역할, 런타임 DML/열/시퀀스 권한을 확인한다. 현재 `DATABASE_URL`의 역할에 DDL 권한이 있다고 추정하지 않는다. 업무/인증 대상이 다르면 현재 고객 가입의 동일 DSN 조건을 충족할 수 없으므로 중단한다.
- 검증 릴리스와 001~004 파일 체크섬을 고정한다. 이미 적용한 SQL 파일을 고쳐 재실행하지 않는다. 기존 로그인·매뉴얼·문서 접근의 기준 상태를 확인한다.
- 기존 서버 설정에서 `COMPANY_ADMIN_ENABLED=0`, `CUSTOMER_ACCESS_ENABLED=0`, `CUSTOMER_ACCESS_RELEASE_APPROVED=0`, `CUSTOMER_REGISTRATION_ENABLED=0`을 유지한다. 이미 활성화된 환경의 복구라면 신규 쓰기/선점/발송 중지와 진행 중 작업 정리를 별도로 확인한다.

## 2. 백업과 격리 복원 확인

서버의 실제 버전에 맞는 공식 PostgreSQL 클라이언트와 접근이 제한된 백업 저장소를 사용한다. `PGHOST`·`PGPORT`·`PGUSER`·`PGDATABASE`·`PGPASSFILE` 등은 관리 환경에서 검증한 대상으로 주입한다. 비밀번호/DSN을 명령 인수·Git·터미널 출력에 넣지 않는다. POSIX 암호 파일은 0600, Windows는 사용자 전용 ACL을 확인한다. 백업에는 비밀번호 해시·세션·개인정보가 있으므로 별도 접근/암호화·보관/파기 정책을 적용한다. custom 형식 자체는 암호화가 아니다.

다음은 **관리자가 실제 값으로 지정할 템플릿**이며 자동 실행 스크립트가 아니다. `MORRONO_BACKUP_ARCHIVE`는 새 비공개 백업 파일의 절대 경로, `MORRONO_RESTORE_DB`는 원본과 다른 새 빈 검증 DB명이다. 원본 대상은 검증한 `PGDATABASE`이며 복원 대상은 `template0`로 새로 준비하고 필요한 역할/확장을 확인한다. 두 DB명과 실제 서버를 대조한 뒤 실행한다.

```sh
pg_dump --no-password --format=custom --file "$MORRONO_BACKUP_ARCHIVE"
pg_restore --list "$MORRONO_BACKUP_ARCHIVE"
pg_restore --no-password --single-transaction --exit-on-error --dbname "$MORRONO_RESTORE_DB" "$MORRONO_BACKUP_ARCHIVE"
```

종료 코드·경고, 원본/백업 대상과 시각·크기·해시·보호/보관 위치를 기록한다. 목록 열람만으로 복원 성공을 판단하지 않는다. 전체 복원 후 기존 로그인/권한과 업무 자료·제약·인덱스·시퀀스·확장·런타임 접근을 검증한다. 역할·테이블스페이스는 단일 DB `pg_dump`에 포함되지 않으므로 별도 전역 객체/권한 복구 계획이 필요하다. 매뉴얼 PDF·자산 파일·서버 환경 설정·SMTP/AI 키도 DB dump만으로 복구되지 않는다. 확장 바이너리·역할과 외부 자료가 준비되지 않은 복원은 완료가 아니다.

`pg_dump`는 자신보다 새로운 메이저 서버를 dump할 수 없다. 같은 서버 메이저의 도구를 우선 검증하고 다른 버전/확장 조합은 별도 검증한다. `--single-transaction`은 복원 중 오류 시 부분 적용을 막지만 대규모 DB의 잠금/용량·실제 소요 시간은 별도로 검증한다. 근거: [pg_dump 공식 문서](https://www.postgresql.org/docs/17/app-pgdump.html), [pg_restore 공식 문서](https://www.postgresql.org/docs/17/app-pgrestore.html), [암호 파일](https://www.postgresql.org/docs/17/libpq-pgpass.html).

## 3. 기존 명시적 migration 적용

다음 Python 명령은 `backend` 또는 기존 앱 컨테이너의 `/app`에서 실행한다. 서버 관리자가 주입한 `CUSTOMER_ACCESS_MIGRATION_DATABASE_URL`과 `COMPANY_ADMIN_MIGRATION_DATABASE_URL`을 사용하며 앱 DSN으로 자동 대체하지 않는다. `MORRONO_EXPECTED_DATABASE`는 앞서 확인한 정확한 대상 DB명이다. 호스트에서 환경변수를 설정했다고 기존 컨테이너에 자동 전달되는 것은 아니므로 실제 명령 실행 환경의 주입을 확인한다.

```sh
# 읽기 전용 확인: 대상 불일치 시 중단. 구조/권한 전체 검사를 대신하지 않는다.
python -m app.customer_access.manage --expect-database "$MORRONO_EXPECTED_DATABASE"
python -m app.company_admin.manage --expect-database "$MORRONO_EXPECTED_DATABASE"

# 별도 승인된 관리 환경: 기본 구조 + 고객 역할/이메일 제약(001/002/003).
python -m app.customer_access.manage --apply --expect-database "$MORRONO_EXPECTED_DATABASE" --with-customer-role --with-customer-email

# 같은 대상: 고객사/설비 관리 구조(001 확인 + 004).
python -m app.company_admin.manage --apply --expect-database "$MORRONO_EXPECTED_DATABASE"
```

명령은 각각 트랜잭션·동일 advisory lock·기존 이력 체크섬을 사용한다. **두 명령 전체가 하나의 트랜잭션인 것은 아니다.** 두 번째 실패 시 먼저 적용된 001/002/003은 남을 수 있으므로 플래그를 계속 0으로 두고 원인을 확인한다. 같은 파일 재실행은 이미 일치한 이력을 건너뛰며 알 수 없는 기존 인증 제약·대상 불일치·체크섬 차이는 중단한다. 실패를 피하려고 제약/잠금을 제거하거나 이력을 임의 변경하지 않는다.

적용 후 서버의 새 연결로 001~004 일치, 필수 실제 테이블과 열/제약/인덱스, 런타임에 필요한 DML/열/시퀀스 권한, 기존 로그인/매뉴얼을 확인한다. 사전 점검의 `matched`만으로 이 전체 검사를 대체하지 않는다. 일상 런타임에 migration 이력 쓰기/DDL 권한을 상시 추가하지 않는다. [실제 시험에서 확인한 최소 권한](./POSTGRES_CUSTOMER_ACCESS_TESTS.md)도 참고한다.

이 절차는 schema만 적용한다. 전체 CSV 1,455개 고객사를 자동 적재하거나 실제 고객/운영진 계정을 발급하지 않는다. 테스트용 회사 3개·가입 1/미가입 2는 로컬 합성 검증 자료이며 실제 명부/메일로 자동 승격하지 않는다.

## 4. 설정과 기능별 활성화

먼저 기존 설정 주입 경로에서 `APP_COOKIE_SECURE=1`을 제공하고 HTTPS 로그인·세션·동일 출처/CSRF를 확인한다. HTTP 로컬 시험과 운영 HTTPS를 혼동하지 않는다. 실제 운영 명부와 권한 검증 후 `COMPANY_ADMIN_ENABLED=1`로 고객사 관리만 별도로 열 수 있으며 SMTP·공개 가입을 함께 열 필요는 없다. 운영진 CRUD/감사·낡은 편집/중복 차단, 고객/비로그인 차단과 기존 매뉴얼을 확인한다.

공개 고객 기능은 다음 준비 후 순차적으로 연다.

1. [공유 빈 양식](./customer-access.env.example)과 [Gmail 안내](./GMAIL_SMTP.md)에 따라 실제 SMTP·32자 이상 별도 인증 비밀값을 서버의 비밀 설정으로 주입한다. 로컬 `private-data/gmail-smtp.env`는 Git/Docker 이미지에 넣지 않는다. 검증된 발신 계정과 사용자 승인 수신함 한 곳으로 **서버에서** TLS 인증·소량 발송·실제 도착을 확인한다. 로컬 성공/SMTP 수락만으로 서버 배달 완료를 선언하지 않는다.
2. 실제 운영자/문의·철회 경로, 외부 처리, 보유기간과 실행 가능한 삭제/철회·백업 반영 절차를 확정한다. 공개 고지와 정책 JSON의 version/purpose/items/retention/recipients/contact/refusal을 일치시킨다. 초안·빈 문의처·미구현 삭제 보장을 정책으로 채우지 않는다. 실제 파일을 컨테이너의 확정된 경로에서 읽게 하고 `CUSTOMER_ACCESS_POLICY_FILE`을 지정한다.
3. 명시적인 운영 승인 후 `CUSTOMER_ACCESS_ENABLED=1`, `CUSTOMER_ACCESS_RELEASE_APPROVED=1`, 필요 시 `CUSTOMER_REGISTRATION_ENABLED=1`을 주입한다. 기존 기동 방식으로 적용하고 `/access/status`·실제 가입/비회원 경로를 확인한다. 다른 인증/업무 DSN 설정이면 가입은 닫힌다.
4. 승인된 소량의 실제 명부/수신함으로 등록 코드/이메일 오류, 이메일 소유 인증, 중복 계정 차단, 고객 소속/운영진 권한 분리, 비회원 문의 세션 격리를 확인한다. 부하 시험이나 재시도 때문에 실메일을 반복 발송하지 않는다.

## 5. 실패와 복구

실패 시 해당 기능 플래그를 0으로 두고 신규 쓰기/발송을 닫는다. migration 한 명령의 실패는 해당 트랜잭션이 롤백되는지 확인한다. 코드 장애만으로 DB 전체를 과거 백업으로 되돌리지 않는다. 기존 추가 구조와 호환되는 검증 코드/이미지로 복귀하고 상태·대상·이력을 보전한다.

DB 복원이 필요하면 새 쓰기·실행자·실메일을 먼저 중지하고 현재 DB/발송·불명 이력을 보전한다. 백업 이후의 계정·접수·명부 변경·철회/삭제·외부 발송은 백업에 없다. 원본과 다른 새 DB에서 먼저 복원·대조하고 복구 책임자가 누락 자료/발송/세션·철회 처리와 재개 조건을 확정한다. 복원으로 사라진 성공 발송 기록 때문에 메일을 자동 재발송하지 않는다. 이 문서의 일반 복원 명령에는 기존 DB를 지우는 `--clean`/`--create`를 넣지 않았다.

## 6. 검증 근거의 한계

[백업·복원 시험](./tests/test_customer_access_backup.py)은 새 로컬 PostgreSQL 17.11과 합성 자료만 사용한다. 적용 전 인증 구조의 로그인/세션 복원, 적용 후 모든 인증·고객 테이블 행/시퀀스 일치, 가입 소속/비회원 문의/설비 재요청·감사 시퀀스, 복원 실패의 부분 적용 차단을 실제 도구로 검증한다. 원본 DB는 덮어쓰지 않으며 백업 이후 자료가 복원본에 없는 것도 시험한다.

실제 운영 DB 버전·전체 RAG/pgvector/외부 자산·전역 역할·네트워크·권한·백업 보관/암호화·RTO/RPO·SMTP·정책 운영은 이 시험으로 검증되지 않는다. 서버 관리 실행 경로와 해당 조건이 확인되기 전에는 위 명령을 실행한 것으로 기록하지 않는다.
