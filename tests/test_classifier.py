"""Unit tests for intent classifier."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from analyzer.classifier import IntentClassifier


@pytest.fixture
def clf():
    return IntentClassifier()


def test_keyword_account_trade(clf):
    result = clf.classify_keyword("出抖音千粉号 可开播")
    assert result is not None
    assert "账号" in result[0]


def test_keyword_cheating_brush(clf):
    result = clf.classify_keyword("刷播放量 包上热门")
    assert result is not None
    assert result[0] == "作弊"


def test_keyword_fraud_loan(clf):
    result = clf.classify_keyword("代办贷款 无抵押 黑户可做")
    assert result is not None
    assert result[0] == "诈骗"


def test_keyword_traffic_gambling(clf):
    result = clf.classify_keyword("菠菜平台 真人视讯 百家乐")
    assert result is not None
    assert result[0] == "引流"


def test_keyword_no_match(clf):
    result = clf.classify_keyword("今天天气真好")
    assert result is None


def test_classify_cascade_uses_keyword(clf):
    """When keyword hits, should use keyword method."""
    result = clf.classify("出抖音千粉号 量大优惠")
    assert result["method"].value == "keyword"
    assert result["confidence"] > 0.9
