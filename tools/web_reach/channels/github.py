"""GitHub channel using gh when available, with raw-file handling."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from urllib.parse import urlparse

import httpx

from ..utils import DEFAULT_TIMEOUT
from .base import ChannelCheck, ReachChannel


def _run_gh(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


class GitHubChannel(ReachChannel):
    name = "github"
    description = "GitHub repos, issues, PRs, and source files"
    search_prefixes = ("github", "gh")

    def can_handle_url(self, url: str) -> bool:
        return "github.com" in urlparse(url).netloc.lower()

    def check(self) -> ChannelCheck:
        if not shutil.which("gh"):
            return ChannelCheck(status="warn", message="gh CLI unavailable; falling back to generic web reads")
        result = _run_gh(["auth", "status"])
        if result.returncode == 0:
            return ChannelCheck(status="ok", message="gh CLI available")
        return ChannelCheck(status="warn", message="gh CLI installed but not authenticated")

    def search(self, query: str, limit: int) -> list[dict[str, object]] | None:
        if not shutil.which("gh"):
            return None
        result = _run_gh(
            [
                "search",
                "repos",
                query,
                "--limit",
                str(min(limit, 10)),
                "--json",
                "nameWithOwner,description,url,stargazerCount,updatedAt",
            ]
        )
        if result.returncode != 0:
            return None
        payload = json.loads(result.stdout or "[]")
        results = []
        for idx, item in enumerate(payload[:limit], start=1):
            results.append(
                {
                    "title": item.get("nameWithOwner", ""),
                    "url": item.get("url", ""),
                    "description": item.get("description", ""),
                    "position": idx,
                }
            )
        return results

    async def extract(self, url: str, client: httpx.AsyncClient) -> dict[str, object] | None:
        parsed = urlparse(url)
        segments = [segment for segment in parsed.path.split("/") if segment]
        if len(segments) < 2:
            return None

        owner, repo = segments[0], segments[1]

        if len(segments) >= 5 and segments[2] == "blob":
            ref = segments[3]
            file_path = "/".join(segments[4:])
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{file_path}"
            response = await client.get(raw_url, timeout=DEFAULT_TIMEOUT)
            response.raise_for_status()
            content = response.text
            return {
                "url": raw_url,
                "title": f"{owner}/{repo}:{file_path}",
                "content": content,
                "raw_content": content,
                "metadata": {
                    "sourceURL": raw_url,
                    "title": f"{owner}/{repo}:{file_path}",
                    "backend": "reach",
                    "channel": self.name,
                },
            }

        if not shutil.which("gh"):
            return None

        if len(segments) >= 4 and segments[2] == "issues":
            issue_number = segments[3]
            result = _run_gh(
                [
                    "issue",
                    "view",
                    issue_number,
                    "-R",
                    f"{owner}/{repo}",
                    "--json",
                    "title,body,url,state,author,labels,comments",
                ]
            )
            if result.returncode == 0:
                payload = json.loads(result.stdout or "{}")
                comments = payload.get("comments", [])[:10]
                lines = [
                    f"# {payload.get('title', '')}",
                    f"State: {payload.get('state', '')}",
                    "",
                    payload.get("body") or "",
                    "",
                    "## Comments",
                ]
                for comment in comments:
                    author = (comment.get("author") or {}).get("login", "")
                    lines.extend([f"- {author}", comment.get("body") or ""])
                content = "\n".join(lines).strip()
                return {
                    "url": payload.get("url", url),
                    "title": payload.get("title", ""),
                    "content": content,
                    "raw_content": content,
                    "metadata": {
                        "sourceURL": payload.get("url", url),
                        "title": payload.get("title", ""),
                        "backend": "reach",
                        "channel": self.name,
                    },
                }

        if len(segments) >= 4 and segments[2] == "pull":
            pr_number = segments[3]
            result = _run_gh(
                [
                    "pr",
                    "view",
                    pr_number,
                    "-R",
                    f"{owner}/{repo}",
                    "--json",
                    "title,body,url,state,author,commits,reviews",
                ]
            )
            if result.returncode == 0:
                payload = json.loads(result.stdout or "{}")
                lines = [
                    f"# {payload.get('title', '')}",
                    f"State: {payload.get('state', '')}",
                    "",
                    payload.get("body") or "",
                ]
                content = "\n".join(lines).strip()
                return {
                    "url": payload.get("url", url),
                    "title": payload.get("title", ""),
                    "content": content,
                    "raw_content": content,
                    "metadata": {
                        "sourceURL": payload.get("url", url),
                        "title": payload.get("title", ""),
                        "backend": "reach",
                        "channel": self.name,
                    },
                }

        result = _run_gh(
            [
                "repo",
                "view",
                f"{owner}/{repo}",
                "--json",
                "nameWithOwner,description,url,homepageUrl,stargazerCount,forkCount,primaryLanguage,updatedAt",
            ]
        )
        if result.returncode != 0:
            return None
        payload = json.loads(result.stdout or "{}")
        content = "\n".join(
            [
                f"# {payload.get('nameWithOwner', f'{owner}/{repo}')}",
                payload.get("description") or "",
                "",
                f"Stars: {payload.get('stargazerCount', 0)}",
                f"Forks: {payload.get('forkCount', 0)}",
                f"Primary language: {(payload.get('primaryLanguage') or {}).get('name', '')}",
                f"Updated: {payload.get('updatedAt', '')}",
                f"Homepage: {payload.get('homepageUrl', '')}",
            ]
        ).strip()
        return {
            "url": payload.get("url", url),
            "title": payload.get("nameWithOwner", f"{owner}/{repo}"),
            "content": content,
            "raw_content": content,
            "metadata": {
                "sourceURL": payload.get("url", url),
                "title": payload.get("nameWithOwner", f"{owner}/{repo}"),
                "backend": "reach",
                "channel": self.name,
            },
        }
