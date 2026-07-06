"""Research-OS memory subsystem: durable semantic memory + hypothesis ledger.

Public API
----------
EvidenceLink        – typed pointer from a hypothesis to a piece of evidence
Hypothesis          – falsifiable scientific claim with status tracking
MemoryRecord        – durable per-project memory entry
MemoryRetriever     – semantic (or keyword-fallback) retrieval over records
search_all_projects – cross-project ranked search
"""

from .models import EvidenceLink, Hypothesis, MemoryRecord
from .retriever import MemoryRetriever, search_all_projects

__all__ = [
    "EvidenceLink",
    "Hypothesis",
    "MemoryRecord",
    "MemoryRetriever",
    "search_all_projects",
]
