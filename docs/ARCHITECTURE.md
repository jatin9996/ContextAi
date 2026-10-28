# Architecture

ContextAI splits the product into a Next.js UI and a FastAPI service. Vercel can host the UI. The API process owns authentication, retrieval, and the document worker.

```text
Browser
  |  cookie session + X-Requested-With
  v
Next.js  ----HTTP---->  FastAPI
                           |-- PostgreSQL + pgvector
                           |-- local disk or S3
                           \-- embedded or external worker
```

## Ownership

Every private query filters by the session user. A missing or foreign resource returns 404. Sessions store a SHA-256 hash of an opaque token. The model API key never reaches the browser.

## Documents

Upload validates the extension, size, and file signature, then writes the bytes to `{user_id}/{document_id}/original`. A Postgres job queue (`FOR UPDATE SKIP LOCKED`) moves the document through `uploaded → queued → processing → completed`, or `failed`. Reprocessing deletes the previous chunks and inserts the new ones in one transaction. Deleting a document removes its chunks, vectors, and stored file.

Text is split into chunks, embedded at 384 dimensions, and stored with a generated full-text vector. The default embedder is `BAAI/bge-small-en-v1.5`. If it cannot load, the service switches to a deterministic hashing embedder and reports that in health. Hashing is not semantic: abstention then requires lexical overlap.

## Answers

Retrieval combines cosine distance and keyword search with reciprocal rank fusion. The model, when configured, sees evidence and memories inside fences and must cite `[S#]` or `[M#]`. Unknown markers are stripped. If the documents do not support the question, the answer says they do not establish it and returns no citations. A streaming response that is interrupted is stored as `incomplete` or `failed`, not as a successful answer.

## Memory, tasks, and tools

Memories have a source (`user`, `document`, `model_suggestion`) and a status. Retrieval uses active memories only. The model cannot mark a memory active or a task open. Tool calls are validated against a registry. `update_task` waits for a user confirmation recorded on `tool_operations`. Idempotency keys stop a retried create from inserting a second row.

## Evaluation

`contextai-sample-v1` is seeded from code and scored against `samples/project-brief.md`. A run records recall@5, precision@5, citation support, abstention, and workflow checks. The stored disclaimer says those figures describe that set, not a production guarantee.

## Deletion

Account deletion is immediate. Database rows cascade. The audit row keeps a hash of the email and nulls the user id. Stored files are removed after the database commit.
