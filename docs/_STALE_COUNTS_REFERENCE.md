# Stale-count reference

> Do not edit by hand. Regenerate with `python scripts/update_stale_counts_reference.py` or verify with `--check`.

| Item | Current value | Source |
|---|---:|---|
| Active MCP tools | 47 | `research_os.server.TOOL_DEFINITIONS` |
| Protocol YAML files | 161 | `src/research_os/protocols/**/*.yaml` excluding `_*.yaml` |
| Preflight checks | 36 | `scripts/preflight.py` registered checks |
| Pytest gate | collected by `python -m pytest -q` during release gate | tests/ |
| src/research_os/protocols/_route_meta.json | generated artifact | generated sidecar |
| src/research_os/protocols/_precondition_meta.json | generated artifact | generated sidecar |
| src/research_os/protocols/_gate_meta.json | generated artifact | generated sidecar |
| src/research_os/protocols/_embeddings_meta.json | 6 entries | generated sidecar |
