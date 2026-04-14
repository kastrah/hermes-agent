"""Tests for session.stopping hook — steering feature."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSessionStoppingHook:
    @pytest.mark.asyncio
    async def test_stopping_hook_emitted_on_agent_completion(self):
        """Test that session:stopping hook fires when agent loop is about to break."""
        from gateway.hooks import HookRegistry

        reg = HookRegistry()
        emitted_events = []

        async def mock_handler(event_type, context):
            emitted_events.append((event_type, context))

        reg._handlers["session:stopping"] = [mock_handler]
        reg.discover_and_load = MagicMock()

        result = await reg.emit("session:stopping", {
            "session_key": "test-key",
            "session_id": "test-id",
            "messages": [{"role": "user", "content": "hello"}],
        })

        assert len(emitted_events) == 1
        assert emitted_events[0][0] == "session:stopping"
        assert emitted_events[0][1]["session_key"] == "test-key"

    @pytest.mark.asyncio
    async def test_stopping_hook_returns_result_for_steering(self):
        """Test that hook result is returned from emit for steering control."""
        from gateway.hooks import HookRegistry

        reg = HookRegistry()

        async def steering_handler(event_type, context):
            return {"stop": False, "message": "continue with this"}

        reg._handlers["session:stopping"] = [steering_handler]
        reg.discover_and_load = MagicMock()

        result = await reg.emit("session:stopping", {
            "session_key": "test-key",
            "session_id": "test-id",
            "messages": [],
        })

        assert result is not None
        assert result["stop"] is False
        assert result["message"] == "continue with this"

    @pytest.mark.asyncio
    async def test_stopping_hook_no_result_means_normal_break(self):
        """Test that no hook result means normal loop termination."""
        from gateway.hooks import HookRegistry

        reg = HookRegistry()

        async def noop_handler(event_type, context):
            return None

        reg._handlers["session:stopping"] = [noop_handler]
        reg.discover_and_load = MagicMock()

        result = await reg.emit("session:stopping", {
            "session_key": "test-key",
            "session_id": "test-id",
            "messages": [],
        })

        assert result is None

    @pytest.mark.asyncio
    async def test_multiple_handlers_last_result_wins(self):
        """Test that when multiple handlers run, last non-None result is returned."""
        from gateway.hooks import HookRegistry

        reg = HookRegistry()

        async def handler1(event_type, context):
            return {"stop": True, "message": "first"}

        async def handler2(event_type, context):
            return {"stop": False, "message": "second"}

        reg._handlers["session:stopping"] = [handler1, handler2]
        reg.discover_and_load = MagicMock()

        result = await reg.emit("session:stopping", {
            "session_key": "test-key",
            "session_id": "test-id",
            "messages": [],
        })

        assert result is not None
        assert result["stop"] is False
        assert result["message"] == "second"


class TestStoppingHookSchema:
    def test_hook_schema_documented(self):
        """Verify session:stopping is documented in hooks.py."""
        from gateway import hooks as hooks_module
        import inspect

        source = inspect.getsource(hooks_module)
        assert "session:stopping" in source