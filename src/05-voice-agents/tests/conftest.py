"""Isolate operational data before importing the real graph and tools."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_artifacts = tempfile.TemporaryDirectory(prefix="voice-lab-tests-")
os.environ["VOICE_LAB_ARTIFACTS_DIR"] = _artifacts.name

import pytest
from voice_lab.tools import operational_tools
from voice_lab.tools.sandbox import OperationalSandbox


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    instance = OperationalSandbox(tmp_path / "jobs.db")
    monkeypatch.setattr(operational_tools, "sandbox", instance)
    return instance
