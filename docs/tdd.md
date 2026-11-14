# 실제 업무 TDD 검증

## 단위와 안전 경계

첫 단위는 **실제 로그인 → 자기 회사 장비로 접수 → 저장 → 새로고침 후 조회 → 같은 회사/운영진 조회 → 다른 회사 차단**이다. 이후 분석·승인·부서 처리·종결을 같은 방식으로 확장한다.

화면을 가짜 API 응답으로 통과시키지 않는다. 외부 LLM·임베딩은 일반 테스트에서 호출하지 않는다. 이번 단위는 분석을 호출하지 않고 `접수됨`으로 저장한다.

**일반 TDD 회귀**에서는 실제 사용 DB나 코퍼스를 테스트에 직접 사용하지 않는다. 별도 승인된 현재 환경 인수 E2E는 아래의 명시적 opt-in 절차로만 실행한다. `scripts/test_isolated.py`가 `TEST_DATABASE_URL` 서버에 새 `rag_regression_<무작위>_test` DB를 만들고, 그 DB에서만 마이그레이션·합성 자료·검증을 수행한 뒤 삭제한다. 지정 계정에는 새 테스트 DB 생성 권한이 필요하다. 서비스 요청 fixture는 이 전용 DB명만 허용한다.

## 실행

프런트 의존성 및 빌드:

```sh
cd frontend
npm ci
npm test
npm run build
```

백엔드 전체 회귀(실제 PostgreSQL 통합 포함):

```sh
cd backend
python -m pip install -r requirements-dev.txt
python scripts/test_isolated.py tests -q
```

로컬 브라우저 E2E는 프런트 빌드 후 명시적으로 실행한다. 테스트가 임시 API 서버와 Vite preview를 빈 로컬 포트에 띄우고, 실제 세션·CSRF·API·격리 DB를 사용한다. 계정은 테스트 fixture에만 합성 자료로 생성되며 앱에 시연 계정을 심지 않는다.

```sh
# 설치된 Chromium이 없으면 frontend에서 npx playwright install chromium
cd backend
# POSIX 예시
PYTHONIOENCODING=utf-8 RUN_BROWSER_E2E=1 python scripts/test_isolated.py tests/test_service_requests_e2e.py -q
```

PowerShell에서는 실행 전 `$env:RUN_BROWSER_E2E='1'`, `$env:PYTHONIOENCODING='utf-8'`을 설정한다. 별도 설치된 Chromium을 쓸 경우 `PW_CHROMIUM_EXECUTABLE`을 실행 파일 경로로 지정한다. Node를 자동으로 찾지 못하면 `NODE_BINARY`를 지정한다. 종료 후 테스트용 환경변수를 해제한다.

`frontend/playwright.config.js`는 테스트 서버·합성 계정 정보가 없을 때 실제 서버로 자동 대체하지 않는다. `npm run test:e2e`는 위 Python harness가 제공한 환경에서 실행하는 Playwright 진입점이다. 임의의 사용 DB에 연결한 E2E는 수행하지 않는다.

## 현재 검증 범위

- `frontend/src/workflow.test.js`: 시연 상태 변경 없이 업무 조건·고객 상태 표시·빈 목록 검증
- `frontend/src/vite-config.test.js`: 개발/미리보기 프록시의 Host 보존
- `backend/tests/test_service_requests_api.py`: 실제 로그인·CSRF·입력 검증·번호 할당·영속성·회사 격리·운영진 조회
- `backend/tests/test_service_request_readiness.py`: 스키마 미적용 시 503, 가짜 데이터/자동 DDL 없음
- `frontend/e2e/service-requests.spec.js`: 실제 브라우저 접수·새로고침·동일 회사 공유·다른 회사 차단·운영진 조회, 오프라인 전송 실패 시 화면 유지, 미연결 조작 비활성화
- 기존 인증·AI·검색·적재·마이그레이션 테스트는 함께 회귀 검증

실제 사용 DB에 `012_service_requests`를 적용하거나 기존 고객사·장비를 이관하는 작업은 별도 승인과 대상 확인 후 수행한다. 위 격리 검증 명령은 배포/실제 데이터 이관 명령이 아니다.

## 승인된 현재 환경 인수 E2E

일반 회귀와 분리한 파일:

- `backend/scripts/test_live_intake.py`: 명시적 DB 승인, 실제 DB명 확인, 임시 타사 fixture 준비·정리
- `frontend/playwright.live.config.js`: localhost만 허용, 승인·계정 ID·장비 ID·자격정보 필수, 재시도 없음
- `frontend/e2e-live/service-requests.spec.js`: 실제 `user` 접수 → 새로고침 → `admin` 조회/접수 → 타사 접근 및 CSRF/Origin 차단 → 로그아웃
- `backend/tests/test_live_intake_runner.py`: 잘못된 DB·승인 누락·외부 URL을 연결 전에 거부하는 안전장치 테스트

현재 로컬 미리보기 주소는 `http://localhost:4173`이다. 인증/접수 DB는 앱과 동일하게 `RAG_DATABASE_URL`을 우선 사용한다. 이 환경에서는 그 대상의 실제 DB명이 **`service_poc_test`**다. 이름에 `_test`가 들어 있어도 현재 앱이 사용하는 DB이므로 임시 DB로 취급하지 않는다. `DATABASE_URL`의 `service_poc`에는 적용하지 않는다.

별도 승인으로 **012만** 적용했고, 기존 활성 고객사 1개를 재사용해 `user`를 연결했다. 기존 명부에 장비가 없으므로 이름이 `E2E 검증용 장비`, 시리얼이 `E2E-LIVE-USER-001`인 검증용 장비를 준비했다. 실제 실장비 정보가 아니며 앱 시작 시 자동 생성되는 시연 seed도 아니다. 비밀번호·역할은 바꾸지 않았다.

재실행은 승인된 현재 환경에서만 다음처럼 수행한다. 실행 중인 프런트/API가 필요하며 DB 마이그레이션·계정 생성·소속 변경은 자동 수행하지 않는다.

```sh
cd backend
# 자격정보는 셸 환경변수로만 제공하며 Git에 저장하지 않는다.
# LIVE_E2E_USER_PASSWORD, LIVE_E2E_ADMIN_PASSWORD를 먼저 설정한다.
# 필요하면 PW_CHROMIUM_EXECUTABLE과 NODE_BINARY도 지정한다.
python scripts/test_live_intake.py --allow-current-db service_poc_test --base-url http://localhost:4173
```

이 명령은 기존 계정·소속·명시된 검증용 장비가 준비됐는지 확인한 뒤, 실행마다 무작위 표식 `[LIVE-E2E:<uuid>]`와 임시 타사 고객사/장비를 만든다. API 응답 가로채기·인증 주입은 없다. 브라우저 로그인 응답의 계정 ID와 장비 ID도 DB 준비 단계에서 읽은 값과 대조한다.

실행 후 성공·실패에 관계없이 해당 무작위 표식과 두 계정 ID가 일치하는 테스트 요청만 정리하고 임시 타사 장비/고객사를 제거한다. 기존 요청 전체 삭제, DB drop/truncate, 시퀀스 초기화, 코퍼스 변경은 하지 않는다. 프로세스를 강제 종료하거나 정리에 실패하면 표식을 확인하고 해당 실행 자료만 별도로 점검한다. 기존 소속과 검증용 장비는 유지한다.

### 현재 환경 실행 결과

- 현재 DB·실제 두 계정으로 인수 E2E 통과
- 첫 실행 `CLM-001`/`CLM-002`를 DB에서 직접 대조: 작성 계정·회사·장비·`접수됨` 상태·서버 시각 일치
- 정식 재실행 harness에서도 `CLM-003`/`CLM-004` 생성 및 동일 검증 흐름 통과, 테스트 요청 2건과 임시 타사 자료 자동 정리
- 기존 코퍼스 행 수와 원래 계정 ID·비밀번호 해시·역할 유지 확인
- 테스트 요청을 정리했으므로 목록에 테스트 건이 남아 있지 않는 것이 정상이며, 시퀀스는 되돌리지 않음


## 요청 분석 단위

- `POST /api/v1/service-requests/{identity}/analysis`: 운영진(`admin`)·CSRF·same-origin만 허용, 본문 없음. 서버가 저장된 증상·장비·알람만 모델 입력으로 사용하고 연락처는 보내지 않는다.
- `접수됨 → 분석 중 → 검토 대기`. 실패하면 `접수됨`으로 돌아가 재시도할 수 있다. 서버 재시작으로 남은 실행은 `interrupted`로 정리한다.
- 모델 출력은 같은 실행에서 실제 조회한 매뉴얼 페이지·FSR만 인용할 수 있으며, 발췌문은 모델이 아니라 DB에서 가져온다. 근거 없는 `answered`·잘못된 부서/수준/근거 참조는 저장하지 않는다(`invalid_analysis`).
- 고객 응답에는 분석·부서 초안·실행 상태가 포함되지 않는다.
- 일반 회귀·격리 브라우저 E2E(`backend/tests/e2e_app.py`)는 모델 호출만 통제된 대역으로 바꾸고 인증·DB·UI는 실제로 쓴다. 실제 LLM·Qwen 검색은 위 승인된 현재 환경 E2E(`frontend/e2e-live`)의 두 번째 테스트에서만 호출한다(약 80초, 비용 발생).

## 검토·승인·부서 처리·고객 조작 단위

- 운영진 API: 부서·초안 수정(`PATCH /departments/{key}`), 담당자 지정, 메모·고객 답변, 승인, 반려, 재분석, 업무 지정·시작·완료, 종결. 고객 API: 정보 추가(`/replies`), 콜백, 종결 요청.
- 승인은 **서버에 저장된 현재 초안**으로만 업무를 만들며 클라이언트가 부서·행위자·시각을 보낼 수 없다. 요청 행을 `FOR UPDATE`로 잠가 동시 승인에서도 한 번만 성공한다.
- 승인 조건: 검토 가능 상태, 선택한 부서 1곳 이상, 선택 부서의 초안이 모두 비어 있지 않음. 업무는 `전달됨 → 진행 중 → 완료` 순서만 허용하고, 모든 업무가 완료되어야 종결할 수 있다.
- 근거 부족 분석은 `추가 정보 필요`가 되고, 고객 답변은 그 상태에서만 재분석을 시작한다. 재분석 실패·서버 재시작 시 이전 상태로 복원하며 이전 결과·검토 수정은 유지한다.
- 고객 응답은 서버가 고객용 상태(`접수됨/확인 중/정보 요청/처리 중/완료`)·고객용 이력 문구·공개 댓글·종결 메모·승인 이후 매뉴얼 제목만 내려준다. 내부 메모·반려 사유·분석·초안·업무·담당자는 포함하지 않는다.
- 테스트: `backend/tests/test_service_workflow_api.py`(권한·상태 전이·동시성·고객 투영), `frontend/src/actions.test.js`, 격리 브라우저 E2E `frontend/e2e/workflow.spec.js`(모델만 대역), 현재 환경 인수 E2E `frontend/e2e-live`(실제 LLM·검색 포함 승인→업무→종결).
- 초안 입력은 화면에서 잠시 뒤 또는 포커스를 잃을 때 저장하며, 화면 동작은 클릭 순서대로 서버에 전달해 승인이 항상 저장된 초안을 보게 한다.

## 회귀 테스트가 DB를 지우지 않게 하는 규칙

일부 테스트는 `TRUNCATE ... CASCADE`로 테이블을 비웁니다. 그래서 다음을 지킵니다.
- 실행은 `scripts/test_isolated.py`로만 합니다. 이 스크립트가 만든 `rag_regression_<hex>_test` 임시 DB만 테스트 대상입니다.
- `.env`의 `TEST_DATABASE_URL`이 앱이 쓰는 DB(예: `service_poc_test`)를 가리키면 `tests/conftest.py`가 이를 빈 값으로 바꿔 DB 테스트를 건너뜁니다. 이름이 `_test`로 끝난다는 이유만으로는 안전하지 않습니다.
- 값을 삭제하지 않고 **빈 문자열로 바꾸는** 이유: 앱 모듈이 import될 때 `load_dotenv(override=False)`를 호출해 삭제된 값을 `.env`에서 되살립니다.
- DB를 비우는 fixture는 한 번 더 `require_disposable_test_database`로 임시 DB가 아니면 실행 전에 거부합니다.
- `pytest`를 직접 실행해도 DB 테스트는 건너뜁니다. 검증: `tests/test_database_guard.py`.
