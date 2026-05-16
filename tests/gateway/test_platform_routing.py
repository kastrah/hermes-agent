from gateway.platforms.routing import RoutingFacts, channel_set, decide_message_routing


def test_dm_is_always_allowed():
    decision = decide_message_routing(RoutingFacts(is_dm=True, authored_by_bot=True))

    assert decision.should_process is True
    assert decision.reason == "dm"


def test_other_bot_mention_wins_over_wake_pattern():
    decision = decide_message_routing(
        RoutingFacts(
            require_mention=True,
            mentions_other=True,
            matches_wake_pattern=True,
        )
    )

    assert decision.should_process is False
    assert decision.reason == "mentions_other"


def test_self_mention_wins_over_reply_to_other_bot():
    decision = decide_message_routing(
        RoutingFacts(
            require_mention=True,
            mentions_self=True,
            replies_to_other_bot=True,
        )
    )

    assert decision.should_process is True
    assert decision.reason == "mentions_self"


def test_channel_set_normalizes_lists_scalars_and_csv():
    assert channel_set([123, " 456 ", ""]) == {"123", "456"}
    assert channel_set("123, 456") == {"123", "456"}
    assert channel_set(None) == set()
