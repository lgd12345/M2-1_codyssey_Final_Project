# 서비스 접수 화면 목업

React/Vite 화면과 FastAPI API를 하나의 이미지로 빌드합니다. FastAPI가 빌드된 정적 화면과 `/api`를 8000 포트에서 함께 제공합니다. 화면은 여전히 **정적 목업**이며 접수 분석, RAG 검색, 메일 발송 기능은 구현되지 않았습니다.

## 통합 이미지 빌드 및 실행

```sh
docker build -t demo-app .
docker run --rm --network YOUR_DB_NETWORK -p 8000:8000 \
  -e DATABASE_URL='postgresql://user:password@db:5432/database' demo-app
```

컨테이너에서 `db` 호스트에 접근할 수 있는 Docker 네트워크에 연결해야 DB 초기화와 `/api/db-status`가 동작합니다. DB에 연결되지 않아도 웹 화면과 `/api/health`는 실행됩니다.

- 화면: http://localhost:8000/
- API 문서: http://localhost:8000/docs
- API 상태: http://localhost:8000/api/health
- DB 및 pgvector 상태: http://localhost:8000/api/db-status

앱 시작 시 `vector` 확장, `knowledge_documents` 테이블, HNSW 인덱스를 멱등하게 생성합니다. DB 연결 또는 생성에 실패하면 로그를 남기고 백그라운드에서 재시도하며 웹 서버는 계속 실행됩니다. DB 계정에는 확장·테이블·인덱스 생성 권한이 필요합니다. 임베딩 차원 1536은 추후 사용할 모델에 맞춰 조정해야 합니다.

정적 파일 경로는 `STATIC_DIR` 환경변수로 변경할 수 있습니다. 디렉터리가 없으면 정적 파일 마운트를 건너뛰므로 백엔드 단독 실행도 가능합니다.

## 로컬 프런트엔드 개발

`frontend/`에서 `npm ci` 후 `npm run dev`를 실행할 수 있습니다. 이때 Vite의 `/api` 프록시 기본 대상은 `http://localhost:8000`이며 `VITE_API_PROXY_TARGET`으로 변경할 수 있습니다. 로컬 Compose 파일은 제공하지 않습니다.
