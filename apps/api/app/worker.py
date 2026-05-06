"""Command-line entrypoint for the local autonomous trading worker."""

import argparse
import json
import sys

from app.services.broker_adapter import (
    MissingBrokerCredentialsError,
    get_active_alpaca_broker,
    get_alpaca_paper_broker,
)
from app.services.local_worker import run_single_cycle


def main() -> None:
    """Run local worker utilities and print redacted audit payloads."""

    parser = argparse.ArgumentParser(description="Local trading worker utilities.")
    parser.add_argument(
        "--check-alpaca",
        action="store_true",
        help="Run a read-only Alpaca paper account connection check.",
    )
    parser.add_argument(
        "--check-broker",
        action="store_true",
        help="Run a read-only account check against the active paper/live broker configuration.",
    )
    parser.add_argument(
        "--paper-order",
        action="store_true",
        help="Submit one risk-gated demo order to Alpaca paper trading.",
    )
    parser.add_argument(
        "--reconcile-alpaca",
        action="store_true",
        help="Fetch read-only Alpaca paper account, orders, and positions.",
    )
    parser.add_argument(
        "--reconcile-broker",
        action="store_true",
        help="Fetch account, orders, and positions from the active paper/live broker configuration.",
    )
    parser.add_argument(
        "--cancel-open-orders",
        action="store_true",
        help="Cancel all currently open orders on the active paper/live broker configuration.",
    )
    args = parser.parse_args()

    try:
        selected_actions = [
            args.check_alpaca,
            args.check_broker,
            args.paper_order,
            args.reconcile_alpaca,
            args.reconcile_broker,
            args.cancel_open_orders,
        ]
        if sum(bool(action) for action in selected_actions) > 1:
            parser.error("Choose only one worker action at a time.")

        if args.check_alpaca:
            result = get_alpaca_paper_broker().get_account_status()
        elif args.check_broker:
            result = get_active_alpaca_broker().get_account_status()
        elif args.paper_order:
            result = run_single_cycle(use_alpaca_paper=True)
        elif args.reconcile_alpaca:
            result = get_alpaca_paper_broker().get_reconciliation_snapshot()
        elif args.reconcile_broker:
            result = get_active_alpaca_broker().get_reconciliation_snapshot()
        elif args.cancel_open_orders:
            result = {
                "broker": "alpaca",
                "mode": "active-config",
                "canceled_orders": get_active_alpaca_broker().cancel_open_orders(),
            }
        else:
            result = run_single_cycle()
    except MissingBrokerCredentialsError as exc:
        print("Broker credentials are not configured yet.")
        print("Open apps/api/.env and fill these fields:")
        for name in exc.missing_names:
            print(f"- {name}")
        print("Confirm the paper/live mode flags in apps/api/.env before retrying.")
        sys.exit(2)

    if hasattr(result, "model_dump"):
        payload = result.model_dump(mode="json")
    else:
        payload = result

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
