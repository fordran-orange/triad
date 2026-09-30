"""Operator host rollout after independent source QA."""

import argparse

from trading_core.intelligence.records import Records
from trading_core.product_changes import activate

parser = argparse.ArgumentParser()
parser.add_argument("--implementation", required=True)
parser.add_argument("--commit", required=True)
args = parser.parse_args()
print(activate(Records(), args.implementation, args.commit))
