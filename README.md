# 서비스 접수 화면 목업 + 백엔드 매뉴얼 에이전트

React/Vite 화면과 FastAPI API를 하나의 이미지로 빌드합니다. FastAPI가 정적 화면과 `/api`를 8000 포트에서 제공합니다. **현재 mock 화면이 제품 범위의 기준**입니다: 공개 홈·고객센터·로그인, 고객 요청 목록·접수·상세, 운영진 대기열·분석·승인, 부서 업무 목록·상세·결과.

시연용 샘플 데이터·키워드 시나리오·자동 분석 타이머·프런트 전용 업무 reducer는 제거했습니다. 인증과 서비스 요청 접수·목록·상세는 실제 API/DB를 사용합니다. AI 분석·승인·부서 처리·메시지·첨부는 아직 미연결이며 화면에서 비활성화하거나 미연결 상태를 표시합니다. 기능 경계는 [화면 기준 개발 범위](docs/screen-scope.md)를 참고하세요.

실제 요청 기능에는 `012_service_requests` 마이그레이션과 계정의 고객사 소속·장비 데이터가 필요합니다. 앱 시작 시 적용하거나 샘플을 자동 생성하지 않습니다. 스키마가 없으면 `REQUESTS_NOT_READY`(503)를 반환합니다.

별도 승인 후 현재 로컬 앱의 `RAG_DATABASE_URL` 대상인 `service_poc_test`에 **012만 적용**하고, 기존 고객사를 재사용해 `user` 소속과 명시적인 **E2E 검증용 장비**를 연결했습니다. `admin`/`user` 실제 계정으로 로컬 브라우저 인수 E2E를 통과했으며 테스트 요청과 임시 타사 자료는 정리했습니다. 실제 장비 명부를 자동 이관하거나 가짜 실장비 정보를 넣은 것은 아닙니다. 일반 TDD 회귀는 계속 격리 DB에서 실행합니다.

## 통합 이미지 빌드 및 실행

```sh
docker build -t demo-app .
docker run --rm --network YOUR_DB_NETWORK --env-file backend/.env -p 8000:8000 demo-app
```

로그인과 에이전트 실행을 사용하려면 컨테이너에서 인증·RAG DB 호스트에 접근할 수 있어야 합니다. `/api/health`와 정적 파일 제공은 DB 연결 없이 실행됩니다. 로그인 상태 조회에는 DB 연결이 필요합니다. 앱 시작 시 스키마를 만들거나 변경하지 않습니다.

- 화면: http://localhost:8000/
- API 문서: http://localhost:8000/docs
- API 상태: http://localhost:8000/api/health

데이터베이스 스키마 변경은 명시적인 마이그레이션 CLI에서만 수행합니다. 웹 DB 진단·설치 API는 제공하지 않습니다. 정적 파일 경로는 `STATIC_DIR` 환경변수로 변경할 수 있습니다.

## 로컬 프런트엔드 개발

`frontend/`에서 `npm ci` 후 `npm run dev`를 실행할 수 있습니다. 이때 Vite의 `/api` 프록시 기본 대상은 `http://localhost:8000`이며 `VITE_API_PROXY_TARGET`으로 변경할 수 있습니다. 로컬 Compose 파일은 제공하지 않습니다.

## 마이그레이션 적용

앱은 RAG_DATABASE_URL(없으면 DATABASE_URL)을 사용합니다. 스키마는 앱 시작 시 자동으로 바뀌지 않고 명시적으로 적용합니다.

```sh
cd backend
python scripts/migrate.py --env-name RAG_DATABASE_URL --allow-non-test   # 앱이 실제로 쓰는 DB
```

--allow-non-test 없이는 RAG_DATABASE_URL·DATABASE_URL에 적용하지 않습니다. 적용 전에 어떤 DB인지(SELECT current_database())와 미적용 버전을 확인하세요. .env에서 두 URL이 서로 다른 DB를 가리킬 수 있습니다.

## 서비스 요청 TDD

- 실제 접수 API: `GET /api/v1/service-requests/context`, `POST /api/v1/service-requests`, `GET /api/v1/service-requests`, `GET /api/v1/service-requests/{identity}`
- 고객은 서버에 등록된 자기 회사의 장비·요청만 접근하고, 운영진은 전체 요청을 조회합니다. 회사·계정·접수 번호·시각을 클라이언트가 지정할 수 없습니다.
- 최소 회사·소속·장비 테이블은 접수 데이터 기반이며 관리 CRUD 화면/API를 다시 추가하지 않습니다.
- 상세 검증 방법: [TDD 검증 지침](docs/tdd.md). 실제 로그인·API·DB를 거치는 로컬 Playwright E2E가 포함됩니다.

## 백엔드 매뉴얼 에이전트 (요청 분석 연동 전)

에이전트는 PostgreSQL + pgvector + `pg_trgm`을 사용합니다. 변환 페이지 텍스트를 키워드/벡터로 검색하고, 필요한 페이지를 원본 PDF에서 온디맨드 렌더링해 도구 결과로 돌려줍니다. LLM 및 Gemini 임베딩 프록시 값은 `backend/.env`에 두며, 키 이름은 `backend/.env.example`에 있습니다. 비밀값은 커밋하지 마세요.

```sh
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
# backend/.env에 DATABASE_URL, TEST_DATABASE_URL, RAG_DATABASE_URL(로컬은 테스트 DB), LLM 및 Gemini 설정
.venv/Scripts/python scripts/migrate.py --env-name TEST_DATABASE_URL
.venv/Scripts/python scripts/test_isolated.py  # 임시 DB에서 테스트하고 삭제; DB 생성 권한 필요
.venv/Scripts/python scripts/ingest_corpus.py  # backend/data/test_corpus/가 로컬에 있을 때
.venv/Scripts/python scripts/index_embeddings.py --activate  # Gemini에 실제 색인 요청
.venv/Scripts/python scripts/run_agent.py "윤활 펌프 알람 2023 원인과 확인 방법"
```

`migrate.py`와 `ingest_corpus.py`는 기본으로 `_test` 접미사가 있는 `TEST_DATABASE_URL`만 허용합니다. `DATABASE_URL` 대상 작업은 명시적인 `--allow-non-test` 옵션이 필요합니다. 에이전트는 `RAG_DATABASE_URL`을 우선 사용하므로 로컬에서는 이를 테스트 DB로 설정하고, 지정하지 않으면 `DATABASE_URL`을 사용합니다. 앱 시작은 DB DDL을 실행하지 않습니다. 인덱싱은 100개 이하 배치로 재개 가능하며, `--activate`는 모든 임베딩이 준비됐을 때만 config를 활성화합니다. 단위 테스트는 실제 LLM/Gemini를 호출하지 않습니다.

### 로그인과 에이전트 실행 API

공개 회원가입은 없습니다. 계정은 CLI로만 만들며 비밀번호는 인자가 아니라 숨김 프롬프트로 입력합니다.

```sh
.venv/Scripts/python scripts/migrate.py --env-name TEST_DATABASE_URL   # 003_auth, 004_agent_runs 포함
.venv/Scripts/python scripts/create_user.py --login-id alice            # --role admin 도 가능
```

현재 화면의 운영진은 `admin`, 발급 고객 계정은 `user`입니다. 기존 `customer` 계정의 로그인 호환성은 유지하며, 고객 역할은 에이전트 API에 접근할 수 없습니다.

로그인하면 서버 세션을 `HttpOnly` 쿠키로 유지하고(7일, DB에는 토큰 해시만 저장), 쓰기 요청은 `X-CSRF-Token` 헤더와 같은 출처 검사를 통과해야 합니다. 로그인 실패는 접속지 10분 5회·아이디 10분 10회로 제한됩니다. HTTPS로 공개할 때는 `APP_COOKIE_SECURE=1`을 설정하세요. 사용자당 동시에 실행할 수 있는 에이전트는 1개이며 실행 기록·이미지는 소유자만 조회합니다. 서버를 재시작하면 실행 중이던 기록은 `interrupted`로 표시됩니다(단일 프로세스 기준).

| 엔드포인트 | 설명 |
|---|---|
| `GET /api/v1/auth/me` | 로그인 상태와 CSRF 토큰 |
| `POST /api/v1/auth/login`, `/logout` | 로그인·로그아웃 |
| `POST /api/v1/agent/runs` | 질문 실행 시작(202, 백그라운드·비스트리밍) |
| `GET /api/v1/agent/runs`, `/runs/{id}` | 내 실행 목록·상세(답변·출처·도구·이미지) |
| `GET /api/v1/agent/runs/{id}/assets/{asset_id}` | 에이전트가 연 원본 페이지 이미지 |

위 에이전트 API는 분석 기반 재사용을 위해 유지한 비스트리밍 실행·결과·이미지 API이며, 현재 mock 화면에서 호출하지 않습니다. 이전 독립 채팅 UI와 AI SDK 스트리밍 어댑터는 제거했습니다. 오류는 고정 코드로만 전달합니다. PydanticAI 버전은 2.64.0을 유지합니다.

회귀 테스트는 `scripts/test_isolated.py`를 권장합니다. `pytest tests`를 직접 실행하면 `TEST_DATABASE_URL`의 RAG 자료를 초기화하므로 코퍼스/임베딩을 보관한 DB를 대상으로 실행하지 마세요. 격리 실행기는 별도 임시 DB를 사용하고 테스트 출력의 접속 문자열·비밀번호·키를 마스킹합니다.

최종 결과의 `status`는 `answered` 또는 `insufficient_evidence`입니다. `answered`는 조회된 페이지 인용이 필수이고, 근거 부족 결과에는 관련 없는 인용을 강제하지 않습니다. 이미지 목적지는 CommonMark 파서로 검증하며 현재 실행의 `asset:<id>`만 허용합니다. Raw HTML은 지원하지 않으며 코드 블록/인라인 코드의 예제는 그대로 둘 수 있습니다.

핵심 경로는 구현됐고 실제 임베딩 단건(3072차원), LLM 식별자 조회→원본 이미지 열람→인용 스모크를 확인했습니다. `.env`를 채우는 것만으로 색인이 생성되지는 않습니다. 전체 코퍼스 색인·골든셋 검색 품질 평가·성능 검증·검색 경로 병렬화는 별도 작업입니다.

테스트 매뉴얼 원본/변환 산출물은 로컬 `backend/data/test_corpus/`에만 두며 gitignore 대상입니다. 문서가 저장소에 포함되지 않으므로 새 체크아웃에서는 별도 코퍼스를 준비해야 DB 적재/검색을 실행할 수 있습니다. `md.zip`과 `pdf.zip`은 선택 샘플을 추출한 뒤 삭제했습니다.
