"""Transport attempt counts, pending output and upstream failure preservation."""

import json
import logging
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from langchain_openai import ChatOpenAI

from app.utils.execution_issues import collect_execution_issues
from core.agents.adapters.research_manager_v2 import ResearchManagerV2
from core.agents.adapters.risk_manager_v2 import RiskManagerV2
from core.agents.base import is_retryable_llm_error
from core.agents.manager import ManagerAgent
from core.agents.output_normalization import _enum_request


class OutputRecoveryTests(unittest.TestCase):
    def test_transport_makes_exactly_one_attempt_and_preserves_original_client(self):
        for status in [200, 401, 429, 500]:
            with self.subTest(status=status):
                calls = []

                def handle(request):
                    calls.append(request)
                    if status != 200:
                        return httpx.Response(status, json={"error": {"message": "test failure"}})
                    return httpx.Response(200, json={
                        "id": "test", "object": "chat.completion", "created": 0, "model": "gpt-6.1-sol",
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": "审慎"}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
                    })

                with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
                    llm = ChatOpenAI(model="gpt-6.1-sol", api_key="test-placeholder", base_url="https://example.invalid/v1", max_retries=3, timeout=180, http_client=transport, reasoning_effort="high")
                    if status == 200:
                        self.assertEqual(_enum_request(llm, "action", "原则维持审慎", ("乐观", "审慎", "中性")), "审慎")
                    else:
                        with self.assertRaises(Exception):
                            _enum_request(llm, "action", "原则维持审慎", ("乐观", "审慎", "中性"))
                    self.assertEqual(len(calls), 1)
                    payload = json.loads(calls[0].content)
                    self.assertEqual(payload["reasoning_effort"], "low")
                    self.assertEqual(payload.get("max_completion_tokens", payload.get("max_tokens")), 256)
                    self.assertEqual(calls[0].extensions["timeout"]["read"], 20)
                    self.assertEqual(llm.max_retries, 3)
                    self.assertEqual(llm.root_client.max_retries, 3)
                    self.assertEqual(llm.reasoning_effort, "high")

    def test_pending_enum_does_not_fail_risk_report(self):
        payload = {"risk_level": "中", "risk_score": 0.5, "reasoning": "保留原文", "investment_adjustment": "不明确", "final_trade_decision": {"action": "乐观与审慎并存", "confidence": 0.5}}
        text = json.dumps(payload, ensure_ascii=False)
        agent = object.__new__(RiskManagerV2)
        agent._llm = None
        agent._run_assertions = lambda **kwargs: SimpleNamespace(violations=[], has_error_violation=False)
        agent._record_trace_validation = lambda **kwargs: None
        with patch.object(ManagerAgent, "execute", return_value={"risk_assessment": text}):
            result = agent.execute({})
        self.assertEqual(result["risk_assessment_validation_status"], "pending_review")
        self.assertEqual(result["final_trade_decision"]["action"], "待确认")
        self.assertIn("保留原文", result["risk_assessment"])
        self.assertEqual(result["risk_debate_state"]["judge_decision"], text)

    def test_pending_enum_does_not_fail_research_report(self):
        text = json.dumps({"analysis_view": "不明确", "confidence": 0.5, "risk_score": 0.5, "summary": "正文摘要", "reasoning": "原报告正文"}, ensure_ascii=False)
        agent = object.__new__(ResearchManagerV2)
        agent._llm = None
        agent._run_delegated_research_agents = lambda state: {}
        agent._run_assertions = lambda **kwargs: SimpleNamespace(violations=[], has_error_violation=False)
        agent._record_trace_validation = lambda **kwargs: None
        with patch.object(ManagerAgent, "execute", return_value={"investment_plan": text}):
            result = agent.execute({})
        self.assertEqual(result["investment_plan_validation_status"], "pending_review")
        self.assertIn("原报告正文", result["investment_plan"])

    def test_upstream_authentication_errors_are_not_json_errors(self):
        error = {"investment_plan": {"success": False, "error": "401 authentication error"}}
        agent = object.__new__(ResearchManagerV2)
        agent._run_delegated_research_agents = lambda state: {}
        with patch.object(ManagerAgent, "execute", return_value=error):
            self.assertEqual(agent.execute({}), error)

    def test_task_issues_include_execution_validation_and_pending(self):
        result = {"state": {"sector_report": {"success": False, "error": "401 authentication"}, "risk_assessment_validation_status": "failed", "risk_assessment_validation_error": "invalid JSON", "investment_plan": json.dumps({"enum_review_status": {"analysis_view": "待确认"}})}}
        issues = collect_execution_issues(result)
        self.assertEqual(len(issues), 3)
        self.assertEqual({item["status"] for item in issues}, {"failed", "pending_review"})
        self.assertEqual(collect_execution_issues({"execution_issues": issues}), issues)
        self.assertEqual(collect_execution_issues({"state": {"news_report": "净买入"}}), [])

    def test_authentication_errors_are_not_retryable_but_timeouts_are(self):
        self.assertFalse(is_retryable_llm_error("Error code: 401 - authentication failed; rate limit header"))
        self.assertTrue(is_retryable_llm_error("Request timed out."))


if __name__ == "__main__":
    unittest.main()
