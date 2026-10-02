"""One user-authorized REAL daily demonstration; never enables scheduling itself."""

import argparse
import json

from products.triad.daily_development import DailyDevelopment
from products.triad.daily_verification import verify


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--operator-authorized", action="store_true", required=True)
    parser.add_argument("--cycle-id")
    parser.add_argument("--scheduled", action="store_true")
    parser.add_argument("--expected-epoch", type=int)
    parser.add_argument("--schedule-id")
    parser.add_argument("--resume-patch-failure", action="store_true")
    parser.add_argument("--resume-read-failure", action="store_true")
    args = parser.parse_args()
    result = DailyDevelopment().run_daily(
        cycle_id=args.cycle_id,
        verify=verify,
        scheduled=args.scheduled,
        expected_epoch=args.expected_epoch,
        schedule_id=args.schedule_id,
        resume_patch_failure=args.resume_patch_failure,
        resume_read_failure=args.resume_read_failure,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
