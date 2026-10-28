# ContextAI

ContextAI is a personal knowledge assistant. A user registers, uploads a document, and asks questions. Answers are grounded in that user's documents, citations point at the retrieved passages, and the conversation is still there after a refresh.

The web app is a Next.js frontend. The API, document worker, and database run separately, so a long embedding job is not tied to the Vercel process.

## What is included

- Session authentication, password reset tokens, and account deletion that removes the user's rows and stored files.
- Dashboard, chat with streamed responses, document upload, hybrid search, memories, tasks, tool confirmation, and a labelled evaluation run.
- PostgreSQL with pgvector. Keyword search and vector search are fused, and a later ranking step can only reorder chunks that were already retrieved.
- Document evidence, saved memory, and model suggestions stay distinct. Extracted tasks stay proposed until the user accepts them. A weekday such as Friday is stored as a label, not converted into a calendar date.
- Without `GOOGLE_API_KEY`, answers quote the retrieved evidence and say so. They do not pretend a generative model ran.

## Local setup

PostgreSQL is published on host port **5434** so it does not collide with other local databases.

```powershell
copy .env.example .env
docker compose up -d
cd apps\api
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd apps\web
npm install
npm run dev
```

Open the URL Next prints (usually `http://localhost:3000`). Register, then on Knowledge choose **Add the sample brief**, or upload `samples/project-brief.pdf`. When the document status is `completed`, ask a question in Assistant.

`WORKER_MODE=embedded` starts the job worker inside the API process. For more than one API instance, set `WORKER_MODE=external` and run:

```powershell
.\.venv\Scripts\python.exe -m app.workers.runner
```

## Tests

```powershell
cd apps\api
.\.venv\Scripts\python.exe -m pytest
```

Integration tests create `contextai_test` on the same Postgres and skip if it is unreachable. They use the hashing embedder so they do not download a model.

## Configuration

| Variable | Role |
| --- | --- |
| `DATABASE_URL` | Async SQLAlchemy URL. Local default uses port 5434. |
| `GOOGLE_API_KEY` | Optional. Enables Gemini streaming. Leave empty for extractive answers. |
| `EMBEDDING_PROVIDER` | `fastembed` (BAAI/bge-small-en-v1.5, 384 dimensions) or `hashing`. |
| `STORAGE_BACKEND` | `local` or `s3`. |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | Gmail address and app password. Verification and reset links are sent from `SMTP_FROM`. Leave the password empty to keep showing tokens locally. |
| `EXPOSE_DEV_TOKENS` | Local only. Returns email-verification and reset tokens in the API response when mail is not configured. |
| `NEXT_PUBLIC_API_URL` | API origin used by the browser. |

The vector column is fixed at 384 dimensions. Changing the embedding model requires a migration.

Cookies are `SameSite=Lax` for local split ports. A production frontend on another site needs `COOKIE_SAMESITE=none` and `COOKIE_SECURE=true`. Mutating `/api` requests must send `X-Requested-With: contextai`.

## Deployment

- Frontend: Vercel, with `NEXT_PUBLIC_API_URL` pointing at the API.
- API and worker: any host that can run Python, reach Postgres, and keep the process alive for background jobs.
- Database: PostgreSQL 16 with pgvector.
- Original files: the local disk in development, or S3-compatible storage in production.

## Honest limits

Evaluation numbers describe the fixed sample set and the current configuration. They are not a real-world guarantee. The hashing embedder is deterministic and is not a semantic model; if fastembed cannot load, the API falls back to it and says so in health. Cross-user resources return 404.

PDF text is extracted with pypdf. SQLAlchemy stays on the 2.0 line because 2.1 imports a native module that Windows Application Control can block.
