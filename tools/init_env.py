"""Generate secrets once and restrict the local credential file to its owner/admins."""

import getpass
import os
import secrets
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    print(".env already exists; credentials preserved")
else:
    template = (root / ".env.example").read_text()
    template = template.replace("REPLACE_WITH_RANDOM_SECRET", secrets.token_hex(32))
    template = template.replace("REPLACE_WITH_DIFFERENT_RANDOM_SECRET", secrets.token_hex(32))
    with target.open("x", encoding="utf-8") as handle:
        handle.write(template)
    print("Generated independent random local credentials")
current = target.read_text(encoding="utf-8")
if "TRIAD_OPERATOR_TOKEN=" not in current:
    current += "\nTRIAD_OPERATOR_TOKEN=" + secrets.token_hex(32) + "\n"
if "REPLACE_WITH_OPERATOR_SECRET" in current:
    current = current.replace("REPLACE_WITH_OPERATOR_SECRET", secrets.token_hex(32))
target.write_text(current, encoding="utf-8")
if os.name == "nt":
    subprocess.run(
        [
            "icacls",
            str(target),
            "/inheritance:r",
            "/grant:r",
            getpass.getuser() + ":(F)",
            "*S-1-5-18:(F)",
            "*S-1-5-32-544:(F)",
        ],
        check=True,
        capture_output=True,
    )
else:
    target.chmod(0o600)
print("Restricted .env access to owner, system and administrators")
