from __future__ import annotations

import shutil

import pytest

from app import config, storage


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Give every test its own database and output folder."""
    out = tmp_path / "output"
    out.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "OUTPUT_DIR", out, raising=False)
    monkeypatch.setattr("app.agent.pipeline.OUTPUT_DIR", out, raising=False)
    storage.reset_store(tmp_path / "test.db")
    yield
    shutil.rmtree(out, ignore_errors=True)


@pytest.fixture
def store():
    return storage.get_store()
