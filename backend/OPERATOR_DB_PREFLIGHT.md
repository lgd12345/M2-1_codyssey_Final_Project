# 운영진 DB 사전 점검

기존 운영진(`user`, `admin`) 세션으로 `GET /api/v1/companies/readiness`를 호출한다. 고객은 403, 비로그인은 401이며 응답은 `no-store, private`다. 기존 `/api/v1/admin/db-inspection`의 관리자 권한 조건은 변경하지 않는다. 공개 문서/OpenAPI와 고객 화면에는 이 진단을 추가하지 않는다.

이 API는 기능 플래그가 꺼져 있어도 `DATABASE_URL`에 설정된 업무 DB를 **읽기 전용 트랜잭션**으로 검사한다. 연결 제한 3초, SQL 제한 2초, 잠금 대기 제한 500ms를 사용하고 서버가 `transaction_read_only=on`을 확인한 뒤 고정된 메타데이터만 조회한다. 시작 시 실행하지 않으며 입력 SQL·대상 DSN·마이그레이션 실행 기능은 없다. 업무 행·사용자 행을 조회하지 않고 DB/서버/역할 이름·주소·키·체크섬 원문·예외 원문을 반환하거나 기록하지 않는다.

| 필드 | 해석 |
|---|---|
| `database.connection` | `ok`: 연결 성공. `not_configured`: 업무 DB 설정 없음. `failed`: 연결 실패. |
| `database.read_only` | `true`일 때만 DB의 읽기 전용 설정이 확인됨. `false`는 미확인. |
| `database.schema` | `present`/`missing`은 카탈로그에서 `claim_access` 존재 여부를 확인함. `unverified`는 확인 못 함. |
| `database.required_tables` | 고정된 9개 필수 관계의 존재·일반/파티션 테이블 종류만 확인. `missing`/`unsupported_relation`/`unverified`를 구분. |
| `database.auth_table` | `public_visible`은 현재 업무 연결에서 `public.app_user`가 실제 테이블이며 인증 SQL의 `app_user`로 해석됨. 다른 인증 연결의 테이블 검증은 아님. |
| `database.ledger` | migration 이력의 `missing`/`readable`/`unreadable`/`unverified`. 뷰·외부 테이블·RLS가 적용된 이력은 조회하지 않음. |
| `database.migrations` | `001`~`004`의 이력 누락(`missing`), 현재 배포 파일 체크섬 일치(`matched`), 불일치(`mismatch`), 확인 불가(`unverified`). 이력 누락이 과거 SQL 미실행을 증명하지는 않음. |
| `auth_configuration` | `same_connection_settings`는 현재 회원가입 코드가 요구하는 공백 제거 후 DSN 문자열 일치 조건. `different_connection_settings`는 문자열이 다름. 물리 DB 동일/분리 판정이 아님. 설정 누락도 구분. |
| `feature_flags` | 현재 요청 플래그의 참/거짓일 뿐 실제 기능 사용 가능 여부나 운영 승인 상태가 아님. 기존 `/companies/status`, `/access/status`를 유지함. |

오류는 확인된 사실만 남기고 미검사 항목을 `unverified`로 유지한다. 권한 부족이나 시간 초과를 “스키마 없음”으로 바꾸지 않는다. 실제 활성화는 별도 판단이다. 모든 값이 정상이어도 열·제약·인덱스의 전체 변경 여부, 런타임 DML 권한, 기존 데이터, 백업/복구, 서버 SMTP, 개인정보 정책·삭제 운영을 증명하지 않는다. `write_checks_performed`는 항상 `false`다. 실제 적용에는 기존 명시적 관리 명령과 대상/권한/복구 검증이 필요하다.

검증은 `pytest --noconftest tests/test_company_readiness.py tests/test_db_inspection.py tests/test_db_metadata.py tests/test_company_registry.py -q`로 실행한다. 실제 PostgreSQL의 읽기 전용 강제·이력 불일치·관계 누락·이력 뷰 거절·권한 오류 구분은 [격리 DB 시험](./POSTGRES_CUSTOMER_ACCESS_TESTS.md)을 따른다. 기존 애플리케이션 DB를 테스트 대상으로 사용하지 않는다.
