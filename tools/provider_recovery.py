"""Trusted host rollout/status entry point; never exposed as an agent tool."""
import argparse

from trading_core.intelligence.records import Records
from trading_core.providers.contracts import AGENTS
from trading_core.providers.control import ProviderControl
from trading_core.providers.recovery import activate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--activate', action='store_true')
    parser.add_argument('--implementation')
    parser.add_argument('--commit')
    parser.add_argument('--reconcile', action='store_true')
    args = parser.parse_args()
    records = Records()
    if args.activate:
        if not args.implementation or not args.commit:
            parser.error('Activation requires the independently reviewed implementation and commit')
        print('Recovery policy activated: ' + activate(records, args.implementation, args.commit))
    control = ProviderControl(records.ledger)
    if args.reconcile:
        control.monitor_connections()
    for agent in AGENTS:
        transport = control.policy(agent).preferred_transport
        state = control.read('provider-recovery-' + transport)
        print(agent + ': ' + state.get('status', 'Not yet reconciled') +
              (' — ' + state['message'] if state.get('message') else ''))


if __name__ == '__main__':
    main()
