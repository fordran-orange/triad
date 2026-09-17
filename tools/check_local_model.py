"""Bounded synthetic local inference smoke check, not a quality or authority evaluation."""

import json
import urllib.request

from triad.settings import ROOT, Settings


def main():
    settings = Settings()
    payload = {
        "model": settings.ollama_model,
        "prompt": (
            "Summarize in one sentence: The nightly import processed 120 records. "
            "Two records were rejected because timestamps were missing."
        ),
        "think": True,
        "stream": False,
        "keep_alive": 0,
        "options": {"temperature": 0.6, "num_ctx": 2048, "num_predict": 512},
    }
    request = urllib.request.Request(
        settings.ollama_url.rstrip("/") + "/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.load(response)
    if (
        not result.get("done")
        or result.get("done_reason") != "stop"
        or not result.get("response", "").strip()
    ):
        raise RuntimeError("Local model did not return a complete response within the token limit")
    report = {
        "model": result["model"],
        "completed": result["done"],
        "done_reason": result["done_reason"],
        "response": result["response"],
        "seconds": round(result["total_duration"] / 1_000_000_000, 2),
        "output_tokens": result.get("eval_count"),
        "context_limit": 2048,
        "thinking": True,
        "scope": "synthetic inference smoke check only",
    }
    output = json.dumps(report, indent=2)
    (ROOT / "logs/local-model.latest.json").write_text(output + "\n")
    print(output)


if __name__ == "__main__":
    main()
