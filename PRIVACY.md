# Privacy

`swarm-mcp` is a local Model Context Protocol server that speaks over stdio
to the client that started it. It collects nothing, stores nothing of its
own, and sends nothing anywhere. It has no telemetry, no analytics, no
accounts, and no server operated by the swarm-routing org or anyone else
([ADR-0002](docs/adr/0002-swarm-mcp-is-a-local-read-only-mcp-server.md),
"Trust boundary").

## What the server does

- **No network connection of its own.** `tools/swarm-mcp/swarm_mcp.py` reads
  JSON-RPC from stdin and writes replies to stdout. It opens no socket and
  serves no HTTP.
- **No credentials read, nothing logged.** The server reads no token or
  credential. It passes its environment unchanged to the script a tool
  runs, as a shell would, and never prints or records it.
- **No file written.** The server writes no file. A tool's result is the
  script's own summary, trimmed to `SWARM_MCP_MAX_CHARS`, returned to the
  client and kept nowhere else.

## What the scripts it runs reach

Each tool runs one read-only command of a `swarm-routing/.github` script
through `tools/swarm-mcp/org-tool`. Those scripts reach the network only as
they do when a person runs the same command by hand, with that person's own
permissions:

- **The scripts themselves.** Unless `ORG_TOOLS_DIR` names a local checkout,
  `org-tool` fetches `swarm-routing/.github` with `git` over public HTTPS,
  at the commit this repository's `.github/org-sync.lock` pins (or
  `ORG_TOOLS_REF`). It keeps the snapshot under
  `${XDG_CACHE_HOME:-~/.cache}/swarm-routing/checkouts/` and removes
  snapshots unused for 7 days. That cache is the only thing written to disk.
- **`fidelity_check`, `fidelity_row`, `fidelity_verify`** read the sheet and
  the text files they are given.
- **`protocol_review`** runs `git` on the local repository named.
- **`release_ready`, `release_after`** read GitHub with `gh api`, under the
  user's own `gh` login, and public package indexes over HTTPS (PyPI), as
  `release_check.py` does.
- **`lock_verify`** reads GitHub (`git ls-remote`, the release's public
  assets) to check a lock against its release.

What a script does is that script's behaviour at the pinned commit; its
review happens in `swarm-routing/.github`.

## Questions

Open an issue in this repository. For a security concern, follow
[SECURITY.md](SECURITY.md).
