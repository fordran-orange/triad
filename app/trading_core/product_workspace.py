"""Product development tools operating on an isolated snapshot, never host files.

This broker does not grant authority or merge changes. A trusted caller must
validate the canonical assignment before construction and on every guard call.
"""

import hashlib
import json
import threading

from trading_core.product_changes import PRODUCT_ROOTS, ProductFileChange, product_path
from trading_core.providers.isolation import OfflineSandbox
from trading_core.security import ensure_no_secret

MAX_FILES = 2048
MAX_BYTES = 1000000


def validate_snapshot(files):
    if not isinstance(files, dict) or len(files) > MAX_FILES:
        raise ValueError("Product snapshot exceeds physical file capacity")
    if len({p.casefold() for p in files}) != len(files):
        raise PermissionError("Aliased product paths")
    for path, content in files.items():
        product_path(path)
        if not isinstance(content, str):
            raise TypeError("Product snapshot must contain text")
    if sum(len(v.encode()) for v in files.values()) > MAX_BYTES:
        raise ValueError("Product snapshot exceeds physical byte capacity")
    ensure_no_secret(files)


class ProductWorkspace:
    def __init__(self, files, *, image, guard, resources=None):
        validate_snapshot(files)
        self.files = dict(files)
        self.original = dict(files)
        self.writable = PRODUCT_ROOTS
        self.guard, self.resources = guard, resources
        self.calls, self.denials = [], 0
        self.sandbox = OfflineSandbox(image=image)
        self.lock = threading.Lock()

    def cancel(self):
        self.sandbox.cancel()

    def call(self, name, arguments):
        with self.lock:
            self.guard()
            if self.resources:
                self.resources.check_time()
                self.resources.consume_tool()
            try:
                if not isinstance(arguments, dict):
                    raise TypeError("Tool arguments must be an object")
                ensure_no_secret(arguments)
                candidate = dict(self.files)
                path = arguments.get("path")
                evidence = {"tool": name}
                if name == "list_files" and not arguments:
                    result = json.dumps(sorted(candidate))
                elif name == "read_file" and set(arguments) == {"path"}:
                    product_path(path)
                    result = candidate[path]
                    evidence["path"] = path
                elif name == "write_file" and set(arguments) == {"path", "content"}:
                    product_path(path)
                    candidate[path] = arguments["content"]
                    evidence["path"] = path
                    result = "File updated in development workspace."
                elif name == "delete_file" and set(arguments) == {"path"}:
                    product_path(path)
                    del candidate[path]
                    evidence["path"] = path
                    result = "File removed from development workspace."
                elif name == "rename_file" and set(arguments) == {"path", "destination"}:
                    product_path(path)
                    destination = product_path(arguments["destination"])
                    if destination.casefold() in {p.casefold() for p in candidate}:
                        raise PermissionError("Rename destination already exists")
                    candidate[destination] = candidate.pop(path)
                    evidence.update(path=path, destination=destination)
                    result = "File renamed in development workspace."
                elif name == "run_command" and set(arguments) == {"argv"}:
                    outcome = self.sandbox.run(
                        arguments["argv"],
                        self.files,
                        writable=self.writable,
                        timeout=120,
                        guard=self.guard,
                        max_bytes=MAX_BYTES,
                        max_files=MAX_FILES,
                        export_failed=True,
                    )
                    for deleted in outcome.deleted:
                        product_path(deleted)
                        candidate.pop(deleted)
                    candidate.update(outcome.files)
                    evidence.update(
                        argv=arguments["argv"],
                        status=outcome.status,
                        exit_code=outcome.exit_code,
                        image=outcome.image,
                        boundary=outcome.boundary,
                    )
                    result = json.dumps(
                        {
                            "status": outcome.status,
                            "exit_code": outcome.exit_code,
                            "stdout": outcome.stdout,
                            "stderr": outcome.stderr,
                        }
                    )
                else:
                    raise PermissionError("Unknown development operation or arguments")
                validate_snapshot(candidate)
                self.guard()
                self.files = candidate
                evidence["snapshot_sha256"] = hashlib.sha256(
                    json.dumps(candidate, sort_keys=True).encode()
                ).hexdigest()
                self.calls.append(evidence)
                if self.resources:
                    self.resources.observe("valid_proposal", evidence["snapshot_sha256"])
                return result
            except Exception:
                self.denials += 1
                raise

    def changes(self):
        changes = []
        for path in sorted(set(self.original) | set(self.files)):
            if self.original.get(path) == self.files.get(path):
                continue
            changes.append(
                ProductFileChange(
                    path=path,
                    operation="WRITE" if path in self.files else "DELETE",
                    content=self.files.get(path),
                    original_sha256=hashlib.sha256(self.original[path].encode()).hexdigest()
                    if path in self.original
                    else None,
                )
            )
        return tuple(changes)

    def definitions(self):
        specifications = (
            ("list_files", "List available product files.", {}),
            ("read_file", "Read a product file.", {"path": {"type": "string"}}),
            (
                "write_file",
                "Create or replace a product file in the isolated workspace.",
                {"path": {"type": "string"}, "content": {"type": "string"}},
            ),
            (
                "delete_file",
                "Delete a product file in the isolated workspace.",
                {"path": {"type": "string"}},
            ),
            (
                "rename_file",
                "Rename a product file without replacing an existing file.",
                {"path": {"type": "string"}, "destination": {"type": "string"}},
            ),
            (
                "run_command",
                (
                    "Run tools or tests in the offline, credential-free development container. "
                    "Use an argument array, e.g. python -m unittest; shell syntax requires an explicit /bin/sh -c. "
                    "No host files, credentials or network are available. Results are developer feedback, not independent merge approval."
                ),
                {"argv": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
            ),
        )
        return [
            {
                "name": name,
                "description": description,
                "inputSchema": {
                    "type": "object",
                    "properties": properties,
                    "required": list(properties),
                    "additionalProperties": False,
                },
            }
            for name, description, properties in specifications
        ]
