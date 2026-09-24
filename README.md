# nexus-mods-mcp

[![CI](https://github.com/PhantomDave/nexus-mods-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/PhantomDave/nexus-mods-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

An [MCP](https://modelcontextprotocol.io) server that connects Claude (or any MCP client) to [Nexus Mods](https://www.nexusmods.com). Ask it to discover mods, pull top lists, or build a starter mod list for a game, all from live Nexus data.

> "Suggest a starter mod list for Skyrim Special Edition"
> "What are the most downloaded UI mods for Fallout 4?"
> "Find lighting mods for Starfield"

## Tools

| Tool | What it does | API key |
|---|---|:---:|
| `find_game` | Resolve a game name ("fallout") to its Nexus domain (`fallout4`, `newvegas`, …) | – |
| `search_mods` | Discover mods by name, optionally within a category | – |
| `top_mods` | Top list by `endorsements`, `downloads`, `updatedAt` or `createdAt`, optionally by category | – |
| `trending_mods` | What is trending right now | ✅ |
| `suggest_mods` | Most endorsed mods grouped by category (top 3 each), for the model to build a starter list | – |

Every mod is returned with name, category, endorsements, downloads, author, version, last update, a short summary and its Nexus URL. Adult content is filtered out.

Most tools use the public Nexus v2 GraphQL API and need no key. Only `trending_mods` uses the v1 REST API, which needs a [personal API key](https://www.nexusmods.com/settings/api-keys).

## Setup

Requires [uv](https://docs.astral.sh/uv/). Dependencies are declared inline in `server.py` ([PEP 723](https://peps.python.org/pep-0723/)), so there is nothing to install.

```bash
git clone https://github.com/PhantomDave/nexus-mods-mcp.git
cd nexus-mods-mcp
uv run server.py --check   # live smoke test
```

### Claude Code

Open Claude Code in the cloned folder. The bundled `.mcp.json` registers the server, and `NEXUS_API_KEY` is read from your environment. Or add it globally:

```bash
claude mcp add nexus-mods -e NEXUS_API_KEY=your_key -- uv run /absolute/path/to/nexus-mods-mcp/server.py
```

### Claude Desktop and other clients

```json
{
  "mcpServers": {
    "nexus-mods": {
      "command": "uv",
      "args": ["run", "/absolute/path/to/nexus-mods-mcp/server.py"],
      "env": { "NEXUS_API_KEY": "your_key" }
    }
  }
}
```

The key is optional; without it every tool except `trending_mods` works.

## Development

```bash
uvx ruff check . && uvx ruff format --check .
uv run server.py --check
npx @modelcontextprotocol/inspector uv run server.py   # poke the tools interactively
```

CI runs lint and the live smoke test on every push and PR, plus weekly to catch Nexus API changes. Add a `NEXUS_API_KEY` repository secret to include `trending_mods` in the check.

## License

[MIT](LICENSE). Not affiliated with Nexus Mods.
