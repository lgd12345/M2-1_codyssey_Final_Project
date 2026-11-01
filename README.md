# 서비스 접수 화면 목업 + 백엔드 매뉴얼 에이전트

React/Vite 화면과 FastAPI API를 하나의 이미지로 빌드합니다. FastAPI가 정적 화면과 `/api`를 8000 포트에서 제공합니다. 프런트는 **로그인 + 에이전트 동작 확인용 임시 화면**입니다(질문 실행, 답변·출처·원본 이미지, 도구 호출 순서와 검색 상태 표시). 최종 목적은 고객 민원을 에이전트에 전달해 해결 초안을 만드는 것이며, 그 구조가 되면 이 화면은 제거합니다.

## 통합 이미지 빌드 및 실행

```sh
docker build -t demo-app .
docker run --rm --network YOUR_DB_NETWORK --env-file backend/.env -p 8000:8000 demo-app
```

컨테이너에서 DB 호스트에 접근할 수 있는 Docker 네트워크에 연결해야 `/api/db-status`가 동작합니다. DB에 연결되지 않아도 웹 화면과 `/api/health`는 실행됩니다. 앱 시작 시 스키마를 만들거나 변경하지 않습니다.

- 화면: http://localhost:8000/
- API 문서: http://localhost:8000/docs
- API 상태: http://localhost:8000/api/health
- PostgreSQL 및 pgvector 상태: http://localhost:8000/api/db-status

데이터베이스 스키마 변경은 명시적인 마이그레이션 CLI에서만 수행합니다. `/api/db-status`는 PostgreSQL의 `vector` 확장 존재 여부만 확인합니다. 정적 파일 경로는 `STATIC_DIR` 환경변수로 변경할 수 있습니다.

## 로컬 프런트엔드 개발

`frontend/`에서 `npm ci` 후 `npm run dev`를 실행할 수 있습니다. 이때 Vite의 `/api` 프록시 기본 대상은 `http://localhost:8000`이며 `VITE_API_PROXY_TARGET`으로 변경할 수 있습니다. 로컬 Compose 파일은 제공하지 않습니다.

## 백엔드 매뉴얼 에이전트 (UI 미포함)

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

로그인하면 서버 세션을 `HttpOnly` 쿠키로 유지하고(7일, DB에는 토큰 해시만 저장), 쓰기 요청은 `X-CSRF-Token` 헤더와 같은 출처 검사를 통과해야 합니다. 로그인 실패는 접속지 10분 5회·아이디 10분 10회로 제한됩니다. HTTPS로 공개할 때는 `APP_COOKIE_SECURE=1`을 설정하세요. 사용자당 동시에 실행할 수 있는 에이전트는 1개이며 실행 기록·이미지는 소유자만 조회합니다. 서버를 재시작하면 실행 중이던 기록은 `interrupted`로 표시됩니다(단일 프로세스 기준).

| 엔드포인트 | 설명 |
|---|---|
| `GET /api/v1/auth/me` | 로그인 상태와 CSRF 토큰 |
| `POST /api/v1/auth/login`, `/logout` | 로그인·로그아웃 |
| `POST /api/v1/agent/stream` | 대화형 실행(AI SDK 스트림). 도구 호출이 실시간으로 나오고, 최종 답변은 서버 검증 후 `GET /runs/{id}`로 확인. 응답 헤더 `X-Run-Id` |
| `POST /api/v1/agent/runs` | 질문 실행 시작(202, 백그라운드·비스트리밍) |
| `GET /api/v1/agent/runs`, `/runs/{id}` | 내 실행 목록·상세(답변·출처·도구·이미지) |
| `GET /api/v1/agent/runs/{id}/assets/{asset_id}` | 에이전트가 연 원본 페이지 이미지 |

프런트 임시 화면은 `@ai-sdk/react`(`useChat`)로 대화하며, 스트림의 `final_result`는 검증 전 값이라 화면에 쓰지 않습니다. 오류는 고정 코드로만 전달하고, 연결이 끊기면 실행 기록을 `interrupted`로 마감합니다. PydanticAI는 UI 어댑터 보안 수정이 포함된 2.64.0으로 고정했습니다.

회귀 테스트는 `scripts/test_isolated.py`를 권장합니다. `pytest tests`를 직접 실행하면 `TEST_DATABASE_URL`의 RAG 자료를 초기화하므로 코퍼스/임베딩을 보관한 DB를 대상으로 실행하지 마세요. 격리 실행기는 별도 임시 DB를 사용하고 테스트 출력의 접속 문자열·비밀번호·키를 마스킹합니다.

최종 결과의 `status`는 `answered` 또는 `insufficient_evidence`입니다. `answered`는 조회된 페이지 인용이 필수이고, 근거 부족 결과에는 관련 없는 인용을 강제하지 않습니다. 이미지 목적지는 CommonMark 파서로 검증하며 현재 실행의 `asset:<id>`만 허용합니다. Raw HTML은 지원하지 않으며 코드 블록/인라인 코드의 예제는 그대로 둘 수 있습니다.

핵심 경로는 구현됐고 실제 임베딩 단건(3072차원), LLM 식별자 조회→원본 이미지 열람→인용 스모크를 확인했습니다. `.env`를 채우는 것만으로 색인이 생성되지는 않습니다. 전체 코퍼스 색인·골든셋 검색 품질 평가·성능 검증·검색 경로 병렬화는 별도 작업입니다.

테스트 매뉴얼 원본/변환 산출물은 로컬 `backend/data/test_corpus/`에만 두며 gitignore 대상입니다. 문서가 저장소에 포함되지 않으므로 새 체크아웃에서는 별도 코퍼스를 준비해야 DB 적재/검색을 실행할 수 있습니다. `md.zip`과 `pdf.zip`은 선택 샘플을 추출한 뒤 삭제했습니다.
