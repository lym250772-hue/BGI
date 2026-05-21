"""Unit tests for cleaning pipeline."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from cleaner.pipeline import CleaningPipeline


@pytest.fixture
def pipeline():
    return CleaningPipeline()


def test_normalize_strips_html(pipeline):
    assert pipeline.normalize("<p>Hello</p>") == "Hello"


def test_normalize_collapses_whitespace(pipeline):
    assert pipeline.normalize("a   b\n\nc") == "a b c"


def test_normalize_preserves_numbers(pipeline):
    result = pipeline.normalize("QQ 12345678")
    assert "12345678" in result


def test_simhash_deterministic(pipeline):
    h1 = pipeline.compute_simhash("出抖音千粉号 可开播")
    h2 = pipeline.compute_simhash("出抖音千粉号 可开播")
    assert h1 == h2


def test_simhash_different_for_different_text(pipeline):
    h1 = pipeline.compute_simhash("出抖音千粉号 可开播")
    h2 = pipeline.compute_simhash("今天天气真好适合出去玩")
    assert h1 != h2


def test_hamming_distance_same(pipeline):
    h = "a1b2c3d4e5f6a7b8"
    assert pipeline.hamming_distance(h, h) == 0


def test_hamming_distance_small_for_similar_text(pipeline):
    h1 = pipeline.compute_simhash("出抖音千粉号 可开播 量大优惠")
    h2 = pipeline.compute_simhash("出抖音千粉号 可开播 量大从优")
    dist = pipeline.hamming_distance(h1, h2)
    assert dist < 20  # similar text should have low hamming distance


def test_is_noise_empty(pipeline):
    assert pipeline.is_noise("")[0] is True


def test_is_noise_too_short(pipeline):
    assert pipeline.is_noise("ab")[0] is True


def test_is_noise_valid_text(pipeline):
    assert pipeline.is_noise("出抖音千粉号 可开播 要的私")[0] is False


def test_mark_priority_high_risk(pipeline):
    assert pipeline.mark_priority("刷单兼职 日结") == "high"


def test_mark_priority_normal(pipeline):
    assert pipeline.mark_priority("今天天气不错") == "normal"


def test_full_pipeline_keep_valid(pipeline):
    result = pipeline.process("出号千粉 可开播 量大优惠 刷单 私我")
    assert result["should_discard"] is False
    assert result["priority"] == "high"  # "出号" matches high risk


def test_full_pipeline_discard_short(pipeline):
    result = pipeline.process("OK")
    assert result["should_discard"] is True
