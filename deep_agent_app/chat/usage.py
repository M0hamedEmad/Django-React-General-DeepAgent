"""Provider-reported token accounting for one chat turn."""

from langchain_core.messages.ai import add_usage


def token_usage(calls):
    """Aggregate model calls into a JSON-ready turn usage record.

    ``unreported_calls`` is deliberately first-class. Billing code can refuse
    to debit an incomplete turn rather than accidentally charging zero when a
    provider did not return usage metadata.
    """
    total = None
    models = {}
    calls = list(calls)
    for call in calls:
        # Compatible endpoints may report "openai" even for Groq or Ollama.
        # ``provider_id`` is the server-side config choice used for billing.
        provider = call.get("provider_id") or call.get("provider", "unknown")
        model_provider = call.get("provider", "unknown")
        model = call.get("model", "unknown")
        key = (provider, model)
        bucket = models.setdefault(
            key,
            {
                "provider": provider,
                "model_provider": model_provider,
                "model": model,
                "calls": 0,
                "unreported_calls": 0,
                "usage": None,
            },
        )
        bucket["calls"] += 1
        if reported := call.get("usage"):
            total = add_usage(total, reported)
            bucket["usage"] = add_usage(bucket["usage"], reported)
        else:
            bucket["unreported_calls"] += 1

    zero = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    per_model = []
    for bucket in models.values():
        usage = bucket.pop("usage") or zero
        per_model.append({**bucket, **usage})
    per_model.sort(key=lambda item: (item["provider"], item["model"]))
    return {
        **(total or zero),
        "calls": len(calls),
        "unreported_calls": sum(item["unreported_calls"] for item in per_model),
        "models": per_model,
    }
