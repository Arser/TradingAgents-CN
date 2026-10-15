"""LLM 结论规范化、原文保留及输出校验。无需模型或数据库连接。"""

from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from pydantic import ValidationError

from app.utils.compliance import (
    sanitize_analysis_payload,
    sanitize_brief_points,
    sanitize_display_report_text,
    sanitize_text_block,
)
from app.utils.report_formatter import format_decision
from core.agents.adapters.research_manager_v2 import (
    ResearchManagerOutput,
    ResearchManagerV2,
)
from core.agents.adapters.risk_manager_v2 import (
    FinalTradeDecision,
    RiskAssessmentOutput,
    RiskManagerV2,
)
from core.agents.adapters.trader_v2 import TraderV2
from core.agents.assertion_executor import AssertionExecutor
from core.agents.output_normalization import parse_report_json


class OutputValidationTests(unittest.TestCase):
    def risk_payload(self):
        return {
            "risk_level": "中",
            "risk_score": 0.5,
            "reasoning": "风险仍需观察",
            "investment_adjustment": "审慎",
            "final_trade_decision": {"action": "中性", "confidence": 0.6},
        }

    def research_payload(self):
        return {
            "analysis_view": "中性",
            "confidence": 0.6,
            "risk_score": 0.5,
            "summary": "暂时继续观察",
            "reasoning": "综合已有证据",
        }

    def test_reported_risk_sentence_is_normalized_and_preserved(self):
        payload = self.risk_payload()
        raw = "研究判断暂维持审慎，后续需验证盈利改善能否形成更强支撑。"
        payload["investment_adjustment"] = raw
        payload["risk_level"] = "风险等级为中等风险"
        payload["final_trade_decision"]["action"] = "建议持有"
        original_payload = deepcopy(payload)
        llm = Mock()
        llm.model_copy.return_value = llm
        llm.invoke.side_effect = [SimpleNamespace(content=value) for value in ("审慎", "中", "中性")]
        result, error = RiskManagerV2._validate_risk_assessment(
            SimpleNamespace(_llm=llm), json.dumps(payload, ensure_ascii=False)
        )
        self.assertEqual(llm.invoke.call_count, 3)
        self.assertIsNone(error)
        self.assertEqual(result["investment_adjustment"], "审慎")
        self.assertEqual(result["risk_level"], "中")
        self.assertEqual(result["original_enum_values"]["investment_adjustment"], raw)
        decision = result["final_trade_decision"]
        self.assertEqual(decision["action"], "中性")
        self.assertEqual(decision["original_enum_values"]["action"], "建议持有")
        self.assertEqual(RiskAssessmentOutput(**result).model_dump(), {k: v for k, v in result.items() if k != "original_output_text"})
        self.assertEqual(payload, original_payload)
        formatted = format_decision(decision)
        displayed = sanitize_analysis_payload({"decision": formatted})
        self.assertEqual(displayed["decision"]["original_enum_values"], decision["original_enum_values"])

    def test_only_whitespace_and_quotes_are_normalized_locally(self):
        for raw, expected in [(' "审慎" ', "审慎"), (" ‘中性’ ", "中性"), ("乐观", "乐观")]:
            with self.subTest(raw=raw):
                model = FinalTradeDecision(action=raw, confidence=0.5)
                self.assertEqual(model.action, expected)
        for raw in ["研究判断暂维持审慎", "当前观点为中性", "买入", "SELL", "观望", "**乐观**"]:
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                FinalTradeDecision(action=raw, confidence=0.5)

    def test_ambiguous_negated_conditional_and_incidental_values_are_rejected(self):
        for raw in [
            "审慎乐观", "中性偏乐观", "乐观或审慎", "不是审慎", "不宜乐观",
            "若盈利改善则乐观", "融资客净买入", "不建议买入", "BUYBACK", "未知", "", None,
        ]:
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                FinalTradeDecision(action=raw, confidence=0.5)

    def test_research_adapter_normalizes_and_preserves_text(self):
        payload = self.research_payload()
        payload["analysis_view"] = "当前研究观点为看多"
        payload["summary"] = "融资新闻提到40只股票获得融资客净买入"
        llm = Mock()
        llm.model_copy.return_value = llm
        llm.invoke.return_value = SimpleNamespace(content="乐观")
        result, error = ResearchManagerV2._validate_research_output(
            SimpleNamespace(_llm=llm), "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
        )
        self.assertIsNone(error)
        self.assertEqual(result["analysis_view"], "乐观")
        self.assertEqual(result["original_enum_values"]["analysis_view"], payload["analysis_view"])
        self.assertEqual(result["summary"], payload["summary"])

    def test_canonical_values_remain_unchanged(self):
        payload = self.risk_payload()
        model = RiskAssessmentOutput(**payload)
        self.assertEqual(model.original_enum_values, {})
        self.assertEqual(model.final_trade_decision.original_enum_values, {})
        self.assertEqual(payload, self.risk_payload())

    def test_invalid_structure_and_numeric_ranges_still_fail(self):
        for field, value in [("confidence", 1.1), ("risk_score", -0.1), ("analysis_view", ["乐观"])]:
            payload = self.research_payload()
            payload[field] = value
            with self.subTest(field=field), self.assertRaises(ValidationError):
                ResearchManagerOutput(**payload)
        payload = self.risk_payload()
        del payload["final_trade_decision"]
        with self.assertRaises(ValidationError):
            RiskAssessmentOutput(**payload)
        for text in ["", "not json", "[]"]:
            with self.subTest(text=text):
                result, error = RiskManagerV2._validate_risk_assessment(None, text)
                self.assertIsNone(result)
                self.assertTrue(error)

    def test_valid_enum_never_calls_model(self):
        llm = Mock()
        result, error = ResearchManagerV2._validate_research_output(
            SimpleNamespace(_llm=llm), json.dumps(self.research_payload())
        )
        self.assertIsNone(error)
        llm.invoke.assert_not_called()

    def test_failed_classification_is_pending_and_keeps_report(self):
        for response in ["无法确定", "乐观，因为盈利改善", "", TimeoutError("timeout")]:
            with self.subTest(response=response):
                payload = self.research_payload()
                payload["analysis_view"] = "中性并略偏审慎"
                llm = Mock()
                llm.model_copy.return_value = llm
                if isinstance(response, Exception):
                    llm.invoke.side_effect = response
                else:
                    llm.invoke.return_value = SimpleNamespace(content=response)
                text = json.dumps(payload, ensure_ascii=False)
                result, error = ResearchManagerV2._validate_research_output(SimpleNamespace(_llm=llm), text)
                self.assertIsNone(error)
                self.assertEqual(llm.invoke.call_count, 1)
                self.assertEqual(result["analysis_view"], "待确认")
                self.assertEqual(result["enum_review_status"]["analysis_view"], "待确认")
                self.assertEqual(result["summary"], payload["summary"])
                self.assertEqual(result["original_output_text"], text)
                self.assertEqual(result["original_enum_values"]["analysis_view"], payload["analysis_view"])
                updates = llm.model_copy.call_args.kwargs["update"]
                self.assertEqual(updates["max_retries"], 0)
                self.assertEqual(updates["request_timeout"], 20)
                self.assertEqual(updates["max_tokens"], 256)
                sent = llm.invoke.call_args.args[0]
                self.assertNotIn(payload["summary"], sent[1].content)

    def test_malformed_enum_types_are_classified_once(self):
        for raw in [None, [], {"unexpected": "value"}, 12]:
            with self.subTest(raw=raw):
                payload = self.research_payload()
                payload["analysis_view"] = raw
                result, error = ResearchManagerV2._validate_research_output(None, json.dumps(payload))
                self.assertIsNone(error)
                self.assertEqual(result["analysis_view"], "待确认")
                self.assertEqual(result["original_enum_values"]["analysis_view"], raw)

    def test_structural_errors_do_not_spend_model_tokens(self):
        payload = self.research_payload()
        payload.update(analysis_view="看多", confidence=2)
        llm = Mock()
        result, error = ResearchManagerV2._validate_research_output(SimpleNamespace(_llm=llm), json.dumps(payload))
        self.assertIsNone(result)
        self.assertIn("Schema", error)
        llm.invoke.assert_not_called()

    def test_trailing_commas_are_repaired_without_changing_strings(self):
        text = '{"a": [1,], "text": "保留 ,} 和 ,] 以及 \\"引号\\"",}'
        data, repaired = parse_report_json(text)
        self.assertTrue(repaired)
        self.assertEqual(data["a"], [1])
        self.assertEqual(data["text"], '保留 ,} 和 ,] 以及 "引号"')
        payload = json.dumps(self.risk_payload(), ensure_ascii=False)
        payload = payload[:-1] + ',}'
        result, error = RiskManagerV2._validate_risk_assessment(None, payload)
        self.assertIsNone(error)
        self.assertEqual(result["json_repairs"], ["trailing_comma"])
        self.assertEqual(result["original_output_text"], payload)
        for invalid in ['{"a": 1,,}', '{"a": }', '{"a": "unterminated}']:
            with self.subTest(invalid=invalid), self.assertRaises(json.JSONDecodeError):
                parse_report_json(invalid)

    def test_pending_state_survives_report_formatting(self):
        result = format_decision({"action": "待确认", "reasoning": "原报告正文", "enum_review_status": {"action": "待确认"}, "original_enum_values": {"action": "中性偏审慎"}})
        displayed = sanitize_analysis_payload({"decision": result})["decision"]
        self.assertEqual(displayed["action"], "待确认")
        self.assertEqual(displayed["enum_review_status"], {"action": "待确认"})
        self.assertEqual(displayed["original_enum_values"], {"action": "中性偏审慎"})

    def test_trader_allows_objective_and_recommendation_terms(self):
        text = (
            "## 一句话结论\n融资新闻提到40只股票获得融资客净买入。\n"
            "## 为什么这么看\n看涨、买入、卖出、加仓、减仓、清仓均不触发术语失败。"
        )
        self.assertIsNone(TraderV2._validate_trader_output(None, text))
        self.assertIsNotNone(TraderV2._validate_trader_output(None, ""))
        self.assertIsNotNone(TraderV2._validate_trader_output(None, "只有一句买入建议"))

    def test_legacy_term_assertions_do_not_reject_output(self):
        assertion = SimpleNamespace(terms=["买入", "卖出"])
        self.assertIsNone(AssertionExecutor()._check_term_forbidden(assertion, "建议买入", None))

    def test_display_and_brief_keep_terms_prices_and_factual_flows(self):
        lines = [
            "融资新闻提到40只股票获得融资客净买入",
            "研究员提出买入观点，并给出目标价20元、止损价15元",
            "买入逻辑基于公开披露的盈利增长",
        ]
        self.assertEqual(sanitize_display_report_text("\n".join(lines)), "\n".join(lines))
        self.assertEqual(sanitize_text_block("\n".join(lines)), "\n".join(lines))
        self.assertEqual(sanitize_brief_points(lines), lines)


if __name__ == "__main__":
    unittest.main()
