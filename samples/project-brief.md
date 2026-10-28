# ContextAI Project Brief

Specification code: SPEC-CTX-1842

## Summary

ContextAI is a personal knowledge assistant. People upload project documents and ask evidence-based questions. Answers should cite the material that supports them.

## Technical architecture

The web application uses Next.js and TypeScript. The API is Python and FastAPI. PostgreSQL stores accounts, documents, conversations, and tasks. Semantic search uses pgvector. Embeddings are 384-dimensional vectors. Original files are stored in object storage. Document processing runs in a background worker so the upload request can finish immediately.

## Outstanding work

- Complete API authentication before Friday.
- Add citation display to the chat transcript.
- Review the retrieval evaluation set.

## Decisions

Session-based authentication was chosen so the browser never stores the model API key. The model API key remains a server-side environment variable.

## Out of scope

This brief does not define a project budget, vendor pricing, or staffing cost.
