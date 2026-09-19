"""Run real subscription/local acceptance; never enables API fallback or raises budgets."""

import json

from triad.day5a.contracts import PREFERRED
from triad.day5a.control import ProviderControl
from triad.day5a.relay import run_relay
from triad.day5a.verification import verify


def main():
    control = ProviderControl()
    for transport in PREFERRED.values():
        control.refresh(transport)
        for acceptance in (False, True):
            proof = verify(control, transport, acceptance=acceptance)
            print(json.dumps(proof), flush=True)
            if not proof["success"]:
                return 1
    proof = run_relay(control)
    print(json.dumps(proof), flush=True)
    return 0 if proof["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
