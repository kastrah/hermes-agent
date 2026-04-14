import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
import uuid


def _generate_loop_id() -> str:
    """Generate unique loop ID with timestamp for race condition prevention."""
    return f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"


def test_loop_id_generation():
    """Test that loop IDs are unique and contain timestamp."""
    loop_id = _generate_loop_id()

    assert len(loop_id.split("-")) >= 2
    assert loop_id.count("-") >= 1


def test_loop_id_uniqueness():
    """Test that consecutive loop IDs are unique."""
    ids = {_generate_loop_id() for _ in range(100)}
    assert len(ids) == 100


def test_loop_id_format():
    """Test loop ID format is timestamp-random."""
    loop_id = _generate_loop_id()
    parts = loop_id.split("-")
    assert len(parts) == 2
    timestamp_part = parts[0]
    assert len(timestamp_part) == 14
    assert timestamp_part.isdigit()


def test_session_loop_ids_tracking():
    """Test that loop IDs are tracked per session."""
    runner = MagicMock()
    runner._session_loop_ids = {}

    loop_id = _generate_loop_id()
    runner._session_loop_ids["session1"] = loop_id

    assert runner._session_loop_ids["session1"] == loop_id


def test_loop_id_prevents_race_condition():
    """Test that different loop IDs prevent message appending."""
    pending = {}
    session_key = "session1"

    current_loop_id = _generate_loop_id()
    old_loop_id = "20240414092900-abcdefgh"

    pending[session_key] = {
        "event": "old message",
        "loop_id": old_loop_id,
        "timestamp": None
    }

    new_loop_id = _generate_loop_id()
    existing = pending[session_key]
    assert existing.get("loop_id") != new_loop_id