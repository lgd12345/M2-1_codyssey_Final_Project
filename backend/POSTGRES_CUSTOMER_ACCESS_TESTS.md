# 고객 계정·고객사 관리의 실제 PostgreSQL 검증

## 검증 범위

`tests/test_customer_access_postgres.py`는 메모리 대체 저장소 대신 실제 PostgreSQL과 현재 관리 명령·저장소 코드를 사용한다. 기존 인증 migration `003_auth.sql`을 새 DB에 적용한 뒤 고객 계정 `001/002/003`과 고객사 관리 `004`를 시험한다. 새 DB만 사용하며 운영 DB, 기존 사용자 자료, 실제 SMTP/AI와 연결하지 않는다. 실제 운영 DB의 버전·권한·기존 제약·RAG 확장·백업 복구 검증을 대체하지 않는다.

시험은 읽기 전용 관리/대상 DB 오입력 차단, migration 최초 적용·재실행, 기존 운영진 비밀번호/역할/로그인 보존, 알 수 없는 기존 제약 시 전체 DDL 롤백, 체크섬 불일치 차단, 이메일 기반 가입과 명부 집계, 동시 가입 중복 방지, 소속 저장 실패 시 고아 계정 방지, 비회원 문의의 재전송/세션 격리/철회, 설비 등록 재전송과 과거 버전 덮어쓰기 차단을 다룬다.

2026-11-12에는 [운영진 사전 점검](./OPERATOR_DB_PREFLIGHT.md) 시험을 추가했다. 실제 읽기 전용 트랜잭션에서 DDL 거절, 없는 스키마 확인 후 불변, 필수 테이블 누락·이력 체크섬 불일치, 이력 뷰 조회 거절을 검증한다. 최소 권한 역할 시험에서도 이력 조회 권한 부족과 RLS 적용을 스키마 없음으로 오판하지 않는지 확인한다. 원래 11개를 포함해 총 14개이며 과거 엔진 검증 건수와 구분한다.

별도 런타임 역할은 `NOSUPERUSER NOCREATEDB NOCREATEROLE`로 만들고 필요한 DML·열·시퀀스 권한만 부여한다. 이 역할로 가입·로그인·등록 연락처 추가·비회원 문의가 동작하고, 테이블 생성/삭제 및 migration 이력 변경이 거절되는 것을 확인한다. 실제 운영 역할의 권한을 변경하는 테스트는 아니다.

## 재현 방법

기존 애플리케이션 DB가 없는 **새 로컬 검증 전용 PostgreSQL 클러스터**를 준비한다. Windows에서는 [PostgreSQL 공식 페이지가 안내하는 EDB ZIP](https://www.postgresql.org/download/windows/)을 사용할 수 있다. 전역 설치·Windows 서비스·Docker 배포 구성 변경은 필요하지 않다. 2026-11-11 검증 엔진은 EDB PostgreSQL 17.11-5 Windows ZIP의 PostgreSQL 17.11이며 **11개 통과·실패 0·건너뜀 0**을 확인했다. Windows ZIP의 initdb는 한글 경로에서 인코딩 오류가 발생해 실행 파일과 데이터는 영문 임시 경로에 두고, 한국어 프로젝트 경로의 Python 코드는 그대로 사용했다.

검증 전용 클러스터에만 새 관리용 DB를 만들고 다음 표식을 지정한다. **기존 운영/개발 DB에 표식을 붙여 재사용하지 않는다.** 클러스터 관리자는 테스트가 새 DB와 임시 역할을 만들고 정리할 수 있는 검증 전용 관리자여야 한다.

```sql
CREATE DATABASE morrono_customer_access_test_admin TEMPLATE template0;
COMMENT ON DATABASE morrono_customer_access_test_admin
    IS 'morrono-disposable-customer-access-verification-v1';
```

`CUSTOMER_ACCESS_TEST_ADMIN_DSN`에 이 새 관리용 DB의 DSN을 비공개 환경변수로 주입한다. 호스트는 `127.0.0.1` 또는 `::1`이어야 한다. 코드가 관리용 DB의 표식을 읽어 확인한 뒤, 각 테스트마다 `claim_access_verify_<UUID>_test`라는 **새 DB**를 생성한다. 그 UUID DB와 직접 생성한 임시 역할만 정리하고 기존 애플리케이션 스키마를 초기화하지 않는다. 애플리케이션 런타임이나 공유 설정 양식에 실제 DSN을 커밋하지 않는다.

아래 명령은 `backend`에서 실행한다. 기존 RAG 통합 테스트의 DB 초기화 fixture를 불러오지 않도록 `--noconftest`가 필요하다. `TEST_DATABASE_URL`은 이 시험의 설정 변수가 아니다. 전용 환경변수가 없으면 테스트는 건너뛰므로 **skip을 실제 DB 시험 통과로 기록하지 않는다.** Windows 인코딩은 필요하면 `python -X utf8`로 지정한다.

```text
python -m pytest --noconftest tests/test_customer_access_postgres.py -q
```

## 운영 권한 확인 시 주의할 실제 요구

`Work.guest()`는 문의 재전송을 직렬화하기 위해 `claim_access.guest_session` 행을 `SELECT ... FOR UPDATE`로 잠근다. SELECT/INSERT만 있으면 세션 생성 후 문의 저장에서 `InsufficientPrivilege`가 발생한다. PostgreSQL은 이러한 조회 잠금에도 대상 테이블의 최소 한 열에 UPDATE 권한을 요구한다. [PostgreSQL 17 SELECT 문서](https://www.postgresql.org/docs/17/sql-select.html)

이 시험에서는 `UPDATE(expires_at)` 한 열을 추가해 정상 문의와 스키마 변경 차단을 함께 검증한다. 권한 때문에 조회 잠금을 제거하지 않는다. 기존 운영 역할에 이미 더 넓은 UPDATE가 있다면 이 추가 부여가 필요하다고 단정하지 않는다. 실제 권한 조사 후 판단하며 이 문서가 GRANT를 자동 실행하지 않는다.

그 밖에도 인증번호 만료 정리에 challenge DELETE, 로그인 실패 제한 정리에 app_login_failure DELETE, 인증/고객사 변경에 필요한 DML, identity 열을 쓰는 시퀀스 USAGE가 필요하다. schema_version에는 조회만 허용하고 DDL/이력 쓰기는 별도 관리 역할이 담당한다. 전체 기존 매뉴얼 SQL의 권한까지 이 시험의 부여 예시로 대체하지 않는다.

검증용 서버는 종료하고 일회용 임시 실행 폴더를 확인해 정리했다. 공식 ZIP의 출처·측정 SHA-256·시험 JUnit 결과와 종료 기록은 별도 로컬 검증 기록에 남긴다. 측정 해시를 공급자가 공개한 해시와 독립 대조한 것으로 표현하지 않는다. 실제 운영 DB migration·권한 변경·메일 활성화·main 자동배포는 이 시험에서 수행하지 않는다.
