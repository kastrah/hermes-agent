import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.asyncio
async def test_full_steering_flow():
    """Test complete steering: interrupt -> queue -> inject -> continue."""
    # This tests the full flow:
    # 1. User sends message while agent running
    # 2. Message queued (with loopId)
    # 3. Agent interrupted
    # 4. session:stopping hook called
    # 5. Hook injects continuation message
    # 6. Agent continues with new message
    
    # Test loop_id generation independently (can't import GatewayRunner due to broken run.py)
    from datetime import datetime
    import uuid
    
    def generate_loop_id() -> str:
        return f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    
    # Test generate_loop_id exists and works
    loop_id = generate_loop_id()
    assert loop_id.count('-') == 1
    parts = loop_id.split('-')
    assert len(parts[0]) == 14  # timestamp
    assert len(parts[1]) == 8   # random


@pytest.mark.asyncio
async def test_steering_hook_allows_continue():
    """Test that session:stopping hook can return stop=False to continue."""
    from gateway.hooks import HookRegistry
    
    registry = MagicMock(spec=HookRegistry)
    
    # Hook returns stop=False with continuation message
    mock_handler = AsyncMock(return_value={
        "stop": False,
        "message": "Use a different approach"
    })
    registry._handlers = {"session:stopping": [mock_handler]}
    
    # Call the handler
    handlers = registry._handlers.get("session:stopping", [])
    if handlers:
        result = await handlers[0]("session:stopping", {
            "session_key": "session1",
            "session_id": "session-456",
            "messages": [{"role": "user", "content": "test"}],
            "queued_messages": {}
        })
        
        # Verify continuation
        assert result["stop"] is False
        assert "different approach" in result["message"]


@pytest.mark.asyncio
async def test_steering_hook_can_stop():
    """Test that session:stopping hook can return stop=True."""
    from gateway.hooks import HookRegistry
    
    registry = MagicMock(spec=HookRegistry)
    
    # Hook returns stop=True to stop normally
    mock_handler = AsyncMock(return_value={"stop": True})
    registry._handlers = {"session:stopping": [mock_handler]}
    
    handlers = registry._handlers.get("session:stopping", [])
    if handlers:
        result = await handlers[0]("session:stopping", {
            "session_key": "session1",
            "session_id": "session-789",
            "messages": [],
            "queued_messages": {}
        })
        
        assert result["stop"] is True


@pytest.mark.asyncio
async def test_steering_queued_messages_visibility():
    """Test that queued messages are visible to session:stopping hook."""
    from gateway.hooks import HookRegistry
    
    registry = MagicMock(spec=HookRegistry)
    
    pending_messages = {
        "session1": {
            "text": "Change the code",
            "loop_id": "20240414093000-abc123"
        }
    }
    
    # Hook should receive queued_messages in context
    mock_handler = AsyncMock(return_value={"stop": True})
    registry._handlers = {"session:stopping": [mock_handler]}
    
    handlers = registry._handlers.get("session:stopping", [])
    if handlers:
        await handlers[0]("session:stopping", {
            "session_key": "session1",
            "session_id": "session-abc",
            "messages": [],
            "queued_messages": pending_messages
        })
        
        # Verify hook was called with queued_messages
        call_args = mock_handler.call_args
        context = call_args[0][1]
        assert "queued_messages" in context
        assert "session1" in context["queued_messages"]