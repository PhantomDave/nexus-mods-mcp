# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2", "httpx"]
# ///
"""Nexus Mods MCP server: discover mods, top lists, and suggestion data per game."""

import os
import sys
from collections import defaultdict

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

GQL = "https://api.nexusmods.com/v2/graphql"
V1 = "https://api.nexusmods.com/v1"
HEADERS = {"Application-Name": "nexus-mods-mcp", "Application-Version": "0.1.0"}
MOD_FIELDS = (
    "modId name summary endorsements downloads category author version updatedAt"
)

mcp = MCPServer("nexus-mods")


def gql(query: str, variables: dict) -> dict:
    r = httpx.post(
        GQL, json={"query": query, "variables": variables}, headers=HEADERS, timeout=30
    )
    r.raise_for_status()
    body = r.json()
    # GraphQL reports errors with HTTP 200, so check the body too.
    if body.get("errors"):
        raise ToolError("; ".join(e["message"] for e in body["errors"]))
    return body["data"]


def compact(m: dict, game: str) -> dict:
    summary = (m.get("summary") or "").strip()
    return {
        "name": m["name"],
        "id": m["modId"],
        "category": m.get("category"),
        "endorsements": m.get("endorsements"),
        "downloads": m.get("downloads"),
        "author": m.get("author"),
        "version": m.get("version"),
        "updated": (m.get("updatedAt") or "")[:10],
        "summary": summary[:160] + ("…" if len(summary) > 160 else ""),
        "url": f"https://www.nexusmods.com/{game}/mods/{m['modId']}",
    }


def query_mods(
    game: str,
    sort: str = "endorsements",
    count: int = 15,
    name: str | None = None,
    category: str | None = None,
) -> list[dict]:
    if sort not in ("endorsements", "downloads", "updatedAt", "createdAt"):
        raise ToolError("sort must be endorsements, downloads, updatedAt or createdAt")
    f = {"gameDomainName": [{"value": game}], "adultContent": [{"value": False}]}
    if name:
        f["name"] = [{"value": name, "op": "WILDCARD"}]
    if category:
        f["categoryName"] = [{"value": category}]
    data = gql(
        f"query($f: ModsFilter, $s: [ModsSort!], $n: Int) {{ mods(filter: $f, sort: $s, count: $n) {{ nodes {{ {MOD_FIELDS} }} }} }}",
        {"f": f, "s": [{sort: {"direction": "DESC"}}], "n": min(count, 100)},
    )
    nodes = data["mods"]["nodes"]
    if not nodes and not name and not category:
        raise ToolError(
            f"No mods for game domain '{game}'. Use find_game to get the right domain name."
        )
    return [compact(m, game) for m in nodes]


@mcp.tool()
def find_game(query: str) -> list[dict]:
    """Find a game's Nexus domain name (e.g. 'skyrim' -> skyrimspecialedition). Call this first when unsure of the domain."""
    data = gql(
        "query($f: GamesSearchFilter) { games(filter: $f, sort: [{downloads: {direction: DESC}}], count: 10) { nodes { name domainName } } }",
        {"f": {"name": [{"value": query, "op": "WILDCARD"}]}},
    )
    return [
        {"name": g["name"], "domain": g["domainName"]} for g in data["games"]["nodes"]
    ]


@mcp.tool()
def search_mods(
    game: str, query: str, category: str | None = None, count: int = 10
) -> list[dict]:
    """Discover mods for a game (Nexus domain name) whose name matches `query`, most downloaded first."""
    return query_mods(game, "downloads", count, name=query, category=category)


@mcp.tool()
def top_mods(
    game: str, sort: str = "endorsements", category: str | None = None, count: int = 15
) -> list[dict]:
    """Top mods for a game. sort: endorsements | downloads | updatedAt | createdAt. category: exact Nexus category name, e.g. 'User Interface'."""
    return query_mods(game, sort, count, category=category)


@mcp.tool()
def trending_mods(game: str) -> list[dict]:
    """Currently trending mods for a game (needs NEXUS_API_KEY)."""
    key = os.environ.get("NEXUS_API_KEY")
    if not key:
        raise ToolError(
            "NEXUS_API_KEY is not set; trending needs a personal API key. Use top_mods with sort='updatedAt' instead."
        )
    r = httpx.get(
        f"{V1}/games/{game}/mods/trending.json",
        headers={**HEADERS, "apikey": key},
        timeout=30,
    )
    if r.status_code == 404:
        raise ToolError(f"Unknown game domain '{game}'. Use find_game.")
    r.raise_for_status()
    return [
        {
            "name": m.get("name"),
            "id": m["mod_id"],
            "endorsements": m.get("endorsement_count"),
            "summary": (m.get("summary") or "")[:160],
            "url": f"https://www.nexusmods.com/{game}/mods/{m['mod_id']}",
        }
        for m in r.json()
        if m.get("available", True) and not m.get("contains_adult_content")
    ]


@mcp.tool()
def suggest_mods(game: str) -> dict[str, list[dict]]:
    """Essential-mod candidates for a game: the most endorsed mods grouped by category (top 3 each).
    Use this to build a recommended starter mod list / load order for the user."""
    groups = defaultdict(list)
    for m in query_mods(game, "endorsements", 60):
        if len(groups[m["category"] or "Uncategorized"]) < 3:
            groups[m["category"] or "Uncategorized"].append(m)
    return dict(groups)


if __name__ == "__main__":
    if "--check" in sys.argv:
        g = "skyrimspecialedition"
        assert any(x["domain"] == g for x in find_game("skyrim")), "find_game"
        assert search_mods(g, "lighting"), "search_mods"
        assert len(top_mods(g, count=5)) == 5, "top_mods"
        assert top_mods(g, category="User Interface", count=3), "top_mods category"
        assert len(suggest_mods(g)) > 3, "suggest_mods"
        try:
            top_mods("notarealgame")
            raise AssertionError("unknown game should raise")
        except ToolError:
            pass
        if os.environ.get("NEXUS_API_KEY"):
            assert trending_mods(g), "trending_mods"
        print(
            "trending:",
            "checked" if os.environ.get("NEXUS_API_KEY") else "skipped (no key)",
        )
        print("ok")
    else:
        mcp.run()
