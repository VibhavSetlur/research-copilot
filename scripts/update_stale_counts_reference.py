from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from importlib import import_module


REPO_ROOT = Path('/scratch/vsetlur/Research-OS')
REFERENCE_PATH = REPO_ROOT / 'docs' / '_STALE_COUNTS_REFERENCE.md'


def generate_counts(root: Path) -> dict[str, Any]:
    sys.path.insert(0, str(root / 'src'))
    from research_os.server import TOOL_DEFINITIONS

    protocols_dir = root / 'src' / 'research_os' / 'protocols'
    protocol_files = [
        p for p in protocols_dir.rglob('*.yaml')
        if not p.name.startswith('_') and 'light' not in p.parts
    ]

    preflight = (root / 'scripts' / 'preflight.py').read_text(encoding='utf-8')
    checks = [line for line in preflight.splitlines() if 'tally.check(' in line]

    sidecars: dict[str, dict[str, int | str | None]] = {}
    bundle_path = root / 'src' / 'research_os' / 'protocols' / '_protocols.bundle'
    try:
        msgpack = import_module('msgpack')
    except ImportError:
        msgpack = None
    if bundle_path.exists() and msgpack is not None:
        try:
            bundle = msgpack.unpackb(bundle_path.read_bytes(), raw=False)
            sidecars['_protocols.bundle'] = {
                'protocols': len(bundle.get('protocols', {}) or {}),
                'gates': len(bundle.get('gates', []) or []),
                'preconditions': sum(len(v) for v in (bundle.get('preconditions', {}) or {}).values()),
                'source_hash': bundle.get('source_hash'),
            }
        except (OSError, ValueError, TypeError):
            sidecars['_protocols.bundle'] = {'protocols': None, 'gates': None, 'preconditions': None, 'source_hash': None}
    else:
        sidecars['_protocols.bundle'] = {'protocols': None, 'gates': None, 'preconditions': None, 'source_hash': None}

    for rel in ['src/research_os/protocols/_embeddings.npz', 'src/research_os/protocols/_embeddings_meta.json']:
        p = root / rel
        if not p.exists():
            sidecars[rel] = {'summary': 'missing'}
            continue
        if rel.endswith('.json'):
            try:
                data = json.loads(p.read_text(encoding='utf-8'))
                sidecars[rel] = {'summary': f"keys={len(data)} schema={data.get('schema_version')}"}
            except (OSError, json.JSONDecodeError):
                sidecars[rel] = {'summary': 'unreadable'}
        else:
            sidecars[rel] = {'summary': 'binary artifact'}

    return {
        'tools_active': len(TOOL_DEFINITIONS),
        'protocol_yaml_files': len(protocol_files),
        'preflight_checks': len(checks),
        'preflight_check_names': checks,
        'sidecars': sidecars,
    }


def render_reference(root: Path | None = None) -> str:
    base = root or REPO_ROOT
    counts = generate_counts(base)
    lines = [
        '# Stale-count reference',
        '',
        '> Do not edit by hand. Regenerate with `python scripts/update_stale_counts_reference.py` or verify with `--check`.',
        '',
        '| Item | Current value | Source |',
        '|---|---:|---|',
        f"| Active MCP tools | {counts['tools_active']} | `research_os.server.TOOL_DEFINITIONS` |",
        f"| Protocol YAML files | {counts['protocol_yaml_files']} | `src/research_os/protocols/**/*.yaml` excluding `_*.yaml` |",
        f"| Preflight checks | {counts['preflight_checks']} | `scripts/preflight.py` registered checks |",
        "| Pytest gate | collected by `python -m pytest -q` during release gate | tests/ |",
        "| `_protocols.bundle` | compiled routing / gate / precondition bundle | `scripts/build_protocols.py` |",
        "| `_embeddings.npz` | generated semantic-router vectors | `scripts/build_embeddings.py` |",
        "| `_embeddings_meta.json` | generated embedding metadata | `scripts/build_embeddings.py` |",
    ]
    bundle = counts['sidecars']['_protocols.bundle']
    lines.append(
        f"| `_protocols.bundle` detail | protocols={bundle['protocols']}, gates={bundle['gates']}, "
        f"preconditions={bundle['preconditions']} | source_hash={bundle['source_hash']} |"
    )
    return '\n'.join(lines) + '\n'


def write_reference(root: Path | None = None) -> Path:
    base = root or REPO_ROOT
    REFERENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE_PATH.write_text(render_reference(base), encoding='utf-8')
    return REFERENCE_PATH


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    check = '--check' in args
    if check:
        args = [arg for arg in args if arg != '--check']
    if args:
        print('usage: python scripts/update_stale_counts_reference.py [--check]', file=sys.stderr)
        return 2

    expected = render_reference()
    if check:
        if not REFERENCE_PATH.exists():
            print(f'missing {REFERENCE_PATH.relative_to(REPO_ROOT)}', file=sys.stderr)
            return 1
        actual = REFERENCE_PATH.read_text(encoding='utf-8')
        if actual != expected:
            print(f'stale {REFERENCE_PATH.relative_to(REPO_ROOT)}', file=sys.stderr)
            return 1
        return 0

    write_reference()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
