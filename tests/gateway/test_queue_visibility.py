import pytest
from unittest.mock import MagicMock


def test_queued_messages_string_values():
    """Test queue message formatting logic for string values."""
    _pending_messages = {
        "session1": "Hello world",
        "session2": "Second message",
    }
    
    result = {}
    for session_key, info in _pending_messages.items():
        if hasattr(info, "text"):
            result[session_key] = {
                "message": getattr(info, "text", ""),
                "loop_id": getattr(info, "loop_id", None),
                "timestamp": getattr(info, "timestamp", None),
            }
        else:
            result[session_key] = {
                "message": info if isinstance(info, str) else "",
                "loop_id": None,
                "timestamp": None,
            }
    
    assert "session1" in result
    assert result["session1"]["message"] == "Hello world"
    assert result["session2"]["message"] == "Second message"


def test_queued_messages_event_objects():
    """Test queue message formatting logic for MessageEvent objects."""
    mock_event = MagicMock()
    mock_event.text = "Test message"
    mock_event.loop_id = "20240414093000-a1b2c3d4"
    mock_event.timestamp = "2024-04-14T09:30:00"
    
    _pending_messages = {
        "session1": mock_event,
    }
    
    result = {}
    for session_key, info in _pending_messages.items():
        if hasattr(info, "text"):
            result[session_key] = {
                "message": getattr(info, "text", ""),
                "loop_id": getattr(info, "loop_id", None),
                "timestamp": getattr(info, "timestamp", None),
            }
        else:
            result[session_key] = {
                "message": info if isinstance(info, str) else "",
                "loop_id": None,
                "timestamp": None,
            }
    
    assert "session1" in result
    assert result["session1"]["message"] == "Test message"
    assert result["session1"]["loop_id"] == "20240414093000-a1b2c3d4"
    assert result["session1"]["timestamp"] == "2024-04-14T09:30:00"


def test_queued_messages_empty():
    """Test queue message formatting with empty dict."""
    _pending_messages = {}
    
    result = {}
    for session_key, info in _pending_messages.items():
        if hasattr(info, "text"):
            result[session_key] = {
                "message": getattr(info, "text", ""),
                "loop_id": getattr(info, "loop_id", None),
                "timestamp": getattr(info, "timestamp", None),
            }
        else:
            result[session_key] = {
                "message": info if isinstance(info, str) else "",
                "loop_id": None,
                "timestamp": None,
            }
    
    assert result == {}