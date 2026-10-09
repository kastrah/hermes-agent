import pytest
from types import SimpleNamespace
from plugins.platforms.discord.discord_secure_input import secure_input_view


@pytest.mark.asyncio
async def test_private_link_button_and_plain_send_unchanged():
    url = "https://zuri.example.ts.net:8443/#fictional-request"
    class View:
        def __init__(self, **kwargs):
            self.children = []

        def add_item(self, child):
            self.children.append(child)

    api = SimpleNamespace(ui=SimpleNamespace(View=View, Button=lambda **kwargs: SimpleNamespace(**kwargs)),
                          ButtonStyle=SimpleNamespace(link=5))
    kwargs = secure_input_view({"_secure_vault_link": url}, 0, discord_api=api)
    assert kwargs["view"].children[0].url == url
    assert kwargs["view"].children[0].label == "Save securely"
    assert secure_input_view({}, 0) == {}
    assert secure_input_view({"_secure_vault_link": url}, 1) == {}
    assert secure_input_view({"_secure_vault_link": "https://evil.test/#x"}, 0) == {}
    assert secure_input_view({"_secure_vault_link": "http://zuri.example.ts.net/#x"}, 0) == {}
