"""Tests for document conversion and ingestion (MarkItDown integration)."""

from __future__ import annotations

import asyncio
import os
import tempfile
from contextlib import suppress

import pytest

# ── Documents Module Unit Tests ──────────────────────────────────────────


class TestDocumentsModule:
    """Unit tests for documents.py validation and helpers."""

    def test_validate_file_valid(self):
        from codex_proxy.documents import validate_file
        assert validate_file("report.pdf", 1024) is None
        assert validate_file("data.xlsx", 5_000_000) is None
        assert validate_file("notes.txt", 100) is None

    def test_validate_file_bad_extension(self):
        from codex_proxy.documents import validate_file
        result = validate_file("malware.exe", 1024)
        assert result is not None
        assert "exe" in result
        assert "Unsupported" in result

    def test_validate_file_too_large(self):
        from codex_proxy.documents import MAX_FILE_SIZE_DEFAULT, validate_file
        result = validate_file("big.pdf", MAX_FILE_SIZE_DEFAULT + 1)
        assert result is not None
        assert "too large" in result.lower()

    def test_validate_file_empty(self):
        from codex_proxy.documents import validate_file
        result = validate_file("empty.txt", 0)
        assert result is not None
        assert "empty" in result.lower()

    def test_validate_file_no_filename(self):
        from codex_proxy.documents import validate_file
        result = validate_file("", 1024)
        assert result is not None

    def test_get_file_type(self):
        from codex_proxy.documents import get_file_type
        assert get_file_type("report.PDF") == "pdf"
        assert get_file_type("data.XLSX") == "xlsx"
        assert get_file_type("notes.txt") == "txt"

    def test_singleton(self):
        from codex_proxy.documents import _get_markitdown
        a = _get_markitdown()
        b = _get_markitdown()
        assert a is b

    def test_convert_txt_file(self):
        """Test actual MarkItDown conversion on a text file."""
        from codex_proxy.documents import convert_file

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write("# Hello World\n\nThis is a test document.\n")
            tmp = f.name

        try:
            markdown, title = asyncio.run(convert_file(tmp))
            assert "Hello World" in markdown
            assert "test document" in markdown
        finally:
            os.unlink(tmp)


# ── CRUD Tests ───────────────────────────────────────────────────────────


def _run_db_test(coro):
    """Run an async coroutine with a temp database (using create_all, not migrations)."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from codex_proxy.db.models import metadata

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    async def _wrapper():
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            result = await coro(session)
        await engine.dispose()
        return result

    try:
        return asyncio.run(_wrapper())
    finally:
        with suppress(OSError):
            os.unlink(db_path)


class TestCrudDocuments:
    """CRUD tests for the documents table."""

    def test_create_and_get_document(self):
        async def _test(session):
            from codex_proxy.db import crud_documents
            doc = await crud_documents.create_document(
                session,
                filename="report.pdf",
                original_path="/tmp/test-report.pdf",
                markdown_content="# Report\n\nContent here",
                file_type="pdf",
                file_size=1024,
                user_id=None,
            )
            assert doc["id"]
            assert doc["filename"] == "report.pdf"
            assert doc["file_type"] == "pdf"
            assert doc["markdown_content"] == "# Report\n\nContent here"

            # Fetch it back
            fetched = await crud_documents.get_document(session, doc["id"])
            assert fetched is not None
            assert fetched["filename"] == "report.pdf"
            return True
        assert _run_db_test(_test)

    def test_list_documents(self):
        async def _test(session):
            from codex_proxy.db import crud_documents
            for i in range(3):
                await crud_documents.create_document(
                    session,
                    filename=f"file{i}.txt",
                    original_path=f"/tmp/file{i}.txt",
                    markdown_content=f"Content {i}",
                    file_type="txt",
                    file_size=100 + i,
                )
            docs = await crud_documents.list_documents(session)
            assert len(docs) == 3
            return True
        assert _run_db_test(_test)

    def test_list_documents_by_user(self):
        async def _test(session):
            from codex_proxy.db import crud_documents
            await crud_documents.create_document(
                session, filename="u1.txt", original_path="/tmp/u1.txt",
                markdown_content="u1", file_type="txt", file_size=10,
                user_id="user-1",
            )
            await crud_documents.create_document(
                session, filename="u2.txt", original_path="/tmp/u2.txt",
                markdown_content="u2", file_type="txt", file_size=20,
                user_id="user-2",
            )
            u1_docs = await crud_documents.list_documents(session, user_id="user-1")
            assert len(u1_docs) == 1
            assert u1_docs[0]["filename"] == "u1.txt"

            all_docs = await crud_documents.list_documents(session)
            assert len(all_docs) == 2
            return True
        assert _run_db_test(_test)

    def test_delete_document(self):
        async def _test(session):
            from codex_proxy.db import crud_documents
            doc = await crud_documents.create_document(
                session, filename="del.txt", original_path="/tmp/del.txt",
                markdown_content="bye", file_type="txt", file_size=5,
            )
            deleted = await crud_documents.delete_document(session, doc["id"])
            assert deleted is True

            fetched = await crud_documents.get_document(session, doc["id"])
            assert fetched is None
            return True
        assert _run_db_test(_test)

    def test_count_documents(self):
        async def _test(session):
            from codex_proxy.db import crud_documents
            for i in range(5):
                await crud_documents.create_document(
                    session, filename=f"c{i}.txt", original_path=f"/tmp/c{i}.txt",
                    markdown_content=f"c{i}", file_type="txt", file_size=i,
                    user_id="counter-user",
                )
            total = await crud_documents.count_documents(session)
            assert total == 5

            by_user = await crud_documents.count_documents(session, user_id="counter-user")
            assert by_user == 5

            other = await crud_documents.count_documents(session, user_id="nonexistent")
            assert other == 0
            return True
        assert _run_db_test(_test)


# ── Server Endpoint Integration Tests ────────────────────────────────────


class TestDocumentEndpoints:
    """Integration tests for /documents/* endpoints."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        """Configure the proxy for each test."""
        from codex_proxy.config import ProxyConfig
        from codex_proxy.server import configure
        config = ProxyConfig()
        config.provider.api_key = "test-key"
        configure(config)
        yield

    def test_convert_endpoint_success(self):
        """POST /documents/convert with a .txt file returns markdown."""
        from fastapi.testclient import TestClient

        from codex_proxy.server import app

        client = TestClient(app)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write("# Test Doc\n\nHello from the test!\n")
            tmp = f.name

        try:
            with open(tmp, "rb") as fh:
                resp = client.post("/documents/convert", files={"file": ("test.txt", fh)})
            assert resp.status_code == 200
            data = resp.json()
            assert "markdown" in data
            assert "Test Doc" in data["markdown"]
            assert data["file_type"] == "txt"
        finally:
            os.unlink(tmp)

    def test_convert_endpoint_bad_extension(self):
        """POST /documents/convert with unsupported extension returns 400."""
        from fastapi.testclient import TestClient

        from codex_proxy.server import app

        client = TestClient(app)
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            f.write(b"binary junk")
            tmp = f.name

        try:
            with open(tmp, "rb") as fh:
                resp = client.post("/documents/convert", files={"file": ("evil.exe", fh)})
            assert resp.status_code == 400
            assert "Unsupported" in resp.json()["error"]
        finally:
            os.unlink(tmp)

    def test_ingest_requires_documents_enabled(self):
        """POST /documents/ingest returns 400 when documents disabled."""
        from fastapi.testclient import TestClient

        from codex_proxy.server import app

        client = TestClient(app)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write("test")
            tmp = f.name

        try:
            with open(tmp, "rb") as fh:
                resp = client.post("/documents/ingest", files={"file": ("test.txt", fh)})
            assert resp.status_code == 400
            assert "not enabled" in resp.json()["error"].lower()
        finally:
            os.unlink(tmp)

    def test_list_documents_when_disabled(self):
        """GET /documents returns 400 when documents disabled."""
        from fastapi.testclient import TestClient

        from codex_proxy.server import app

        client = TestClient(app)
        resp = client.get("/documents")
        assert resp.status_code == 400

    def test_get_document_when_disabled(self):
        """GET /documents/{id} returns 400 when documents disabled."""
        from fastapi.testclient import TestClient

        from codex_proxy.server import app

        client = TestClient(app)
        resp = client.get("/documents/nonexistent-id")
        assert resp.status_code == 400

    def test_delete_document_when_disabled(self):
        """DELETE /documents/{id} returns 400 when documents disabled."""
        from fastapi.testclient import TestClient

        from codex_proxy.server import app

        client = TestClient(app)
        resp = client.delete("/documents/nonexistent-id")
        assert resp.status_code == 400
