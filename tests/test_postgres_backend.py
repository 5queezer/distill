"""PostgreSQL backend wiring — unit tests (no live DB required)."""

import pytest

from distill_mcp.settings import Settings

try:
    from distill_mcp.adapters.storage.postgres_store import PostgresStore

    _HAS_ASYNCPG = True
except ImportError:
    _HAS_ASYNCPG = False


class TestSettings:
    def test_default_backend_is_local(self) -> None:
        s = Settings(backend="local")
        assert s.backend == "local"
        assert s.database_url is None

    def test_postgres_backend_with_database_url(self) -> None:
        s = Settings(
            backend="postgres",
            database_url="postgresql://user:pass@localhost:5432/distill",
        )
        assert s.backend == "postgres"
        assert s.database_url == "postgresql://user:pass@localhost:5432/distill"

    def test_database_url_defaults_to_none(self) -> None:
        s = Settings()
        assert s.database_url is None


@pytest.mark.skipif(not _HAS_ASYNCPG, reason="asyncpg not installed")
class TestPostgresStoreInstantiation:
    def test_instantiate_with_dsn(self) -> None:
        dsn = "postgresql://user:pass@localhost:5432/distill"
        store = PostgresStore(dsn=dsn)
        assert store._dsn == dsn
        assert store._pool is None

    def test_instantiate_with_individual_params(self) -> None:
        store = PostgresStore(
            host="db.example.com",
            port=5433,
            database="mydb",
            user="myuser",
            password="mypass",
        )
        assert store._host == "db.example.com"
        assert store._port == 5433
        assert store._database == "mydb"
        assert store._dsn is None
        assert store._pool is None

    def test_default_params(self) -> None:
        store = PostgresStore()
        assert store._host == "localhost"
        assert store._port == 5432
        assert store._database == "distill"
        assert store._user == "distill"
        assert store._password == "distill"
        assert store._rrf_k == 60
        assert store._fts_language == "simple"
