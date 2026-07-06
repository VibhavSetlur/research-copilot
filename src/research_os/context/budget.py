"""Token-budget accounting for Research-OS context engineering.

Heuristic: ~4 characters per token (GPT-family average).
This module is deliberately dependency-free (stdlib only, no tiktoken).
The heuristic intentionally over-counts slightly — safe for a budget guard.
"""

from __future__ import annotations

import json
from typing import Any


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------


def count_tokens(payload: Any) -> int:
    """Estimate the number of tokens in *payload* using a 4-chars-per-token heuristic.

    Rules:
    - ``None`` or empty string / empty container → 0
    - ``str`` → ``len(payload) // 4``
    - ``dict`` / ``list`` → ``len(json.dumps(payload, default=str)) // 4``
    - anything else → ``len(str(payload)) // 4``

    Always returns at least 1 for non-empty input.
    """
    if payload is None:
        return 0

    if isinstance(payload, str):
        length = len(payload)
    elif isinstance(payload, (dict, list)):
        if not payload:
            return 0
        length = len(json.dumps(payload, default=str))
    else:
        length = len(str(payload))

    if length == 0:
        return 0
    return max(1, length // 4)


# ---------------------------------------------------------------------------
# Budget constants + reporting
# ---------------------------------------------------------------------------

_CATEGORY_ATTRS = (
    "system",
    "protocol",
    "state",
    "memory",
    "user_input",
    "output",
    "overhead",
)


class ContextBudget:
    """Token-budget allocations for each context slot.

    Constants are the public contract — do not change their values without
    updating TOTAL and bumping the package version.
    """

    SYSTEM: int = 2000       # Tool descriptions + mode directives
    PROTOCOL: int = 1000     # Current protocol summary
    STATE: int = 500         # Project state + config
    MEMORY: int = 1500       # Retrieved memory records
    USER_INPUT: int = 4000   # Current user turn
    OUTPUT: int = 3000       # Expected response
    OVERHEAD: int = 1000     # Formatting, envelopes
    TOTAL: int = 13000

    # Map lowercase category names → class attribute names
    _ATTR_MAP: dict[str, str] = {
        "system": "SYSTEM",
        "protocol": "PROTOCOL",
        "state": "STATE",
        "memory": "MEMORY",
        "user_input": "USER_INPUT",
        "output": "OUTPUT",
        "overhead": "OVERHEAD",
    }

    @classmethod
    def report(cls) -> dict[str, Any]:
        """Return the current budget allocation for sys_boot inspection.

        Returns a self-describing dict::

            {
                "categories": {"system": 2000, "protocol": 1000, ...},
                "total": 13000,
                "sum_of_categories": 13000,
                "consistent": True,
            }
        """
        categories: dict[str, int] = {
            key: getattr(cls, attr)
            for key, attr in cls._ATTR_MAP.items()
        }
        sum_of_categories = sum(categories.values())
        return {
            "categories": categories,
            "total": cls.TOTAL,
            "sum_of_categories": sum_of_categories,
            "consistent": sum_of_categories == cls.TOTAL,
        }

    @classmethod
    def check(cls, category: str, payload: Any) -> dict[str, Any]:
        """Count tokens in *payload* and compare against *category*'s cap.

        Args:
            category: One of the 7 category names (case-insensitive).
            payload:  The content to measure.

        Returns:
            A dict with keys: ``category``, ``tokens``, ``cap``,
            ``within_budget`` (bool), ``overflow`` (int, 0 if within budget).

        Raises:
            ValueError: If *category* is not one of the 7 known names.
        """
        key = category.lower()
        attr = cls._ATTR_MAP.get(key)
        if attr is None:
            known = ", ".join(sorted(cls._ATTR_MAP))
            raise ValueError(
                f"Unknown budget category {category!r}. Known: {known}"
            )
        cap: int = getattr(cls, attr)
        tokens = count_tokens(payload)
        overflow = max(0, tokens - cap)
        return {
            "category": key,
            "tokens": tokens,
            "cap": cap,
            "within_budget": tokens <= cap,
            "overflow": overflow,
        }
