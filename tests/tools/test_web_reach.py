"""Tests for the built-in no-API web backend."""

import asyncio
import json
import subprocess

from tools.web_reach import no_api_web_doctor
from tools.web_reach.channels.linkedin import LinkedInChannel
from tools.web_reach.channels.twitter import TwitterChannel
from tools.web_reach.extract import no_api_web_extract
from tools.web_reach.search import no_api_web_search


class _SyncResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


class _AsyncResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None


def test_no_api_web_search_parses_duckduckgo_results(monkeypatch):
    html = """
    <html>
      <body>
        <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpost&amp;rut=abc">
          Example <b>Post</b>
        </a>
        <a class="result__snippet">A short <b>summary</b> of the result.</a>
      </body>
    </html>
    """

    monkeypatch.setattr(
        "tools.web_reach.channels.web.httpx.get",
        lambda *args, **kwargs: _SyncResponse(html),
    )

    payload = json.loads(no_api_web_search("example query", limit=5))

    assert payload["success"] is True
    assert payload["data"]["web"] == [
        {
            "title": "Example Post",
            "url": "https://example.com/post",
            "description": "A short summary of the result.",
            "position": 1,
        }
    ]


def test_web_channel_filters_ads_and_allowed_hosts(monkeypatch):
    from tools.web_reach.channels.web import WebChannel

    html = """
    <html>
      <body>
        <a rel="nofollow" class="result__a" href="https://duckduckgo.com/y.js?ad_domain=example.com">Ad Result</a>
        <a class="result__snippet">Ad snippet</a>
        <a rel="nofollow" class="result__a" href="https://www.youtube.com/watch?v=123">OpenAI Video</a>
        <a class="result__snippet">Video snippet</a>
        <a rel="nofollow" class="result__a" href="https://example.com/post">Generic Result</a>
        <a class="result__snippet">Generic snippet</a>
      </body>
    </html>
    """

    monkeypatch.setattr(
        "tools.web_reach.channels.web.httpx.get",
        lambda *args, **kwargs: _SyncResponse(html),
    )

    results = WebChannel().search("openai", 5, allowed_hosts=("youtube.com", "youtu.be"))
    assert results == [
        {
            "title": "OpenAI Video",
            "url": "https://www.youtube.com/watch?v=123",
            "description": "Video snippet",
            "position": 1,
        }
    ]


def test_no_api_web_extract_uses_jina_reader(monkeypatch):
    async def fake_extract(self, url, client):
        assert url == "https://example.com/post"
        return {
            "url": "https://example.com/post",
            "title": "Example Post",
            "content": (
                "Title: Example Post\n"
                "URL Source: https://example.com/post\n\n"
                "Markdown body here."
            ),
            "raw_content": (
                "Title: Example Post\n"
                "URL Source: https://example.com/post\n\n"
                "Markdown body here."
            ),
            "metadata": {
                "sourceURL": "https://example.com/post",
                "title": "Example Post",
                "backend": "reach",
                "channel": "web",
            },
        }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("tools.web_reach.extract.httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setattr("tools.web_reach.channels.web.WebChannel.extract", fake_extract)

    results = asyncio.run(no_api_web_extract(["https://example.com/post"]))

    assert results == [
        {
            "url": "https://example.com/post",
            "title": "Example Post",
            "content": (
                "Title: Example Post\n"
                "URL Source: https://example.com/post\n\n"
                "Markdown body here."
            ),
            "raw_content": (
                "Title: Example Post\n"
                "URL Source: https://example.com/post\n\n"
                "Markdown body here."
            ),
            "metadata": {
                "sourceURL": "https://example.com/post",
                "title": "Example Post",
                "backend": "reach",
                "channel": "web",
            },
        }
    ]


def test_no_api_web_search_routes_prefixed_queries(monkeypatch):
    class StubChannel:
        name = "reddit"

        def search(self, query, limit):
            assert query == "python"
            assert limit == 5
            return [
                {
                    "title": "Reddit Result",
                    "url": "https://www.reddit.com/r/python/",
                    "description": "stub",
                    "position": 1,
                }
            ]

    monkeypatch.setattr("tools.web_reach.search.get_channel_by_prefix", lambda prefix: StubChannel())

    payload = json.loads(no_api_web_search("reddit: python", limit=5))
    assert payload["data"]["web"][0]["title"] == "Reddit Result"


def test_no_api_web_search_routes_twitter_prefix(monkeypatch):
    class StubChannel:
        name = "twitter"

        def search(self, query, limit):
            assert query == "openai"
            assert limit == 3
            return [
                {
                    "title": "Tweet Result",
                    "url": "https://x.com/openai/status/1",
                    "description": "stub",
                    "position": 1,
                }
            ]

    monkeypatch.setattr("tools.web_reach.search.get_channel_by_prefix", lambda prefix: StubChannel())

    payload = json.loads(no_api_web_search("twitter: openai", limit=3))
    assert payload["data"]["web"][0]["url"] == "https://x.com/openai/status/1"


def test_no_api_web_doctor_lists_channels():
    payload = json.loads(no_api_web_doctor())
    names = {channel["name"] for channel in payload["channels"]}
    assert {"web", "twitter", "linkedin", "reddit", "github", "youtube", "bilibili", "rss", "v2ex"} <= names


def test_youtube_channel_falls_back_to_filtered_web_results_on_timeout(monkeypatch):
    from tools.web_reach.channels.youtube import YouTubeChannel

    monkeypatch.setattr("tools.web_reach.channels.youtube.shutil.which", lambda _: "/usr/bin/yt-dlp")

    def raise_timeout(args):
        raise subprocess.TimeoutExpired(cmd=["yt-dlp"], timeout=45)

    monkeypatch.setattr("tools.web_reach.channels.youtube._run_ytdlp", raise_timeout)

    captured = {}

    def fake_web_search(self, query, limit, allowed_hosts=None):
        captured["query"] = query
        captured["limit"] = limit
        captured["allowed_hosts"] = allowed_hosts
        return [
            {
                "title": "OpenAI - YouTube",
                "url": "https://www.youtube.com/c/OpenAI",
                "description": "OpenAI channel",
                "position": 1,
            }
        ]

    monkeypatch.setattr("tools.web_reach.channels.youtube.WebChannel.search", fake_web_search)

    results = YouTubeChannel().search("openai", 2)

    assert captured == {
        "query": "site:youtube.com openai",
        "limit": 2,
        "allowed_hosts": ("youtube.com", "youtu.be"),
    }
    assert results[0]["url"] == "https://www.youtube.com/c/OpenAI"


def test_twitter_channel_prefers_bird_for_extract(monkeypatch):
    monkeypatch.setattr("tools.web_reach.channels.twitter._bird_path", lambda: "/usr/bin/bird")

    class Result:
        def __init__(self, stdout, returncode=0):
            self.stdout = stdout
            self.returncode = returncode

    calls = []

    def fake_run(args):
        calls.append(args)
        if args == ["check"]:
            return Result("", 0)
        return Result("OpenAI thread title\nhttps://x.com/OpenAI/status/1\nBody text", 0)

    monkeypatch.setattr("tools.web_reach.channels.twitter._run_bird", fake_run)

    result = asyncio.run(TwitterChannel().extract("https://x.com/OpenAI/status/1", client=None))

    assert calls[0] == ["check"]
    assert calls[1] == ["thread", "https://x.com/OpenAI/status/1"]
    assert result["metadata"]["adapter"] == "bird"
    assert result["title"] == "OpenAI thread title"


def test_linkedin_channel_prefers_mcporter_for_search(monkeypatch):
    monkeypatch.setattr("tools.web_reach.channels.linkedin._linkedin_cookie_client", lambda: None)
    monkeypatch.setattr("tools.web_reach.channels.linkedin._mcporter_path", lambda: "/usr/bin/mcporter")

    class Result:
        def __init__(self, stdout, returncode=0):
            self.stdout = stdout
            self.returncode = returncode

    def fake_run(args):
        if args == ["config", "list"]:
            return Result("linkedin\n", 0)
        return Result(
            json.dumps(
                [
                    {
                        "name": "Ada Lovelace",
                        "linkedin_url": "https://linkedin.com/in/ada",
                        "headline": "Engineer",
                    }
                ]
            ),
            0,
        )

    monkeypatch.setattr("tools.web_reach.channels.linkedin._run_mcporter", fake_run)

    results = LinkedInChannel().search("ada", 5)

    assert results[0]["title"] == "Ada Lovelace"
    assert results[0]["url"] == "https://linkedin.com/in/ada"


def test_linkedin_channel_prefers_mcporter_for_profile_extract(monkeypatch):
    monkeypatch.setattr("tools.web_reach.channels.linkedin._linkedin_cookie_client", lambda: None)
    monkeypatch.setattr("tools.web_reach.channels.linkedin._mcporter_path", lambda: "/usr/bin/mcporter")

    class Result:
        def __init__(self, stdout, returncode=0):
            self.stdout = stdout
            self.returncode = returncode

    def fake_run(args):
        if args == ["config", "list"]:
            return Result("linkedin\n", 0)
        return Result(json.dumps({"name": "Ada Lovelace", "headline": "Engineer"}), 0)

    monkeypatch.setattr("tools.web_reach.channels.linkedin._run_mcporter", fake_run)

    result = asyncio.run(LinkedInChannel().extract("https://www.linkedin.com/in/ada", client=None))

    assert result["title"] == "Ada Lovelace"
    assert result["metadata"]["adapter"] == "mcporter"


def test_linkedin_channel_prefers_cookie_adapter_for_search(monkeypatch):
    class FakeClient:
        def search(self, params, limit):
            assert params["keywords"] == "ada"
            assert limit == 5
            return [
                {
                    "navigationUrl": "https://www.linkedin.com/in/ada?trk=foo",
                    "title": {"text": "Ada Lovelace"},
                    "primarySubtitle": {"text": "Engineer"},
                }
            ]

    monkeypatch.setattr("tools.web_reach.channels.linkedin._linkedin_cookie_client", lambda: FakeClient())

    results = LinkedInChannel().search("ada", 5)

    assert results[0]["title"] == "Ada Lovelace"
    assert results[0]["url"] == "https://www.linkedin.com/in/ada"


def test_linkedin_channel_prefers_cookie_adapter_for_profile_extract(monkeypatch):
    class FakeClient:
        def get_profile(self, public_id):
            assert public_id == "ada"
            return {"firstName": "Ada", "lastName": "Lovelace", "headline": "Engineer"}

    monkeypatch.setattr("tools.web_reach.channels.linkedin._linkedin_cookie_client", lambda: FakeClient())

    result = asyncio.run(LinkedInChannel().extract("https://www.linkedin.com/in/ada", client=None))

    assert result["metadata"]["adapter"] == "linkedin-cookies"
    assert "Ada" in result["content"]


def test_linkedin_channel_check_reports_browser_cookie_adapter(monkeypatch):
    monkeypatch.setattr(
        "tools.web_reach.channels.linkedin._linkedin_cookie_source",
        lambda: ("chrome", "li_at", "jsessionid"),
    )
    monkeypatch.setattr("tools.web_reach.channels.linkedin._linkedin_api_available", lambda: True)

    check = LinkedInChannel().check()

    assert check.status == "ok"
    assert "Chrome cookies" in check.message
