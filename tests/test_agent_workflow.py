from bughound_agent import BugHoundAgent
from llm_client import MockClient


def test_workflow_runs_in_offline_mode_and_returns_shape():
    agent = BugHoundAgent(client=None)  # heuristic-only
    code = "def f():\n    print('hi')\n    return True\n"
    result = agent.run(code)

    assert isinstance(result, dict)
    assert "issues" in result
    assert "fixed_code" in result
    assert "risk" in result
    assert "logs" in result

    assert isinstance(result["issues"], list)
    assert isinstance(result["fixed_code"], str)
    assert isinstance(result["risk"], dict)
    assert isinstance(result["logs"], list)
    assert len(result["logs"]) > 0


def test_offline_mode_detects_print_issue():
    agent = BugHoundAgent(client=None)
    code = "def f():\n    print('hi')\n    return True\n"
    result = agent.run(code)

    assert any(issue.get("type") == "Code Quality" for issue in result["issues"])


def test_offline_mode_proposes_logging_fix_for_print():
    agent = BugHoundAgent(client=None)
    code = "def f():\n    print('hi')\n    return True\n"
    result = agent.run(code)

    fixed = result["fixed_code"]
    assert "logging" in fixed
    assert "logging.info(" in fixed


def test_mock_client_forces_llm_fallback_to_heuristics_for_analysis():
    # MockClient returns non-JSON for analyzer prompts, so agent should fall back.
    agent = BugHoundAgent(client=MockClient())
    code = "def f():\n    print('hi')\n    return True\n"
    result = agent.run(code)

    assert any(issue.get("type") == "Code Quality" for issue in result["issues"])
    # Ensure we logged the fallback path
    assert any("Falling back to heuristics" in entry.get("message", "") for entry in result["logs"])


class _BadSeverityClient:
    """LLM stub that returns valid JSON but with an unknown severity value."""

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if "Return ONLY valid JSON" in system_prompt:
            return '[{"type": "Bug", "severity": "CRITICAL", "msg": "something bad"}]'
        # fixer — return something minimal
        return "def f():\n    pass\n"


def test_llm_issue_with_unknown_severity_gets_normalized():
    """Unknown severity values should be mapped to 'Medium' by the validator."""
    agent = BugHoundAgent(client=_BadSeverityClient())
    code = "def f():\n    pass\n"
    result = agent.run(code)

    issues = result["issues"]
    assert len(issues) >= 1
    assert issues[0]["severity"] == "Medium"


class _EmptyMsgClient:
    """LLM stub that returns JSON issues with empty messages."""

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if "Return ONLY valid JSON" in system_prompt:
            return '[{"type": "Bug", "severity": "High", "msg": ""}]'
        return "def f():\n    pass\n"


def test_llm_issues_with_empty_msgs_trigger_heuristic_fallback():
    """Issues with empty messages should be filtered out; if none remain,
    the agent should fall back to heuristics."""
    agent = BugHoundAgent(client=_EmptyMsgClient())
    code = "def f():\n    print('hi')\n    return True\n"
    result = agent.run(code)

    # Heuristic fallback should detect the print statement
    assert any(issue.get("type") == "Code Quality" for issue in result["issues"])
    assert any("Falling back to heuristics" in entry.get("message", "") for entry in result["logs"])
