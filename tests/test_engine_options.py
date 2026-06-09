"""Tests for analysis engine option propagation."""

from analyzer.engine import AnalysisEngine


class FakeAgent:
    def __init__(self):
        self.run_kwargs = None
        self.stream_kwargs = None

    def run(self, **kwargs):
        self.run_kwargs = kwargs
        return {"ok": True}

    def run_stream(self, **kwargs):
        self.stream_kwargs = kwargs
        yield {"final": True, "result": {"ok": True}}


def test_engine_passes_enable_llm_to_agent_run():
    engine = AnalysisEngine()
    fake_agent = FakeAgent()
    engine._agent = fake_agent

    result = engine.run(1, "text", "weibo", enable_llm=False)

    assert result == {"ok": True}
    assert fake_agent.run_kwargs["enable_llm"] is False
    assert fake_agent.run_kwargs["enable_embedding"] is False
    assert fake_agent.run_kwargs["enable_roberta"] is True
    assert fake_agent.run_kwargs["analysis_mode"] == ""


def test_engine_passes_enable_llm_to_agent_run_stream():
    engine = AnalysisEngine()
    fake_agent = FakeAgent()
    engine._agent = fake_agent

    steps = list(engine.run_stream(1, "text", "weibo", enable_llm=False))

    assert steps[-1]["final"] is True
    assert fake_agent.stream_kwargs["enable_llm"] is False
    assert fake_agent.stream_kwargs["enable_embedding"] is False
    assert fake_agent.stream_kwargs["enable_roberta"] is True
    assert fake_agent.stream_kwargs["analysis_mode"] == ""


def test_engine_passes_enable_embedding_to_agent():
    engine = AnalysisEngine()
    fake_agent = FakeAgent()
    engine._agent = fake_agent

    result = engine.run(1, "text", "telegram", enable_embedding=True)
    steps = list(engine.run_stream(1, "text", "telegram", enable_embedding=True))

    assert result == {"ok": True}
    assert steps[-1]["final"] is True
    assert fake_agent.run_kwargs["enable_embedding"] is True
    assert fake_agent.stream_kwargs["enable_embedding"] is True


def test_engine_passes_enable_roberta_to_agent():
    engine = AnalysisEngine()
    fake_agent = FakeAgent()
    engine._agent = fake_agent

    result = engine.run(1, "text", "telegram", enable_roberta=False)
    steps = list(engine.run_stream(1, "text", "telegram", enable_roberta=False))

    assert result == {"ok": True}
    assert steps[-1]["final"] is True
    assert fake_agent.run_kwargs["enable_roberta"] is False
    assert fake_agent.stream_kwargs["enable_roberta"] is False


def test_engine_passes_analysis_mode_to_agent():
    engine = AnalysisEngine()
    fake_agent = FakeAgent()
    engine._agent = fake_agent

    result = engine.run(1, "text", "telegram", analysis_mode="快速筛查")
    steps = list(engine.run_stream(1, "text", "telegram", analysis_mode="扩线研判"))

    assert result == {"ok": True}
    assert steps[-1]["final"] is True
    assert fake_agent.run_kwargs["analysis_mode"] == "快速筛查"
    assert fake_agent.stream_kwargs["analysis_mode"] == "扩线研判"
