# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=2", "httpx"]
# ///
"""Nexus Mods MCP server: discover mods, top lists, suggestion data, and (Premium) file downloads."""

import os
import sys
from collections import defaultdict
from pathlib import Path

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

GQL = "https://api.nexusmods.com/v2/graphql"
V1 = "https://api.nexusmods.com/v1"
HEADERS = {"Application-Name": "nexus-mods-mcp", "Application-Version": "0.2.0"}
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


def v1(path: str, what: str) -> httpx.Response:
    """GET a v1 REST endpoint with the personal API key."""
    key = os.environ.get("NEXUS_API_KEY")
    if not key:
        raise ToolError(
            f"NEXUS_API_KEY is not set; {what} needs a personal API key "
            "(https://www.nexusmods.com/settings/api-keys)."
        )
    r = httpx.get(f"{V1}{path}", headers={**HEADERS, "apikey": key}, timeout=30)
    if r.status_code == 404:
        raise ToolError(
            f"Not found: {path}. Check the game domain (find_game) and ids."
        )
    if r.status_code in (401, 403):
        raise ToolError(f"Nexus refused {what}: {r.json().get('message', r.text)}")
    r.raise_for_status()
    return r


@mcp.tool()
def trending_mods(game: str) -> list[dict]:
    """Currently trending mods for a game (needs NEXUS_API_KEY)."""
    r = v1(f"/games/{game}/mods/trending.json", "trending")
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


def mod_files(game: str, mod_id: int) -> list[dict]:
    files = v1(f"/games/{game}/mods/{mod_id}/files.json", "listing files").json()
    return [
        f
        for f in files["files"]
        if f.get("category_name") not in ("OLD_VERSION", "ARCHIVED", "REMOVED", None)
    ]


@mcp.tool()
def list_files(game: str, mod_id: int) -> list[dict]:
    """Downloadable files of a mod (main, update, optional, misc; old versions hidden), newest first.
    Use the file_id with download_file. Needs NEXUS_API_KEY."""
    files = sorted(
        mod_files(game, mod_id), key=lambda f: f["uploaded_timestamp"], reverse=True
    )
    return [
        {
            "file_id": f["file_id"],
            "name": f.get("name"),
            "file_name": f.get("file_name"),
            "category": f.get("category_name"),
            "primary": bool(f.get("is_primary")),
            "version": f.get("version"),
            "size_mb": round(
                (f.get("size_in_bytes") or f.get("size_kb", 0) * 1024) / 2**20, 1
            ),
            "uploaded": (f.get("uploaded_time") or "")[:10],
            "description": (f.get("description") or "")[:160],
        }
        for f in files
    ]


@mcp.tool()
def download_file(
    game: str, mod_id: int, file_id: int | None = None, dest_dir: str | None = None
) -> dict:
    """Download a mod file to disk (Nexus Premium + NEXUS_API_KEY). Without file_id the primary MAIN file is used.
    dest_dir defaults to $NEXUS_DOWNLOAD_DIR or ~/Downloads/nexus-mods/<game>. Returns the saved path; it does
    not install the mod. Only download what the user asked for: no bulk downloads."""
    files = mod_files(game, mod_id)
    if file_id is None:
        mains = [f for f in files if f["category_name"] == "MAIN"]
        if not mains:
            raise ToolError("No MAIN file on this mod; pick a file_id from list_files.")
        f = max(
            mains, key=lambda f: (bool(f.get("is_primary")), f["uploaded_timestamp"])
        )
    else:
        f = next((x for x in files if x["file_id"] == file_id), None)
        if f is None:
            raise ToolError(
                f"file_id {file_id} not found on mod {mod_id}; use list_files."
            )

    links = v1(
        f"/games/{game}/mods/{mod_id}/files/{f['file_id']}/download_link.json",
        "the download (direct API downloads need Nexus Premium)",
    ).json()
    if not links:
        raise ToolError("Nexus returned no download mirrors for this file.")

    base = (
        dest_dir
        or os.environ.get("NEXUS_DOWNLOAD_DIR")
        or f"~/Downloads/nexus-mods/{game}"
    )
    out_dir = Path(base).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    # basename only: a file name from the API must never escape dest_dir
    out = out_dir / Path(f.get("file_name") or f"{mod_id}-{f['file_id']}").name
    part = out.with_name(out.name + ".part")

    with httpx.stream(
        "GET", links[0]["URI"], headers=HEADERS, timeout=60, follow_redirects=True
    ) as r:
        r.raise_for_status()
        with part.open("wb") as fh:
            for chunk in r.iter_bytes(1 << 20):
                fh.write(chunk)
    part.replace(out)
    return {
        "path": str(out),
        "size_mb": round(out.stat().st_size / 2**20, 1),
        "file_id": f["file_id"],
        "name": f.get("name"),
        "version": f.get("version"),
        "mirror": links[0].get("name"),
    }


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
            assert list_files(g, 12604), "list_files"  # SkyUI
        print(
            "trending/list_files:",
            "checked" if os.environ.get("NEXUS_API_KEY") else "skipped (no key)",
        )
        print("ok")
    else:
        mcp.run()
