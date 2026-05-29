"""Local paper broker used by tests and offline development."""

from app.core.config import settings
from app.domain.trading import (
    BrokerAccountStatus,
    BrokerOrderReceipt,
    ExecutionIntent,
    new_id,
)


class LocalPaperBroker:
    """Local receipt generator that never contacts a broker."""

    def get_account_status(self) -> BrokerAccountStatus:
        """Return a local demo account shape for offline development."""

        return BrokerAccountStatus(
            broker="local-paper",
            account_mode="paper",
            account_id_hint="local",
            status="offline-demo",
            currency=settings.base_currency,
            buying_power=10,
            cash=10,
            portfolio_value=10,
            pattern_day_trader=None,
        )

    def submit_order(self, intent: ExecutionIntent) -> BrokerOrderReceipt:
        """Pretend to submit an order for pipeline verification."""

        return BrokerOrderReceipt(
            broker_order_id=new_id("local_order"),
            intent_id=intent.intent_id,
            status="accepted_local_paper",
            symbol=intent.symbol,
            side=intent.side,
            submitted_notional=intent.approved_notional,
            raw_message="Local paper broker accepted the execution intent.",
        )


__all__ = ["LocalPaperBroker"]
