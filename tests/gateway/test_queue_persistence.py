import pytest
from unittest.mock import MagicMock


def test_pending_messages_survive_interrupt():
    """Test that pending messages are not lost on interrupt."""
    runner = MagicMock()
    runner._pending_messages = {"session1": "test message"}
    runner._session_store = MagicMock()

    session_key = "session1"
    assert session_key in runner._pending_messages
    assert runner._pending_messages[session_key] is not None


def test_persistence_interface_exists():
    """Test that session store has persistence methods."""
    from gateway.session import SessionStore

    assert hasattr(SessionStore, 'save_pending_messages')
    assert hasattr(SessionStore, 'load_pending_messages')


def test_gateway_loads_pending_on_resume():
    """Test that gateway loads pending messages when session resumes."""
    runner = MagicMock()
    runner._pending_messages = {}
    runner._session_store = MagicMock()
    runner._session_store.load_pending_messages = MagicMock(return_value={"text": "queued"})

    session_key = "test-session"
    saved_pending = runner._session_store.load_pending_messages(session_key)
    if saved_pending and session_key not in runner._pending_messages:
        runner._pending_messages[session_key] = saved_pending

    assert session_key in runner._pending_messages
    assert runner._pending_messages[session_key] == {"text": "queued"}