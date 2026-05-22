"""Unit tests for entity extractor."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from analyzer.entity_extractor import EntityExtractor


@pytest.fixture
def extractor():
    return EntityExtractor()


def test_extract_phone(extractor):
    entities = extractor.extract_regex("联系我 13812345678")
    phones = [e for e in entities if e["entity_type"].value == "phone"]
    assert len(phones) >= 1
    assert "13812345678" in phones[0]["entity_value"]


def test_extract_wechat(extractor):
    entities = extractor.extract_regex("加我微信 abc12345 详聊")
    wechats = [e for e in entities if e["entity_type"].value == "wechat"]
    assert len(wechats) >= 1


def test_extract_qq(extractor):
    entities = extractor.extract_regex("私我QQ 12345678")
    qqs = [e for e in entities if e["entity_type"].value == "qq"]
    assert len(qqs) >= 1


def test_extract_url(extractor):
    entities = extractor.extract_regex("详情看 https://example.com/page")
    urls = [e for e in entities if e["entity_type"].value == "url"]
    assert len(urls) >= 1


def test_extract_multiple_entities(extractor):
    entities = extractor.extract_regex(
        "出号 微信 test123 手机 13912345678 QQ 987654321 链接 t.me/xxx"
    )
    types = {e["entity_type"].value for e in entities}
    assert "wechat" in types
    assert "phone" in types
    assert "qq" in types


def test_extract_dict_known_slang(extractor):
    extractor.load_slang_dict({"刷单": "虚假交易提升销量"})
    entities = extractor.extract_dict("招聘刷单 日结")
    assert len(entities) >= 1
    assert entities[0]["entity_value"] == "刷单"


def test_extract_empty_text(extractor):
    entities = extractor.extract_regex("")
    assert entities == []


def test_extract_l1_l2_only_no_llm(extractor):
    """Degraded extraction should skip LLM entirely."""
    extractor.load_slang_dict({"刷单": "虚假交易提升销量"})
    entities = extractor.extract_l1_l2_only(
        "微信 test123 招聘刷单 日结 电话 13812345678"
    )
    types = {e["entity_type"].value for e in entities}
    methods = {e["extraction_method"].value for e in entities}
    assert "wechat" in types
    assert "phone" in types
    assert "slang" in types
    assert "llm" not in methods  # LLM must not be used
