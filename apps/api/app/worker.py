"""Command-line entrypoint for the local autonomous trading worker."""

import argparse
import json
import sys

from app.services.broker_adapter import (
    MissingBrokerCredentialsError,
    get_active_alpaca_broker,
    get_alpaca_paper_broker,
)
from app.services.audit_replay import replay_pipeline_runs
from app.services.audit_store import (
    get_autopilot_state,
    record_cancel_result,
    record_reconciliation_snapshot,
    set_kill_switch,
    summarize_audit,
)
from app.services.autopilot import (
    disable_autopilot,
    enable_autopilot,
    run_autopilot_loop,
    run_autopilot_once,
)
from app.services.local_worker import run_queue_for_open_cycle, run_single_cycle
from app.services.readiness import get_morning_readiness


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
    parser.add_argument(
        "--queue-for-open",
        action="store_true",
        help="Submit one guarded regular-session order while the market is closed.",
    )
    parser.add_argument(
        "--safety-status",
        action="store_true",
        help="Show local audit, kill-switch, and market-clock state.",
    )
    parser.add_argument(
        "--enable-kill-switch",
        metavar="REASON",
        help="Block future submissions until the kill switch is disabled.",
    )
    parser.add_argument(
        "--disable-kill-switch",
        action="store_true",
        help="Disable the local operator kill switch.",
    )
    parser.add_argument(
        "--autopilot-status",
        action="store_true",
        help="Show local supervised autopilot state.",
    )
    parser.add_argument(
        "--enable-autopilot",
        metavar="REASON",
        help="Arm supervised autopilot state. Start --autopilot-loop separately.",
    )
    parser.add_argument(
        "--disable-autopilot",
        metavar="REASON",
        nargs="?",
        const="Operator disabled autopilot.",
        help="Disarm supervised autopilot state.",
    )
    parser.add_argument(
        "--autopilot-once",
        action="store_true",
        help="Run one supervised autopilot tick.",
    )
    parser.add_argument(
        "--autopilot-loop",
        action="store_true",
        help="Run the supervised autopilot loop until disabled or interrupted.",
    )
    parser.add_argument(
        "--morning-readiness",
        action="store_true",
        help="Show the morning trading readiness checklist.",
    )
    parser.add_argument(
        "--autopilot-max-ticks",
        type=int,
        default=None,
        help="Optional testing limit for --autopilot-loop.",
    )
    parser.add_argument(
        "--replay-pipeline",
        action="store_true",
        help="Re-score recorded pipeline runs with the current local fallback "
        "scorer and report per-strategy deltas plus decision flips.",
    )
    parser.add_argument(
        "--replay-limit",
        type=int,
        default=None,
        help="Replay only the most recent N pipeline runs (default: all).",
    )
    parser.add_argument(
        "--replay-include-model-tier",
        action="store_true",
        help="Include rows scored by Claude/OpenAI in the replay (default: skip "
        "non-local rows since the fallback can't replicate model output).",
    )
    parser.add_argument(
        "--replay-current-schema-only",
        action="store_true",
        help="Skip pre-market-context candidates in replay. Use this when "
        "validating a scoring-logic change to avoid apples-to-oranges deltas.",
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
            args.queue_for_open,
            args.safety_status,
            bool(args.enable_kill_switch),
            args.disable_kill_switch,
            args.autopilot_status,
            bool(args.enable_autopilot),
            bool(args.disable_autopilot),
            args.autopilot_once,
            args.autopilot_loop,
            args.morning_readiness,
            args.replay_pipeline,
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
            record_reconciliation_snapshot(result)
        elif args.reconcile_broker:
            result = get_active_alpaca_broker().get_reconciliation_snapshot()
            record_reconciliation_snapshot(result)
        elif args.cancel_open_orders:
            result = {
                "broker": "alpaca",
                "mode": "active-config",
                "canceled_orders": get_active_alpaca_broker().cancel_open_orders(),
            }
            record_cancel_result(result)
        elif args.queue_for_open:
            result = run_queue_for_open_cycle()
        elif args.safety_status:
            broker = get_active_alpaca_broker()
            result = summarize_audit(market_clock=broker.get_market_clock())
        elif args.enable_kill_switch:
            result = set_kill_switch(True, reason=args.enable_kill_switch)
        elif args.disable_kill_switch:
            result = set_kill_switch(False, reason="Operator disabled the kill switch.")
        elif args.autopilot_status:
            result = get_autopilot_state()
        elif args.enable_autopilot:
            result = enable_autopilot(reason=args.enable_autopilot)
        elif args.disable_autopilot:
            result = disable_autopilot(reason=args.disable_autopilot)
        elif args.autopilot_once:
            result = run_autopilot_once()
        elif args.autopilot_loop:
            run_autopilot_loop(max_ticks=args.autopilot_max_ticks)
            result = get_autopilot_state()
        elif args.morning_readiness:
            result = get_morning_readiness()
        elif args.replay_pipeline:
            report = replay_pipeline_runs(
                limit=args.replay_limit,
                only_local_tier=not args.replay_include_model_tier,
                only_with_market_context=args.replay_current_schema_only,
            )
            result = report.to_summary()
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
