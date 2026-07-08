# Stale-count reference

> Do not edit by hand. Regenerate with `python scripts/update_stale_counts_reference.py` or verify with `--check`.

| Item | Current value | Source |
|---|---:|---|
| Active MCP tools | 47 | `research_os.server.TOOL_DEFINITIONS` |
| Protocol YAML files | 161 | `src/research_os/protocols/**/*.yaml` excluding `_*.yaml` |
| Preflight checks | 37 | `scripts/preflight.py` registered checks |
| Pytest gate | collected by `python -m pytest -q` during release gate | tests/ |
| `_protocols.bundle` | compiled routing / gate / precondition bundle | `scripts/build_protocols.py` |
| `_embeddings.npz` | generated semantic-router vectors | `scripts/build_embeddings.py` |
| `_embeddings_meta.json` | generated embedding metadata | `scripts/build_embeddings.py` |
| `_protocols.bundle` detail | protocols=161, gates=10, preconditions=19 | source_hash=4c6105550ea0c647820f7db88bbdf1528a8cc872c8e6b25b13c2937c4f1694cd |
