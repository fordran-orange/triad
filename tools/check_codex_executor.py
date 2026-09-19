"""Read-only remote-protocol smoke check. Does not invoke a model."""

import json
import shutil

from triad.day5a.codex_executor import CodexExecutor, LineProcess


def main():
    with CodexExecutor({"README.md": "# Executor boundary probe"}, guard=lambda: None) as executor:
        app = LineProcess([shutil.which("codex.exe"), "app-server", "--stdio"])
        serial = 0

        def call(method, params):
            nonlocal serial
            serial += 1
            app.send({"id": serial, "method": method, "params": params})
            while True:
                message = app.receive(timeout=20)
                if message.get("id") == serial:
                    if "error" in message:
                        raise RuntimeError(str(message["error"]))
                    return message.get("result")

        try:
            call(
                "initialize",
                {
                    "clientInfo": {"name": "triad_executor_check", "version": "0.1"},
                    "capabilities": {"experimentalApi": True},
                },
            )
            app.send({"method": "initialized", "params": {}})
            print("Initialized", flush=True)
            call(
                "environment/add",
                {
                    "environmentId": executor.environment_id,
                    "execServerUrl": executor.url,
                    "connectTimeoutMs": 10000,
                },
            )
            print("Connected remote executor", flush=True)
            print(json.dumps(call("environment/info", {"environmentId": executor.environment_id})))

        finally:
            app.close()


if __name__ == "__main__":
    main()
