# 서비스 접수 화면 목업

React/Vite 프런트엔드, FastAPI 백엔드, PostgreSQL + pgvector 개발 환경입니다. 현재 프런트 화면은 **정적 목업**이며 접수 분석, RAG 검색, 메일 발송 기능은 구현되지 않았습니다.

## Docker Compose로 실행

```sh
docker compose up --build
```

- 목업 화면: http://localhost:5173
- API 문서: http://localhost:8000/docs
- API 상태: http://localhost:8000/api/health
- DB 및 pgvector 상태: http://localhost:8000/api/db-status

포트를 바꾸거나 DB 비밀번호를 지정하려면 `.env.example`을 `.env`로 복사한 뒤 값을 수정하세요. 제공된 기본 비밀번호는 로컬 개발용입니다.

## 구성

- `frontend/`: React + Vite 목업. `/api` 요청은 Vite 프록시를 통해 FastAPI로 전달할 수 있습니다.
- `backend/`: FastAPI 골격과 상태 확인 엔드포인트.
- `db/init.sql`: 첫 DB 생성 시 `vector` 확장과 향후 RAG 문서 저장에 쓸 테이블을 만듭니다. 임베딩 차원 1536은 임시 값입니다.
- `compose.yaml`: 프런트엔드, 백엔드, pgvector 포함 PostgreSQL을 함께 실행합니다.

DB 초기화 SQL은 **빈 데이터 볼륨을 처음 만들 때만** 실행됩니다. 현재 문서 임베딩 생성이나 벡터 검색 API는 없습니다.

## 사용 이미지

- 프런트엔드: [Docker 공식 Node 이미지](https://hub.docker.com/_/node) `node:22-alpine`
- 백엔드: [Docker 공식 Python 이미지](https://hub.docker.com/_/python) `python:3.12-slim`
- DB: [pgvector 프로젝트 제공 이미지](https://github.com/pgvector/pgvector#docker) `pgvector/pgvector:0.8.7-pg17-bookworm` (PostgreSQL 17 + pgvector)
