from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from app.models import Base

TABLES = {
    "users",
    "documents",
    "sections",
    "facts",
    "quizzes",
    "questions",
    "attempts",
    "fact_coverage",
    "generation_log",
}


def _has_vector(conn) -> bool:
    return conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).first() is not None


def test_upgrade_creates_schema_and_downgrade_removes_it(alembic_cfg, test_engine):
    command.upgrade(alembic_cfg, "head")
    try:
        inspector = inspect(test_engine)
        assert TABLES <= set(inspector.get_table_names())
        with test_engine.connect() as conn:
            assert _has_vector(conn)
            hnsw = conn.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_facts_embedding_hnsw'")
            ).scalar_one()
        assert "hnsw" in hnsw and "vector_cosine_ops" in hnsw
        assert any(i["column_names"] == ["fingerprint"] for i in inspector.get_indexes("questions"))
        assert any(
            u["column_names"] == ["document_id", "idx"] for u in inspector.get_unique_constraints("facts")
        )

        command.downgrade(alembic_cfg, "base")
        assert not TABLES & set(inspect(test_engine).get_table_names())
        with test_engine.connect() as conn:
            assert not _has_vector(conn)
    finally:
        # Other tests expect the schema, whatever happened above.
        command.upgrade(alembic_cfg, "head")


def test_models_match_migration(alembic_cfg, test_engine):
    command.upgrade(alembic_cfg, "head")
    with test_engine.connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []
