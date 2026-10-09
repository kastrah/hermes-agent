"""Render secure input links without accepting or handling secret values in Discord."""
from urllib.parse import urlsplit


def secure_input_view(metadata, chunk_index, discord_api=None):
    url = (metadata or {}).get("_secure_vault_link")
    if chunk_index != 0 or not isinstance(url, str):
        return {}
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".ts.net")
            or parsed.username or parsed.password or not parsed.fragment):
        return {}
    if discord_api is None:
        import discord as discord_api
    discord = discord_api
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Save securely", style=discord.ButtonStyle.link, url=url))
    return {"view": view}
