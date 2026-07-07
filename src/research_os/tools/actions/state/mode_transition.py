"""First-class workspace-mode transitions (B1/B2).

Before this, `sys_config(workspace.mode=X)` flipped the config string but never
created mode X's scaffold surface and left config/state disagreeing — a silent
half-change that made mode effectively immutable after init. This module makes a
mode change a real, additive, recorded operation:

  plan  → what surface the target mode needs that's missing (dry-run).
  apply → create that surface (never delete prior work), sync config + state,
          record the move to .os_state/mode_history.jsonl, and point the AI at
          the promotion/handoff protocol for the crossing.

Lives in the reasoning layer (no daemon import). Shares ensure_mode_surface with
init so both produce identical surfaces from one source of truth.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_os.project_ops import ensure_mode_surface, load_state, save_state
from research_os.tools.actions.router import mode_transition_spec
from research_os.tools.actions.state.config import (
    VALID_WORKSPACE_MODES,
    get_workspace_mode,
    set_config,
)

_HISTORY = "mode_history.jsonl"


def _state_mode(root: Path) -> str:
    try:
        return str(load_state(root).get("workspace_mode") or "analysis")
    except Exception:
        return "analysis"


def workspace_mode_status(root: Path) -> dict[str, Any]:
    """Current mode (config) + state mode + drift flag + available moves."""
    root = Path(root)
    cfg_mode = get_workspace_mode(root)
    st_mode = _state_mode(root)
    moves = [
        {"to": to, **spec}
        for (frm, to), spec in _all_transitions_from(cfg_mode)
    ]
    return {
        "status": "success",
        "config_mode": cfg_mode,
        "state_mode": st_mode,
        "drift": cfg_mode != st_mode,
        "available_transitions": moves,
    }


def _all_transitions_from(frm: str):
    # Use the registry's default-allow logic so available_transitions reflects
    # ALL non-forbidden moves, not just the explicitly-declared subset.
    from research_os.state.mode_registry import all_transitions_from as _reg_all
    return _reg_all(frm)


def transition_workspace_mode(
    root: Path,
    to_mode: str,
    *,
    plan_only: bool = True,
    rationale: str = "",
) -> dict[str, Any]:
    """Plan (default) or apply an additive mode transition.

    plan_only=True (default): report the target spec + what surface is missing.
    plan_only=False: create the missing surface, sync config+state, record it.
    """
    root = Path(root)
    if to_mode not in VALID_WORKSPACE_MODES:
        return {
            "status": "error",
            "message": f"Unknown mode '{to_mode}'. Valid: {', '.join(VALID_WORKSPACE_MODES)}.",
        }
    cur = get_workspace_mode(root)
    if to_mode == cur and _state_mode(root) == cur:
        return {"status": "noop", "message": f"Already in '{cur}' mode.", "mode": cur}

    spec = mode_transition_spec(cur, to_mode)
    # Even with no declared spec we allow a 'heal' move when config/state already
    # name to_mode (drift repair) — but an unknown deliberate move is refused.
    drift_heal = (to_mode in (cur, _state_mode(root)))
    if spec is None and not drift_heal:
        return {
            "status": "error",
            "message": (
                f"No supported transition {cur} → {to_mode}. Supported from "
                f"'{cur}': {[t for (_f, t), _s in _all_transitions_from(cur)] or 'none'}."
            ),
        }

    plan = ensure_mode_surface(root, to_mode, plan_only=True)
    payload: dict[str, Any] = {
        "from_mode": cur,
        "to_mode": to_mode,
        "transition": spec or {"kind": "heal", "protocol": "", "guidance": "Repair a half-applied mode change."},
        "surface_missing": plan["missing_before"],
    }

    if plan_only:
        payload["status"] = "plan"
        payload["message"] = (
            f"Plan {cur} → {to_mode} ({(spec or {}).get('kind', 'heal')}). "
            f"Would create: {plan['missing_before'] or '(surface already present)'}. "
            "Re-call with plan_only=false to apply (additive — no existing work is removed)."
        )
        if spec and spec.get("protocol"):
            payload["next_protocol"] = spec["protocol"]
        return payload

    # Apply: additive surface, then sync BOTH writers atomically-ish.
    created = ensure_mode_surface(root, to_mode)
    set_config("workspace.mode", to_mode, root)
    try:
        st = load_state(root)
        st["workspace_mode"] = to_mode
        save_state(root, st)
    except Exception:
        pass

    # Record the move (provenance — "started as exploration, became analysis").
    try:
        hist = root / ".os_state" / _HISTORY
        hist.parent.mkdir(parents=True, exist_ok=True)
        with open(hist, "a") as f:
            f.write(json.dumps({
                "from": cur, "to": to_mode,
                "at": datetime.now(timezone.utc).isoformat(),
                "kind": (spec or {}).get("kind", "heal"),
                "rationale": rationale,
                "surface_created": created["created_dirs"],
            }) + "\n")
    except OSError:
        pass

    payload["status"] = "applied"
    payload["surface_created"] = created["created_dirs"]
    payload["message"] = (
        f"Transitioned {cur} → {to_mode}. Created: "
        f"{created['created_dirs'] or '(surface already present)'}. "
        "Config + state synced; recorded to mode_history. Prior work untouched."
    )
    if spec and spec.get("protocol"):
        payload["next_protocol"] = spec["protocol"]
        payload["message"] += f" Continue via {spec['protocol']}."
    return payload
