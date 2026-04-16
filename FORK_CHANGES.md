# Fork Changes Summary

This fork includes two major improvements for more control:

## 1. Telemetry Control (Opt-In)

**Problem:** Users wanted explicit control over telemetry.

**Solution:** Added `--no-telemetry` flag and `DG_DISABLE_TELEMETRY` environment variable.

### Usage:

```bash
# Disable telemetry for a single run
dgc --no-telemetry /path/to/project
dg-mcp --no-telemetry /path/to/project

# Disable globally via environment
export DG_DISABLE_TELEMETRY=1
dgc .
```

### How it works:

- Telemetry remains opt-in (user prompted on first run)
- `--no-telemetry` flag disables telemetry for that session
- `DG_DISABLE_TELEMETRY=1` environment variable permanently disables for that terminal
- Consent is stored in `~/.dual-graph/identity.json`
- Only error reports are sent (no code, no paths), and only if user opts in

### Changed Files:

- `bin/dual_graph_launch.sh`: Added flag parsing and environment variable check in `_get_telemetry_consent()`

---

## 2. Standalone MCP Server (`dg-mcp`)

**Problem:** No way to run the MCP server without launching Cursor, Claude, Codex, or another IDE.

**Solution:** New `dg-mcp` command that starts the MCP server standalone, useful for:
- Containerized environments
- Custom integrations  
- Remote development
- Running as a service
- Development of MCP clients

### Usage:

```bash
# Start MCP server for current directory
dg-mcp

# Start MCP server for a specific project
dg-mcp /path/to/project

# With custom port
dg-mcp /path/to/project --port 9000

# Disable telemetry
dg-mcp --no-telemetry /path/to/project
```

### Output:

```
[dg-mcp] MCP server running on port 8080
[dg-mcp] Project: /path/to/project
[dg-mcp] Data: /path/to/project/.dual-graph

[dg-mcp] Connection info:
[dg-mcp]   HTTP:  http://127.0.0.1:8080
[dg-mcp]   MCP:   http://127.0.0.1:8080/mcp

[dg-mcp] Press Ctrl+C to stop the server.
```

### New Files:

- `bin/dg-mcp` — Bash launcher for macOS/Linux
- `bin/dg-mcp.cmd` — Batch launcher for Windows
- `bin/dg-mcp.ps1` — PowerShell launcher for Windows

### Changed Files:

- `bin/dual_graph_launch.sh`: Added `mcp-only` mode handling to skip IDE registration and launch

---

## Integration

Both changes are backward compatible:

- Existing `dgc`, `dg`, and `graperoot` commands work unchanged
- Telemetry remains opt-in (default behavior unchanged)
- `dg-mcp` is a new command with no impact on existing workflows

## Testing

```bash
# Test telemetry control
dgc --no-telemetry . --json-schema '{}' << EOF
Tell me about yourself in 10 words
EOF

# Test standalone MCP server
dg-mcp /path/to/your/project
# In another terminal:
curl -X POST http://127.0.0.1:8080/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

---

## Files Modified

1. `bin/dual_graph_launch.sh` — Core launcher (telemetry + mcp-only mode)
2. `bin/dg-mcp` — New bash launcher (executable)
3. `bin/dg-mcp.cmd` — New Windows batch launcher
4. `bin/dg-mcp.ps1` — New Windows PowerShell launcher
5. `README.md` — Added docs for dg-mcp and telemetry

---

## Next Steps (Optional)

- Document `dg-mcp` in Docker examples
- Add `dg-mcp` to install scripts for easier setup
- Consider running `dg-mcp` as a systemd service for production setups
