# Extensions available to the AI Business Twin PostgreSQL database.
# pgvector is provisioned for the knowledge/vector layer. The application
# stores embeddings in a JSON-compatible column by default so the same code can
# use SQLite for local development; production can add a vector index.
CREATE EXTENSION IF NOT EXISTS vector;
