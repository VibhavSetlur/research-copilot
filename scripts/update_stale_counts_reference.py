from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

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

    sidecars: dict[str, int | None] = {}
    for rel in [
        'src/research_os/protocols/_route_meta.json',
        'src/research_os/protocols/_precondition_meta.json',
        'src/research_os/protocols/_gate_meta.json',
        'src/research_os/protocols/_embeddings_meta.json',
    ]:
        p = root / rel
        if p.exists():
            try:
                sidecars[rel] = len(json.loads(p.read_text(encoding='utf-8')))
            except (OSError, json.JSONDecodeError):
                sidecars[rel] = None
        else:
            sidecars[rel] = None

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
    ]
    for rel, value in counts['sidecars'].items():
        desc = 'generated artifact' if value is None else f'{value} entries'
        lines.append(f"| {rel} | {desc} | generated sidecar |")
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
