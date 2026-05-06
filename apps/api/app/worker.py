"""Command-line entrypoint for the local autonomous trading worker."""

import argparse
import json
import sys

from app.services.broker_adapter import (
    MissingBrokerCredentialsError,
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
        "--paper-order",
        action="store_true",
        help="Submit one risk-gated demo order to Alpaca paper trading.",
    )
    parser.add_argument(
        "--reconcile-alpaca",
        action="store_true",
        help="Fetch read-only Alpaca paper account, orders, and positions.",
    )
    args = parser.parse_args()

    try:
        selected_actions = [
            args.check_alpaca,
            args.paper_order,
            args.reconcile_alpaca,
        ]
        if sum(bool(action) for action in selected_actions) > 1:
            parser.error("Choose only one worker action at a time.")

        if args.check_alpaca:
            result = get_alpaca_paper_broker().get_account_status()
        elif args.paper_order:
            result = run_single_cycle(use_alpaca_paper=True)
        elif args.reconcile_alpaca:
            result = get_alpaca_paper_broker().get_reconciliation_snapshot()
        else:
            result = run_single_cycle()
    except MissingBrokerCredentialsError as exc:
        print("Alpaca paper credentials are not configured yet.")
        print("Open apps/api/.env and fill these fields:")
        for name in exc.missing_names:
            print(f"- {name}")
        print("Keep INVESTMENT_APP_ALPACA_PAPER=true for the paper account.")
        sys.exit(2)

    print(json.dumps(result.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
