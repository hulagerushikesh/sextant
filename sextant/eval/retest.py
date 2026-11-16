"""
The two closest rejected ideas, judged on the public sets (milestone 28, item 3).

The rules were written down before any run (`learning/rejected-retest.md`);
this module is those rules as code, so the verdict in the note and on the
results page is computed from `retest.json`, not typed. An idea is adopted
only if it passes on every public set, so a single failing set settles it
and the larger sets need not be run.

Reproduce one candidate run (the control is the committed `public-sets.json`):

    SEXTANT_CHUNK_TOKENS=150 python -m sextant.eval.public_sets --data DIR/nfcorpus
    SEXTANT_EMBEDDER=BAAI/bge-small-en-v1.5 python -m sextant.eval.public_sets --data DIR/fiqa
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

EVAL_DIR = Path(__file__).resolve().parent
SETS = ("nfcorpus", "scifact", "fiqa")  # smallest first
GAIN = 0.03  # what the idea must win by, as in both original rules
TOLERANCE = 0.02  # what any guarded stage may lose, as in the gate


def load(name: str) -> dict[str, Any]:
    return json.loads((EVAL_DIR / name).read_text())


def _delta(control: dict[str, Any], run: dict[str, Any], mode: str) -> float:
    return run["modes"][mode]["ndcg@10"] - control["modes"][mode]["ndcg@10"]


def judge(
    control: dict[str, dict[str, Any]],
    runs: dict[str, dict[str, Any]],
    must_gain: str,
    guarded: tuple[str, ...],
) -> dict[str, Any]:
    """Adopt only if `must_gain` rises by GAIN and no `guarded` stage falls past
    TOLERANCE, on every set. Returns the verdict and the reason for each set."""
    reasons: list[str] = []
    for name in SETS:
        if name not in runs:
            continue
        gain = _delta(control[name], runs[name], must_gain)
        if gain < GAIN:
            reasons.append(f"{name}: {must_gain} {gain:+.3f}, needs +{GAIN:.2f}")
        for mode in guarded:
            drop = _delta(control[name], runs[name], mode)
            if drop < -TOLERANCE:
                reasons.append(f"{name}: {mode} {drop:+.3f}, limit -{TOLERANCE:.2f}")
    complete = all(name in runs for name in SETS)
    if reasons:
        verdict = "rejected"
    elif complete:
        verdict = "adopted"
    else:
        verdict = "undecided"
    return {"verdict": verdict, "reasons": reasons}


RULES = {
    # 150-token passages: the full pipeline must gain; no stage may fall.
    "chunk_150": ("rerank", ("dense", "lexical", "rrf", "rerank")),
    # bge-small: meaning search must gain; the full pipeline may not fall.
    "bge_small": ("dense", ("rerank",)),
}


def verdicts() -> dict[str, dict[str, Any]]:
    control = load("public-sets.json")["sets"]
    candidates = load("retest.json")["candidates"]
    return {
        key: judge(control, candidates[key]["runs"], must_gain, guarded)
        for key, (must_gain, guarded) in RULES.items()
    }
