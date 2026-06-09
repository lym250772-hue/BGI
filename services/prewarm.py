"""Prewarm analysis models before demos or latency benchmarks."""

from __future__ import annotations

import time


def _elapsed(start: float) -> float:
    return round(time.perf_counter() - start, 3)


def prewarm_analysis_models(include_embedding: bool = False) -> dict:
    """Load local models and vector collections once in the current process.

    Streamlit and the benchmark script run inside a long-lived Python process.
    Loading RoBERTa or the sentence embedding model on the first request makes
    that first request look much slower than the steady-state pipeline. This
    helper lets demos pay the cold-start cost before the analyst clicks analyze.
    """
    result: dict[str, dict] = {}

    start = time.perf_counter()
    try:
        from analyzer.classifier import classifier
        _ = classifier.roberta
        result["classifier"] = {"ok": True, "seconds": _elapsed(start)}
    except Exception as exc:
        result["classifier"] = {"ok": False, "seconds": _elapsed(start), "error": str(exc)}

    if include_embedding:
        start = time.perf_counter()
        try:
            from analyzer.state_machine import agent
            agent._load_embedding_model()
            result["embedding"] = {"ok": True, "seconds": _elapsed(start)}
        except Exception as exc:
            result["embedding"] = {"ok": False, "seconds": _elapsed(start), "error": str(exc)}

        start = time.perf_counter()
        try:
            from storage.milvus_store import milvus
            result["milvus"] = {"ok": milvus.healthcheck(), "seconds": _elapsed(start)}
        except Exception as exc:
            result["milvus"] = {"ok": False, "seconds": _elapsed(start), "error": str(exc)}

    return result

