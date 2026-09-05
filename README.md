# zcode-local

Local ZCode plugin marketplace. Currently ships **hierarchical-supervisor**.

## Install in ZCode

Settings → Plugin Management → Discover → **+** marketplace, then add either:

- GitHub: `LotoLe/zcode-hierarchical-supervisor`
- Local directory: this checkout

Install **hierarchical-supervisor** and start a new session. Entry command: `/hs`.

## Update

If this directory is already your marketplace checkout:

```bash
cd ~/.zcode/cli/plugins/marketplaces/zcode-local
git pull
```

Then start a new ZCode session so agents, hooks, and MCP reload.

Plugin docs: [plugins/hierarchical-supervisor/README.md](plugins/hierarchical-supervisor/README.md)
