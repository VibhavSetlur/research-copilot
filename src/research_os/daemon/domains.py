"""Domain profiles — make the whole system field-aware (Phase 1.16).

The protocol library is deliberately mostly ``domain: [any]`` — generic
scaffolds for reasoning that work across fields. That breadth is a
strength, but it leaves a gap: a chemist, an economist, and a historian
each deserve a system that *knows* what their project looks like — what
files matter, what languages and tools are idiomatic, what artifacts are
the real deliverables, what reproducibility means in that field.

Hand-authoring 50 protocols per field does not scale and is the wrong
abstraction. Instead this module adds a thin, declarative **domain
profile** layer the daemon owns. A profile is a small descriptor:

    - id / label                 — the field
    - aliases                    — names a researcher might use
    - signals                    — how to AUTO-DETECT it from a project
                                   (file globs, marker files, languages)
    - languages                  — idiomatic languages, best-first
    - artifacts                  — what the real deliverables look like
    - reproducibility            — what "reproducible" means here
    - notes                      — one-line orientation for the AI

One profile makes the ENTIRE existing protocol library field-aware for
that domain: the generic ``[any]`` protocols inherit sensible defaults,
the router can bias, and any transport (CLI / daemon / dashboard) can
surface "this looks like a <field> project; here's what I'll assume."

Adding a field is a ~30-line entry here, not 50 protocols. This is the
daemon getting smarter, not protocol sprawl.

Pure stdlib. No daemon-internal imports (keeps the dependency arrow
clean and lets the reasoning layer read profiles too if it wants).
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DomainProfile:
    """A declarative descriptor for one research field."""

    id: str
    label: str
    aliases: tuple[str, ...] = ()
    # Auto-detection signals.
    file_globs: tuple[str, ...] = ()      # e.g. "*.R", "*.ipynb"
    marker_files: tuple[str, ...] = ()    # e.g. "DESCRIPTION", "environment.yml"
    keywords: tuple[str, ...] = ()        # appear in researcher_config domain/text
    # Field defaults.
    languages: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    reproducibility: str = ""
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "aliases": list(self.aliases),
            "languages": list(self.languages),
            "artifacts": list(self.artifacts),
            "reproducibility": self.reproducibility,
            "notes": self.notes,
        }


# ── built-in registry ────────────────────────────────────────────────
# Deliberately broad: STEM, life sciences, social science, humanities,
# and the cross-cutting "data/ML" field. Each is a starting point a
# project can override via researcher_config; the value is in covering
# the SHAPE of many fields, not exhaustively modelling one.
_PROFILES: tuple[DomainProfile, ...] = (
    DomainProfile(
        id="computational_biology",
        label="Computational biology / bioinformatics",
        aliases=("compbio", "bioinformatics", "genomics", "systems_biology"),
        file_globs=("*.fasta", "*.fa", "*.fastq", "*.vcf", "*.gff", "*.sbml",
                    "*.nwk", "Snakefile", "*.nf"),
        marker_files=("environment.yml", "Snakefile", "nextflow.config"),
        keywords=("biology", "genomics", "bioinformatics", "proteomics",
                  "metabolomics", "sequenc"),
        languages=("python", "R", "bash", "nextflow", "snakemake"),
        artifacts=("sequence alignments", "phylogenetic trees", "models (SBML)",
                   "figures", "processed datasets"),
        reproducibility="pinned conda env + workflow DAG (Snakemake/Nextflow) "
                        "+ versioned reference data + seeds",
        notes="Pipelines dominate over single jobs; reference-data versions "
              "and tool versions are first-class provenance.",
    ),
    DomainProfile(
        id="data_science_ml",
        label="Data science / machine learning",
        aliases=("ml", "machine_learning", "deep_learning", "ai", "datascience"),
        file_globs=("*.ipynb", "*.pt", "*.onnx", "*.parquet", "*.tfrecord",
                    "requirements.txt", "*.pkl"),
        marker_files=("requirements.txt", "pyproject.toml", "environment.yml"),
        keywords=("machine learning", "deep learning", "neural", "model",
                  "dataset", "benchmark"),
        languages=("python", "julia"),
        artifacts=("trained models", "metrics/benchmarks", "learning curves",
                   "checkpoints", "ablation tables"),
        reproducibility="pinned deps + fixed seeds + recorded hyperparameters "
                        "+ dataset hashes + hardware notes",
        notes="Experiments compare against baselines; seeds and "
              "hyperparameters are the provenance that matters most.",
    ),
    DomainProfile(
        id="physical_sciences",
        label="Physics / chemistry / materials / engineering",
        aliases=("physics", "chemistry", "materials", "engineering",
                 "physical_sciences"),
        file_globs=("*.m", "*.f90", "*.f", "*.cpp", "*.cu", "*.inp", "*.cif",
                    "*.xyz", "*.h5"),
        marker_files=("CMakeLists.txt", "Makefile", "Project.toml"),
        keywords=("physics", "chemistry", "materials", "simulation", "quantum",
                  "molecular", "engineering", "finite element"),
        languages=("python", "C++", "fortran", "julia", "matlab"),
        artifacts=("simulation outputs", "spectra", "structures", "figures",
                   "numerical tables"),
        reproducibility="recorded compiler/toolchain + input decks + solver "
                        "tolerances + mesh/grid + seeds for stochastic runs",
        notes="Heavy compute; HPC/SLURM common. Input decks and solver "
              "settings are the reproducibility surface.",
    ),
    DomainProfile(
        id="social_sciences",
        label="Social science / economics / psychology",
        aliases=("economics", "psychology", "sociology", "polisci",
                 "political_science", "social_science"),
        file_globs=("*.dta", "*.sav", "*.do", "*.R", "*.Rmd", "*.csv"),
        marker_files=("DESCRIPTION", "renv.lock"),
        keywords=("economic", "psycholog", "sociolog", "survey", "regression",
                  "causal", "policy", "political"),
        languages=("R", "python", "stata"),
        artifacts=("regression tables", "survey instruments", "figures",
                   "replication packages"),
        reproducibility="preregistration + analysis plan + pinned R/Stata env "
                        "+ codebook + de-identified data",
        notes="Identification strategy and preregistration matter more than "
              "raw compute; replication packages are the deliverable.",
    ),
    DomainProfile(
        id="qualitative_research",
        label="Qualitative / mixed-methods research",
        aliases=("qualitative", "ethnography", "grounded_theory",
                 "mixed_methods", "interview"),
        file_globs=("*.docx", "*.txt", "*.vtt", "*.srt", "*.md"),
        marker_files=(),
        keywords=("qualitative", "interview", "ethnograph", "grounded theory",
                  "thematic", "coding", "focus group"),
        languages=("python", "R"),
        artifacts=("coded transcripts", "codebooks", "thematic memos",
                   "audit trails"),
        reproducibility="codebook + inter-coder agreement + audit trail "
                        "+ de-identified transcripts (PII redacted)",
        notes="Reproducibility is the audit trail, not re-execution. PII "
              "redaction is mandatory before anything leaves the workspace.",
    ),
    DomainProfile(
        id="humanities",
        label="Humanities (history, literature, philosophy, philology)",
        aliases=("history", "literature", "philosophy", "philology",
                 "digital_humanities", "classics"),
        file_globs=("*.tex", "*.typ", "*.bib", "*.xml", "*.tei"),
        marker_files=(),
        keywords=("history", "literature", "literary", "philosoph",
                  "philolog", "rhetoric", "close reading", "archive"),
        languages=("python",),
        artifacts=("essays/monographs (non-IMRAD)", "critical editions",
                   "annotated corpora", "bibliographies"),
        reproducibility="apparatus + provenance of sources/editions + "
                        "transcription conventions; argument, not experiment",
        notes="Output is a sustained ARGUMENT, not a report. IMRAD is the "
              "wrong shape; the essay/monograph form leads.",
    ),
    DomainProfile(
        id="clinical_health",
        label="Clinical / health / epidemiology",
        aliases=("clinical", "health", "epidemiology", "medicine",
                 "public_health", "biostatistics"),
        file_globs=("*.sas", "*.R", "*.dta", "*.csv", "*.xpt"),
        marker_files=("renv.lock", "DESCRIPTION"),
        keywords=("clinical", "epidemiolog", "trial", "cohort", "patient",
                  "biostatist", "public health", "survival"),
        languages=("R", "SAS", "python"),
        artifacts=("CONSORT/STROBE-compliant reports", "survival curves",
                   "forest plots", "statistical analysis plans"),
        reproducibility="SAP locked before unblinding + reporting-guideline "
                        "compliance (CONSORT/STROBE) + de-identified data",
        notes="Reporting guidelines and a pre-locked analysis plan are the "
              "spine; PHI must never leave the workspace.",
    ),
    DomainProfile(
        id="geo_environmental",
        label="Earth / environmental / geospatial science",
        aliases=("geoscience", "environmental", "geospatial", "climate",
                 "ecology", "remote_sensing"),
        file_globs=("*.tif", "*.tiff", "*.nc", "*.shp", "*.geojson", "*.grib",
                    "*.hdf"),
        marker_files=("environment.yml",),
        keywords=("climate", "environment", "ecolog", "geospatial", "remote "
                  "sensing", "earth", "hydrolog", "atmospher"),
        languages=("python", "R", "julia"),
        artifacts=("maps", "raster/vector layers", "time-series figures",
                   "model outputs (NetCDF)"),
        reproducibility="pinned geo stack (GDAL/proj versions) + CRS recorded "
                        "+ data provenance/DOIs + seeds",
        notes="Coordinate reference systems and data provenance/DOIs are "
              "easy to lose and critical to record.",
    ),
)

# A neutral fallback when nothing matches — never returns None.
GENERIC = DomainProfile(
    id="generic",
    label="General research (field not yet detected)",
    languages=("python", "R", "bash"),
    artifacts=("figures", "tables", "processed datasets", "reports"),
    reproducibility="pinned environment + recorded inputs + seeds + provenance",
    notes="No strong field signal detected; using neutral defaults. Set "
          "`domain:` in inputs/researcher_config.yaml to specialize.",
)


def all_profiles() -> list[DomainProfile]:
    """Every built-in profile (excludes the generic fallback)."""
    return list(_PROFILES)


def get_profile(domain_id: str | None) -> DomainProfile:
    """Resolve a domain id/alias/keyword to a profile. Never raises.

    Matching is case-insensitive and tolerant: exact id, then alias,
    then a keyword/substring match either direction. Falls back to
    GENERIC when nothing matches or input is empty.
    """
    if not domain_id:
        return GENERIC
    needle = str(domain_id).strip().lower()
    if not needle:
        return GENERIC
    for p in _PROFILES:
        if needle == p.id.lower():
            return p
    for p in _PROFILES:
        if needle in (a.lower() for a in p.aliases):
            return p
    # Loose: the configured name contains or is contained by a known token.
    for p in _PROFILES:
        tokens = (p.id, *p.aliases, *p.keywords)
        for t in tokens:
            tl = t.lower()
            if tl in needle or needle in tl:
                return p
    return GENERIC


@dataclass
class DetectionResult:
    """Outcome of auto-detecting a project's domain."""

    profile: DomainProfile
    confidence: float                     # 0.0 (declared/fallback) .. 1.0
    source: str                           # "declared" | "detected" | "fallback"
    scores: dict[str, int] = field(default_factory=dict)
    matched_signals: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.as_dict(),
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "scores": dict(self.scores),
            "matched_signals": list(self.matched_signals),
        }


def _declared_domain(root: Path) -> str | None:
    """Read ``domain`` from inputs/researcher_config.yaml (best-effort)."""
    try:
        import yaml
    except Exception:
        return None
    for rel in ("inputs/researcher_config.yaml", "researcher_config.yaml"):
        path = root / rel
        if path.exists():
            try:
                cfg = yaml.safe_load(path.read_text()) or {}
            except Exception:
                return None
            dom = cfg.get("domain")
            if isinstance(dom, list) and dom:
                return str(dom[0])
            if isinstance(dom, str) and dom.strip():
                return dom
            return None
    return None


def _scan_files(root: Path, limit: int = 4000) -> list[str]:
    """Collect a bounded sample of project file names (relative).

    Bounded so detection never walks a huge tree. Skips dotdirs and the
    daemon's own state/cache directories.
    """
    skip = {".git", ".os_state", "__pycache__", "node_modules", ".venv",
            "venv", ".mypy_cache", ".ruff_cache", "env"}
    out: list[str] = []
    try:
        for p in root.rglob("*"):
            if len(out) >= limit:
                break
            parts = set(p.parts)
            if parts & skip:
                continue
            if p.is_file():
                out.append(p.name)
    except Exception:
        pass
    return out


def detect(root: str | Path) -> DetectionResult:
    """Infer a project's domain. Declared config wins; else score signals.

    Resolution order:
      1. ``domain:`` declared in researcher_config -> confidence 1.0.
      2. Otherwise score every profile by marker files + file-glob hits
         over a bounded scan, pick the best -> confidence by margin.
      3. Nothing -> GENERIC fallback, confidence 0.0.

    Never raises.
    """
    root = Path(root)

    declared = _declared_domain(root)
    if declared:
        prof = get_profile(declared)
        if prof.id != "generic":
            return DetectionResult(prof, 1.0, "declared",
                                   {prof.id: 1}, [f"config.domain={declared}"])

    names = _scan_files(root)
    if not names:
        return DetectionResult(GENERIC, 0.0, "fallback")

    scores: dict[str, int] = {}
    matched: dict[str, list[str]] = {}
    name_set = set(names)
    for p in _PROFILES:
        score = 0
        hits: list[str] = []
        for marker in p.marker_files:
            if marker in name_set:
                score += 3                # marker files are strong signals
                hits.append(marker)
        for glob in p.file_globs:
            n = sum(1 for nm in names if fnmatch.fnmatch(nm, glob))
            if n:
                score += min(n, 5)        # cap any single glob's contribution
                hits.append(f"{glob}×{n}")
        if score:
            scores[p.id] = score
            matched[p.id] = hits

    if not scores:
        return DetectionResult(GENERIC, 0.0, "fallback")

    best_id = max(scores, key=lambda k: scores[k])
    best = scores[best_id]
    total = sum(scores.values())
    # Confidence = best score's share of all signal, dampened so a lone
    # weak signal never reads as certain.
    confidence = round(min(0.95, (best / total) * (1 - 1 / (best + 1))), 3)
    prof = get_profile(best_id)
    return DetectionResult(prof, confidence, "detected", scores,
                           matched.get(best_id, []))
