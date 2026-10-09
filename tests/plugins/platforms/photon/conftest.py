"""Keep adapter behaviour tests out of the host's package-manager state."""
import os
import shutil
import pytest


@pytest.fixture(autouse=True)
def isolated_node_discovery(monkeypatch):
    # Test the adapter, not PM's installed tool lookup in the live Hermes home.
    from plugins.platforms.photon import adapter, cli
    for module in (adapter, cli):
        monkeypatch.setattr(module, "find_node_executable", shutil.which)
        monkeypatch.setattr(module, "with_hermes_node_path", lambda: dict(os.environ))
