"""Analysis engine — thin entry point delegating to the state-machine Agent.

The heavy lifting lives in analyzer.state_machine.AnalysisAgent, which uses a
state graph with tool-based decision making instead of a fixed sequential pipeline.

Public API (backward-compatible):
    engine.run(raw_data_id, text, platform) → dict
"""

from loguru import logger


class AnalysisEngine:
    """Entry point for intel analysis. Delegates to the state-machine Agent.

    Maintains the same public API as before the refactoring so callers
    (UI workbench, API server, CLI) need no changes.
    """

    def __init__(self):
        self._agent = None

    @property
    def agent(self):
        if self._agent is None:
            from analyzer.state_machine import agent as _agent
            self._agent = _agent
        return self._agent

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, raw_data_id: int, text: str, platform: str,
            enable_graph_expand: bool = True,
            enable_report: bool = True,
            enable_llm: bool = True) -> dict:
        """Run full analysis pipeline via state-machine Agent.

        Returns a dict matching the PROJECT_PLAN.md AnalyzeResponse format.
        """
        try:
            return self.agent.run(
                raw_data_id=raw_data_id,
                text=text,
                platform=platform,
                enable_graph_expand=enable_graph_expand,
                enable_report=enable_report,
                enable_llm=enable_llm,
            )
        except Exception as exc:
            logger.error(f"Agent run failed [{raw_data_id}]: {exc}")
            raise

    def run_stream(self, raw_data_id: int, text: str, platform: str,
                   enable_graph_expand: bool = True,
                   enable_report: bool = True,
                   enable_llm: bool = True):
        """Generator that yields step-by-step analysis progress for UI think-chain display."""
        try:
            yield from self.agent.run_stream(
                raw_data_id=raw_data_id,
                text=text,
                platform=platform,
                enable_graph_expand=enable_graph_expand,
                enable_report=enable_report,
                enable_llm=enable_llm,
            )
        except Exception as exc:
            logger.error(f"Agent run_stream failed [{raw_data_id}]: {exc}")
            raise

    # ── Health ────────────────────────────────────────────────────────────────

    @property
    def is_degraded(self) -> bool:
        return self.agent.is_degraded

    def reset_circuit(self):
        self.agent.reset_circuit()

    def set_circuit_open(self, open_circuit: bool = True):
        """Manually open/close the circuit breaker (used by API to force degraded mode)."""
        if open_circuit:
            self.agent._circuit_open = True
            self.agent._llm_failure_count = self.agent.CIRCUIT_THRESHOLD
        else:
            self.agent.reset_circuit()


# Singleton — same name, same API, all callers work unchanged
engine = AnalysisEngine()
