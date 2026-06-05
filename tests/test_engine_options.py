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


def test_engine_passes_enable_llm_to_agent_run_stream():
    engine = AnalysisEngine()
    fake_agent = FakeAgent()
    engine._agent = fake_agent

    steps = list(engine.run_stream(1, "text", "weibo", enable_llm=False))

    assert steps[-1]["final"] is True
    assert fake_agent.stream_kwargs["enable_llm"] is False
