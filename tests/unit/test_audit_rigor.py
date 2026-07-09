"""3.2.9 — scientific-rigor fixes to the statistical audit gates.

Locks the methodology corrections: claim-grounding integer-exact + CI/p-value
exclusion (A1/A2), power test-family awareness + numeric coercion (A3/C1),
E-value scale conversion (A5).
"""
from __future__ import annotations

import tempfile
from pathlib import Path


from research_os.tools.actions.audit.claim_grounding import (
    _claim_grounded,
    extract_claims,
)


def _root():
    return Path(tempfile.mkdtemp())


# -- A1: integer claims match EXACTLY (no relative tolerance) -----------------


def test_integer_claim_requires_exact_match():
    # A hallucinated N=2456 must NOT "ground" to a real 2469 (0.5% off).
    assert _claim_grounded(2456.0, {2469.0}, 0.01, is_int=True) is False
    assert _claim_grounded(2456.0, {2456.0}, 0.01, is_int=True) is True


def test_float_claim_keeps_relative_tolerance():
    # Genuine floats still match within 1%.
    assert _claim_grounded(0.84, {0.838}, 0.01) is True


# -- A2: CI levels + p-value thresholds are not extracted as claims -----------


def test_ci_level_and_pvalue_threshold_excluded():
    p = _root() / "paper.md"
    p.write_text("AUROC 0.84 (95% CI 0.79-0.89), p<0.001, on N=2456 patients.\n")
    toks = {c["token"] for c in extract_claims(p)}
    assert "95%" not in toks          # CI confidence level excluded
    assert "0.001" not in toks        # p-value threshold excluded
    assert {"0.84", "0.79", "0.89", "2456"} <= toks  # real estimates kept


def test_pvalue_guard_does_not_eat_unrelated_numbers():
    p = _root() / "paper.md"
    p.write_text("The pipeline ran step < 5 phases and 3 groups.\n")
    toks = {c["token"] for c in extract_claims(p)}
    assert "5" in toks and "3" in toks  # 'step <' must NOT match the p-value guard


def test_integer_claims_flagged_is_int():
    p = _root() / "paper.md"
    p.write_text("We enrolled 2456 patients with AUROC 0.84.\n")
    by_tok = {c["token"]: c for c in extract_claims(p)}
    assert by_tok["2456"]["is_int"] is True
    assert by_tok["0.84"]["is_int"] is False


# -- v3.6.0: power gate VERIFIES a recorded justification (does not compute) --


def _write(root, name, text):
    p = root / name
    p.write_text(text)
    return name


def test_power_verifies_complete_justification():
    from research_os.tools.actions.audit.audit import audit_power
    r = _root()
    fp = _write(
        r, "power.md",
        "# Power analysis\n"
        "Test: two-sample t-test.\n"
        "Effect size d=0.5, taken from the Smith 2021 pilot study.\n"
        "alpha = 0.05, target power = 0.80.\n"
        "Required n = 64 per group; we enrolled 70 per group.\n"
        "Conclusion: the study is adequately powered for d>=0.5.\n",
    )
    res = audit_power(fp, r)
    assert res["status"] == "success"
    assert not res["missing"]


def test_power_flags_missing_elements():
    from research_os.tools.actions.audit.audit import audit_power
    r = _root()
    # No effect size, no power target, no test family.
    fp = _write(r, "power.md", "We used alpha 0.05 and n=30.\n")
    res = audit_power(fp, r)
    assert res["status"] == "warning"
    assert res["missing"]  # names what is absent


def test_power_flags_effect_size_without_source():
    from research_os.tools.actions.audit.audit import audit_power
    r = _root()
    # Effect size present but pulled from thin air (no pilot / prior / SESOI).
    fp = _write(
        r, "power.md",
        "Two-sample t-test, effect size d=0.5, alpha 0.05, "
        "power 0.80, n=64 per group.\n",
    )
    res = audit_power(fp, r)
    # Recorded but the provenance note fires (effect size needs a source).
    assert res["status"] == "warning"
    assert any("source" in n.lower() or "provenance" in n.lower()
               or "pilot" in n.lower() for n in res["notes"])


def test_power_does_not_compute_anything():
    from research_os.tools.actions.audit.audit import audit_power
    r = _root()
    fp = _write(
        r, "power.md",
        "Test: ANOVA. Effect f=0.25 from prior literature (Jones 2019). "
        "alpha=0.05, power=0.80, n=52 per cell.\n",
    )
    res = audit_power(fp, r)
    # No computed power figure is returned — the gate only verifies recording.
    assert "power" not in res.get("report", {})
    assert "recorded" in res


def test_power_handler_ignores_legacy_numeric_args():
    import json

    import research_os.server as srv
    r = _root()
    _write(
        r, "power.md",
        "Two-sample t-test, d=0.5 from the pilot, alpha 0.05, "
        "power 0.80, n=64 per group.\n",
    )
    # Legacy stringified numeric args must NOT crash — accepted + ignored.
    out = srv._handle_tool_call(
        "tool_audit",
        {"scope": "step", "dimension": "power", "filepath": "power.md",
         "effect_size": "0.5", "alpha": "0.05", "n": "30"},
        r,
    )
    env = json.loads(out[0].text)
    assert env["status"] in ("success", "warning")  # no TypeError crash


def test_assumptions_verifies_recorded_diagnostics():
    from research_os.tools.actions.audit.audit import audit_assumptions
    r = _root()
    fp = _write(
        r, "diagnostics.md",
        "# Model diagnostics\n"
        "Shapiro-Wilk on residuals: W=0.99, p=0.4 — no evidence against "
        "normality.\n"
        "Breusch-Pagan: p=0.6 — homoscedastic.\n"
        "Durbin-Watson = 2.0 — no autocorrelation.\n"
        "VIF all < 2 — no multicollinearity.\n"
        "Cook's distance: no influential points.\n",
    )
    res = audit_assumptions(fp, r)
    assert res["status"] == "success"
    assert "normality" in res["recorded"]


def test_assumptions_flags_violation_without_response():
    from research_os.tools.actions.audit.audit import audit_assumptions
    r = _root()
    fp = _write(
        r, "diagnostics.md",
        "Breusch-Pagan p=0.001 — residuals are heteroscedastic and the "
        "normality assumption is violated.\n",
    )
    res = audit_assumptions(fp, r)
    # Violation mentioned, no response recorded -> warns.
    assert res["status"] == "warning"
    assert res["notes"]


def test_assumptions_raw_csv_is_not_a_record():
    from research_os.tools.actions.audit.audit import audit_assumptions
    r = _root()
    fp = _write(r, "residuals.csv", "residual\n0.1\n-0.2\n0.05\n")
    res = audit_assumptions(fp, r)
    assert res["status"] == "warning"  # data dump, no interpretation


def test_assumptions_does_not_run_any_test():
    from research_os.tools.actions.audit.audit import audit_assumptions
    r = _root()
    fp = _write(
        r, "diagnostics.md",
        "Ran Shapiro-Wilk, Levene, Breusch-Pagan; interpretation recorded; "
        "used HC3 robust standard errors in response to mild "
        "heteroscedasticity.\n",
    )
    res = audit_assumptions(fp, r)
    # No statistic is ever computed by the gate — it only reports what it found.
    assert "W" not in str(res.get("report", {}))
    assert "recorded" in res


# -- A5: E-value scale conversion -------------------------------------------


def test_evalue_converts_common_outcome_or_to_rr():
    from research_os.tools.actions.audit.audit import audit_evalue
    r = _root()
    res = audit_evalue(4.0, r, effect_measure="or")  # RR ≈ sqrt(4) = 2.0
    assert abs(res["risk_ratio"] - 2.0) < 0.01
    assert res["scale_note"]


def test_evalue_rr_default_unchanged():
    from research_os.tools.actions.audit.audit import audit_evalue
    r = _root()
    res = audit_evalue(2.0, r)
    assert abs(res["risk_ratio"] - 2.0) < 0.01
    assert res["effect_measure"] == "rr"


def test_evalue_rare_outcome_uses_value_directly():
    from research_os.tools.actions.audit.audit import audit_evalue
    r = _root()
    res = audit_evalue(3.0, r, effect_measure="or", rare_outcome=True)
    assert abs(res["risk_ratio"] - 3.0) < 0.01  # OR≈RR for rare outcomes
