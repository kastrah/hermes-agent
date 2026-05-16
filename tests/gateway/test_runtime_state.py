from gateway.runtime_state import GatewayRuntimeState


PENDING = object()


def test_runtime_state_claim_bind_and_release():
    state = GatewayRuntimeState()

    generation = state.claim_pending("chat", PENDING)
    assert state.running_agents["chat"] is PENDING
    assert generation == 1

    agent = object()
    assert state.bind_agent("chat", agent, generation) is True
    assert state.running_agents["chat"] is agent

    assert state.release("chat", generation) is True
    assert "chat" not in state.running_agents
    assert "chat" not in state.running_started_at


def test_runtime_state_generation_guard_blocks_stale_release():
    state = GatewayRuntimeState()
    old_generation = state.claim_pending("chat", PENDING)
    new_generation = state.begin_generation("chat")

    assert old_generation != new_generation
    assert state.release("chat", old_generation) is False
    assert "chat" in state.running_agents
