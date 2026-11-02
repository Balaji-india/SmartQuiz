---
description: P01 · Database schema, Alembic migrations and email/password JWT auth
---
Create the full Review 1 database schema with Alembic and add simple email/password authentication.

/context: CLAUDE.md, docs/SPEC.md section 1 (tables) and section 2 (/auth endpoints). P00 is done.
/structure: Sync SQLAlchemy 2 models in api/app/models/ for every table in SPEC section 1, using pgvector's `Vector(384)` type and `ARRAY(Integer)` for fact_idxs.
/details:
- First migration runs `CREATE EXTENSION IF NOT EXISTS vector`.
- HNSW cosine index on facts.embedding; unique (document_id, idx) on facts; index on questions.fingerprint.
- Auth: POST /auth/signup, /auth/login and GET /auth/me per SPEC; passwords hashed with argon2-cffi; JWT (HS256, JWT_SECRET, 7-day expiry); a `get_current_user` dependency for protected routes.
/constraints: Use sync SQLAlchemy. One migration file for all tables is fine. No feature logic yet.
/test: pytest against a test database (create `smartquiz_test` automatically): migration upgrade then downgrade; signup → login → protected `/auth/me` works; wrong password → 401.
/examples: `Invoke-RestMethod -Method Post -Uri http://localhost:8000/auth/signup -ContentType "application/json" -Body '{"email":"a@b.com","password":"secret12","name":"Test User"}'`

First show a short plan and wait for my "go". When finished: commit "feat: schema and auth", append a P01 entry to docs/STATUS.md, then tell me to run /compact.
