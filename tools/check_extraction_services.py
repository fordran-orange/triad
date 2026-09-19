"""Read-only acceptance of the running three-service platform; never prints secrets."""

import json

import httpx
from trading_core.settings import ROOT


def main():
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=30, trust_env=False) as client:
        routes = {
            path: client.get(path).status_code
            for path in (
                "/", "/core", "/triad", "/p2p", "/day2", "/research",
                "/settings/ai-providers", "/assets/record-view.js", "/assets/record-view.css",
            )
        }
        status = client.get("/api/status").raise_for_status().json()
        providers = client.get("/api/providers").raise_for_status().json()
        triad = client.get("/api/day3/dashboard").raise_for_status().json()
        p2p = client.get("/p2p/api/status").raise_for_status().json()
        workers = {
            product: client.get(f"http://127.0.0.1:{port}/health/live").raise_for_status().json()
            for product, port in (("triad", 8101), ("p2p", 8102))
        }
    report = {
        "routes": routes,
        "services": status,
        "workers": workers,
        "providers": [
            {key: agent.get(key) for key in ("agent", "state", "billing_source", "actual_model")}
            for agent in providers["agents"]
        ],
        "provider_gate": providers["gate"],
        "active_provider_runs": len(providers["active_runs"]),
        "triad_relay_accepted": triad["relay_accepted"],
        "p2p": {"mode": p2p["mode"], "exchange": p2p["exchange"], "work_count": len(p2p["work_items"])},
    }
    (ROOT / "logs/extraction-services.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    assert all(code == 200 for code in routes.values())
    assert all(status[key]["status"] == "up" for key in ("backend", "postgres", "timescale", "neo4j", "ollama", "git"))
    assert len(report["providers"]) == 4 and all(a["state"] == "ONLINE" for a in report["providers"])
    assert report["provider_gate"] == "PASS" and report["active_provider_runs"] == 0
    assert report["triad_relay_accepted"]
    assert report["p2p"] == {"mode": "human_directed", "exchange": "CLOSED", "work_count": 0}


if __name__ == "__main__":
    main()
