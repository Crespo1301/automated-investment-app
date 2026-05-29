"""Options-trading methods for the Alpaca broker.

Implemented as a mixin so the equity-focused ``AlpacaBroker`` stays
readable while the options surface (chain fetch + order submission)
lives next to its OCC parsing and SDK details.
"""

from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.domain.trading import (
    BrokerOrderReceipt,
    OptionContract,
    OptionsChainSnapshot,
    OptionsExecutionIntent,
)

from app.services.brokers.base import _optional_int, _parse_occ_symbol


class AlpacaOptionsMixin:
    """Options chain and order methods mixed into :class:`AlpacaBroker`.

    Relies on attributes initialized by the host class:
    ``client``, ``data_client``, ``_options_data_client``, and the
    ``_optional_float`` helper.
    """

    def get_option_chain(
        self,
        underlying: str,
        *,
        dte_min: int,
        dte_max: int,
    ) -> OptionsChainSnapshot:
        """Fetch a filtered option chain snapshot for the given underlying.

        NOTE: verify Alpaca options SDK field names with a live call before
        first real submission. The alpaca-py options module shape can shift
        between SDK releases.
        """

        from alpaca.data.historical.option import OptionHistoricalDataClient
        from alpaca.data.requests import OptionChainRequest
        from alpaca.data.requests import StockLatestTradeRequest

        if self._options_data_client is None:
            self._options_data_client = OptionHistoricalDataClient(
                settings.alpaca_api_key,
                settings.alpaca_secret_key,
            )

        normalized = underlying.upper()
        today = datetime.now(UTC).date()
        expiration_gte = today + timedelta(days=max(0, dte_min))
        expiration_lte = today + timedelta(days=max(dte_min, dte_max))

        chain_response = self._options_data_client.get_option_chain(
            OptionChainRequest(
                underlying_symbol=normalized,
                expiration_date_gte=expiration_gte,
                expiration_date_lte=expiration_lte,
            )
        )

        # get_option_chain returns dict[occ_symbol, OptionsSnapshot]
        contracts: list[OptionContract] = []
        for occ_symbol, snapshot in chain_response.items():
            parsed = _parse_occ_symbol(occ_symbol)
            if parsed is None:
                continue
            expiration, strike, contract_type = parsed
            latest_quote = getattr(snapshot, "latest_quote", None)
            latest_trade = getattr(snapshot, "latest_trade", None)
            greeks = getattr(snapshot, "greeks", None)
            contracts.append(
                OptionContract(
                    occ_symbol=occ_symbol,
                    underlying=normalized,
                    expiration=expiration,
                    strike=strike,
                    contract_type=contract_type,
                    multiplier=100,
                    bid=self._optional_float(getattr(latest_quote, "bid_price", None)),
                    ask=self._optional_float(getattr(latest_quote, "ask_price", None)),
                    last=self._optional_float(getattr(latest_trade, "price", None)),
                    open_interest=_optional_int(getattr(snapshot, "open_interest", None)),
                    volume=_optional_int(getattr(latest_trade, "size", None)),
                    delta=self._optional_float(getattr(greeks, "delta", None)) if greeks else None,
                    implied_volatility=self._optional_float(
                        getattr(snapshot, "implied_volatility", None)
                    ),
                )
            )

        underlying_price: float | None = None
        try:
            trade = self.data_client.get_stock_latest_trade(
                StockLatestTradeRequest(symbol_or_symbols=normalized)
            )
            entry = trade.get(normalized) if isinstance(trade, dict) else None
            underlying_price = self._optional_float(getattr(entry, "price", None))
        except Exception:
            underlying_price = None

        return OptionsChainSnapshot(
            underlying=normalized,
            underlying_price=underlying_price,
            contracts=contracts,
        )

    def submit_options_order(self, intent: OptionsExecutionIntent) -> BrokerOrderReceipt:
        """Submit an approved options execution intent to Alpaca.

        Level 1 orders are single-leg limit orders against an OCC symbol.
        NOTE: verify with a paper round-trip before the first live call.
        """

        from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
        from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest

        side = OrderSide.SELL if intent.action in {"sell_to_open", "sell_to_close"} else OrderSide.BUY
        tif = TimeInForce.DAY if intent.time_in_force == "day" else TimeInForce.GTC

        if intent.order_type == "limit" and intent.limit_price is not None:
            request = LimitOrderRequest(
                symbol=intent.occ_symbol,
                qty=intent.contracts,
                side=side,
                type=OrderType.LIMIT,
                time_in_force=tif,
                limit_price=round(float(intent.limit_price), 2),
                client_order_id=intent.client_order_id,
            )
        else:
            request = MarketOrderRequest(
                symbol=intent.occ_symbol,
                qty=intent.contracts,
                side=side,
                time_in_force=tif,
                client_order_id=intent.client_order_id,
            )

        order = self.client.submit_order(order_data=request)
        return BrokerOrderReceipt(
            broker_order_id=str(order.id),
            intent_id=intent.intent_id,
            status=str(order.status),
            symbol=intent.occ_symbol,
            side="sell" if side == OrderSide.SELL else "buy",
            submitted_notional=(
                float(intent.limit_price) * intent.contracts * 100
                if intent.limit_price is not None
                else 0.0
            ),
            raw_message=(
                f"Alpaca accepted options {intent.action} for {intent.occ_symbol} "
                f"x{intent.contracts} (client id {intent.client_order_id})."
            ),
        )


__all__ = ["AlpacaOptionsMixin"]
