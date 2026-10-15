"""Summarize node failures and pending fields without discarding completed reports."""

import json


def collect_execution_issues(result: dict | None) -> list[dict[str, str]]:
    if not isinstance(result, dict):
        return []
    issues = []

    def add(field, status, message):
        issue = {"field": field, "status": status, "message": str(message)}
        if issue not in issues:
            issues.append(issue)

    def inspect(data, prefix=""):
        if not isinstance(data, dict):
            return
        for field, value in data.items():
            path = prefix + field
            if field.endswith("_validation_status") and value in ("failed", "pending_review"):
                base = field.removesuffix("_validation_status")
                message = data.get(base + "_validation_error") or data.get(base + "_validation_warning") or "输出校验需检查"
                add(prefix + base, value, message)
            elif field in ("_node_errors", "degraded_nodes") and isinstance(value, dict):
                for node, error in value.items():
                    add(str(node), "failed", error)
            elif isinstance(value, dict) and value.get("success") is False:
                add(path, "failed", value.get("error") or value.get("error_message") or "节点执行失败")
            elif field in ("investment_plan", "risk_assessment", "final_trade_decision", "decision"):
                if isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except (ValueError, TypeError):
                        continue
                if isinstance(value, dict):
                    for key, status in (value.get("enum_review_status") or {}).items():
                        if status == "待确认":
                            add(path + "." + key, "pending_review", "字段待确认，原报告已保留")
                    nested = value.get("final_trade_decision")
                    if isinstance(nested, dict):
                        inspect({"final_trade_decision": nested}, path + ".")

    for issue in result.get("execution_issues", []):
        if isinstance(issue, dict) and all(key in issue for key in ("field", "status", "message")):
            add(issue["field"], issue["status"], issue["message"])
    inspect(result)
    inspect(result.get("state"))
    return issues
