"""Per-call model copies without hidden SDK retries or shared-state mutations."""

from typing import Any


def single_attempt_model(llm: Any, **overrides: Any) -> Any:
    updates = {"max_retries": 0, **overrides}
    root = getattr(llm, "root_client", None)
    if root is not None and hasattr(root, "with_options"):
        options = {"max_retries": 0}
        if "request_timeout" in overrides:
            options["timeout"] = overrides["request_timeout"]
        root = root.with_options(**options)
        updates.update(root_client=root, client=root.chat.completions)
    return llm.model_copy(update=updates) if hasattr(llm, "model_copy") else llm
