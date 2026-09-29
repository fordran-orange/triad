"""One executable resolver for detection, authentication and execution.

Version families only qualify an installation for isolated protocol verification;
they never establish a runtime capability or authorize a task.
"""

import hashlib
import os
import re
import shutil
from pathlib import Path

from trading_core.settings import ROOT


def compatible(agent, version):
    patterns = {
        "CODEX": r"codex-cli (0)\.\d+\.\d+(?:[-+][\w.]+)?",
        "CLAUDE": r"(2)\.\d+\.\d+(?:[-+][\w.]+)? \(Claude Code\)",
        "GROK": r"grok (1)\.\d+\.\d+(?:[-+][\w.]+)?(?: \([a-f0-9]+\))?",
    }
    return bool(re.fullmatch(patterns.get(agent, r"(?!)"), version))


def identity(command):
    """Hash launch files so a replaced binary cannot inherit the old proof."""
    result = []
    for value in command or ():
        path = Path(value)
        if path.is_file():
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            result.append({"path": str(path.resolve()), "sha256": digest})
    return result


def candidates(name):
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    local = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData/Local")))
    roaming = Path(os.environ.get("APPDATA", str(home / "AppData/Roaming")))
    program = Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
    node = shutil.which("node.exe") or shutil.which("node")
    if not node and (program / "nodejs/node.exe").is_file():
        node = str(program / "nodejs/node.exe")
    scripts = {
        "codex": "@openai/codex/bin/codex.js",
        "claude": "@anthropic-ai/claude-code/cli.js",
        "grok": "@xai-official/grok/bin/grok",
    }
    found = []
    from dotenv import dotenv_values

    key = "TRIAD_" + name.upper() + "_EXECUTABLE"
    explicit = os.environ.get(key) or dotenv_values(ROOT / ".env").get(key)
    if explicit:
        found.append([explicit])
    if name in scripts:
        for prefix in (
            ROOT / "data/provider-cli/node_modules",
            ROOT / "data/temp/provider-cli/node_modules",
            roaming / "npm/node_modules",
        ):
            if name == "claude":
                found.append([str(prefix / "@anthropic-ai/claude-code/bin/claude.exe")])
            if node:
                found.append([node, str(prefix / scripts[name])])
    for suffix in (".exe", ""):
        item = shutil.which(name + suffix)
        if item and Path(item).suffix.lower() not in {".cmd", ".bat", ".ps1"}:
            found.append([item])
    found.append([str(home / ".local/bin" / (name + ".exe"))])
    if name == "codex":
        found.extend(
            [str(p)]
            for p in sorted(
                (local / "OpenAI/Codex/bin").glob("*/codex.exe"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        )
    if name == "ollama":
        found.extend(
            [[str(local / "Programs/Ollama/ollama.exe")], [str(program / "Ollama/ollama.exe")]]
        )
        # Services can inherit yesterday's PATH. Consult the current Windows user
        # PATH too, without executing shell shims or searching arbitrary directories.
        if os.name == "nt":
            import winreg

            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                    user_path = winreg.QueryValueEx(key, "Path")[0]
                for directory in user_path.split(";"):
                    if directory:
                        found.append([str(Path(os.path.expandvars(directory)) / "ollama.exe")])
            except OSError:
                pass
    unique = []
    for command in found:
        if command not in unique and all(Path(p).is_file() for p in command):
            unique.append(command)
    return unique


def runtime_identity(data, transport):
    keys = (
        ("cli_version", "executable_identity")
        if transport != "ollama"
        else ("endpoint", "local_version", "model_digest")
    )
    return {key: data.get(key) for key in keys}
