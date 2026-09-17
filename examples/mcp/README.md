# MCP client configurations

Two client configurations for the `equilibria` MCP server (`ovf-mcp`). The server, its
tools and its limits are described in [docs/mcp.md](../../docs/mcp.md).

| File | Client | Where it goes |
|---|---|---|
| `claude_desktop_config.json` | Claude Desktop | macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`. Windows: `%APPDATA%\Claude\claude_desktop_config.json` |
| `cursor_mcp.json` | Cursor | `.cursor/mcp.json` in a project, or `~/.cursor/mcp.json` for every project |

Both files have the same `mcpServers` shape. Before using one:

1. Install the server from a checkout: `python -m pip install -e '.[mcp]'` inside the
   repository's virtual environment.
2. Replace `/ABSOLUTE/PATH/TO/personal/.venv/bin/ovf-mcp` with the absolute path of the
   `ovf-mcp` script in that environment. On Windows it is `.venv\Scripts\ovf-mcp.exe`.
   A client does not activate the virtual environment, so a bare `ovf-mcp` works only if
   that script is on the client's `PATH`.
3. Decide on `OVF_MCP_ALLOWED_ROOTS`. As shipped, it names one placeholder directory, so
   `ocf_import` and `ocf_export` refuse every path until you replace it with a real one.
   Several directories are separated by `:` on macOS and Linux and `;` on Windows.
   Deleting the `env` entry lets the OCF tools use any path the server process can reach.
   No other tool reads or writes files.
4. If you already have a configuration file, merge the `equilibria` entry into its
   existing `mcpServers` object instead of replacing the file.
5. Restart the client.

The files are plain JSON with no comments, because both clients parse them as JSON.
Check an edited copy with `python -m json.tool <file>`.

For Claude Code, no file is needed:

```bash
claude mcp add equilibria -- /ABSOLUTE/PATH/TO/personal/.venv/bin/ovf-mcp
```
