"""Host-owned text workspace tools. All file operations run in the offline sandbox.

The broker never exposes a host path, credentials, a shell, or container options.
Writes are exported proposals and require the existing independent review flow.
"""

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from trading_core.contracts import FileChange
from trading_core.providers.isolation import MAX_BYTES, OfflineSandbox, safe_path
from trading_core.security import ensure_no_secret


class BoundedTools:
    def __init__(self, files, *, writable=(), guard=lambda: None, max_calls=30):
        if (
            not isinstance(files, dict)
            or len(files) > 64
            or not all(isinstance(v, str) for v in files.values())
            or sum(len(v.encode()) for v in files.values()) > MAX_BYTES
            or type(max_calls) is not int
            or not 1 <= max_calls <= 30
        ):
            raise ValueError("Invalid bounded workspace")
        self.files = {safe_path(k): v for k, v in files.items()}
        self.original = dict(self.files)
        self.writable = tuple(safe_path(p) for p in writable)
        self.guard = guard
        self.max_calls = max_calls
        self.calls = []
        self.denials = 0
        self.sandbox = OfflineSandbox()
        self.lock = threading.Lock()
        ensure_no_secret(self.files)

    def cancel(self):
        self.sandbox.cancel()

    def call(self, name, arguments):
        with self.lock:
            self.guard()
            if len(self.calls) + self.denials >= self.max_calls:
                raise PermissionError("Tool budget exhausted")
            try:
                if not isinstance(arguments, dict):
                    raise TypeError("Invalid tool arguments")
                path = safe_path(arguments.get("path"))
                if name == "read_file":
                    if set(arguments) != {"path"} or path not in self.files:
                        raise PermissionError("File not supplied to this run")
                    argv = ["cat", "--", path]
                elif name == "propose_file_change":
                    content = arguments.get("content")
                    if (
                        set(arguments) != {"path", "content"}
                        or not isinstance(content, str)
                        or len(content.encode()) > 12000
                        or not any(path.startswith(p + "/") for p in self.writable)
                        or (path not in self.files and len(self.files) >= 3)
                    ):
                        raise PermissionError("Proposal exceeds the write grant")
                    candidate = {**self.files, path: content}
                    if sum(len(v.encode()) for v in candidate.values()) > MAX_BYTES:
                        raise PermissionError("Workspace exceeds byte budget")
                    ensure_no_secret(content)
                    argv = [
                        "python",
                        "-I",
                        "-c",
                        (
                            "import pathlib,sys; p=pathlib.Path(sys.argv[1]); "
                            "p.parent.mkdir(parents=True,exist_ok=True); "
                            "p.write_text(sys.argv[2],encoding='utf-8')"
                        ),
                        path,
                        content,
                    ]
                else:
                    raise PermissionError("Unknown tool")
                result = self.sandbox.run(
                    argv, self.files, writable=self.writable, timeout=15, guard=self.guard
                )
                if result.status != "EXITED" or result.exit_code:
                    raise RuntimeError("Isolated file operation failed")
                self.guard()
                self.files.update(result.files)
                self.calls.append({"tool": name, "path": path, "boundary": result.boundary})
                return (
                    result.stdout
                    if name == "read_file"
                    else "Proposal staged for independent review."
                )
            except Exception:
                self.denials += 1
                raise

    def changes(self):
        return tuple(
            FileChange(path=p, content=v)
            for p, v in self.files.items()
            if self.original.get(p) != v
        )

    def definitions(self):
        tools = [
            {
                "name": "read_file",
                "description": "Read an explicitly supplied sandbox text file.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
            }
        ]
        if self.writable:
            tools.append(
                {
                    "name": "propose_file_change",
                    "description": "Stage a text file in the sandbox for independent review; never changes the host.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                        "required": ["path", "content"],
                        "additionalProperties": False,
                    },
                }
            )
        return tools


class ToolServer:
    """Minimal sessionless MCP HTTP endpoint on loopback, with an unguessable URL."""

    def __init__(self, broker):
        self.broker = broker
        self.path = "/" + secrets.token_urlsafe(32)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                self.send_error(405)

            def do_POST(self):
                self.connection.settimeout(20)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 65536:
                        raise ValueError("Invalid body size")
                    body = self.rfile.read(length)
                    if self.path != owner.path or self.headers.get("Origin"):
                        self.send_error(403)
                        return
                    message = json.loads(body)
                    response = owner.dispatch(message)
                    data = json.dumps(response).encode() if response else b""
                    self.send_response(200 if response else 202)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (ValueError, TypeError, OSError):
                    self.send_error(400)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_port}{self.path}"

    def dispatch(self, message):
        if not isinstance(message, dict):
            raise TypeError("JSON object required")
        method = message.get("method")
        if method == "notifications/initialized":
            return None
        result = {}
        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "triad-isolated-tools", "version": "1"},
            }
        elif method == "tools/list":
            result = {"tools": self.broker.definitions()}
        elif method == "tools/call":
            params = message.get("params", {})
            try:
                output = self.broker.call(params.get("name"), params.get("arguments", {}))
                result = {"content": [{"type": "text", "text": output}]}
            except Exception:  # noqa: BLE001 - protocol returns a fixed denial
                # Never echo host exception strings, paths or command lines to the model.
                result = {
                    "isError": True,
                    "content": [{"type": "text", "text": "Triad denied this tool operation."}],
                }
        elif method != "ping":
            return {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {"code": -32601, "message": "Unsupported method"},
            }
        return {"jsonrpc": "2.0", "id": message.get("id"), "result": result}

    def __enter__(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
