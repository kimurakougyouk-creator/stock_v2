from __future__ import annotations

from dataclasses import dataclass

from ai_asset_platform.brokers.ibkr_config import IbkrConnectionConfig, create_ibkr_paper_config
from ai_asset_platform.brokers.ibkr_paper_order_sender import IbkrPreparedOrder, prepare_ibkr_paper_order_for_instrument
from ai_asset_platform.brokers.instruments import InstrumentSpec
from ai_asset_platform.brokers.orders import OrderRequest, OrderSide, OrderType
from ai_asset_platform.core.asset_classes import AssetClass


PAPER_API_PORTS = {4002, 7497}


@dataclass(frozen=True)
class OvernightPaperOrderSpec:
    symbol: str
    side: OrderSide
    quantity: int
    limit_price: float
    primary_exchange: str
    asset_class: AssetClass = AssetClass.ETF


def prepare_ibkr_overnight_paper_limit_order(
    spec: OvernightPaperOrderSpec,
    *,
    config: IbkrConnectionConfig | None = None,
    verified_paper_test_quantity: int | None = None,
) -> IbkrPreparedOrder:
    """Build an IBKR Overnight Paper limit order without transmitting it.

    Supports the two standard simulated-trading endpoints used by IBKR:
    Gateway Paper (4002) and TWS Paper (7497). The caller must still provide a
    Paper-only config, broker-resolved primary exchange, and an explicitly
    verified quantity. The returned order always has transmit=False.
    """
    cfg = config or create_ibkr_paper_config()
    cfg.validate()
    if cfg.port not in PAPER_API_PORTS:
        raise RuntimeError("Overnight Paper preparation requires IBKR Paper port 4002 or 7497.")
    if not cfg.paper_trading or cfg.allow_live_trading:
        raise RuntimeError("Overnight preparation is Paper-only and Live must remain disabled.")
    if spec.asset_class not in {AssetClass.STOCK, AssetClass.ETF}:
        raise ValueError("Overnight routing is currently verified only for US STOCK/ETF.")
    if not spec.primary_exchange.strip():
        raise ValueError("Overnight routing requires a broker-resolved primary_exchange.")
    if verified_paper_test_quantity is None:
        raise RuntimeError("Overnight Paper quantity is unverified; preparation is blocked.")

    instrument = InstrumentSpec(
        symbol=spec.symbol.strip().upper(),
        asset_class=spec.asset_class,
        exchange="OVERNIGHT",
        currency="USD",
        primary_exchange=spec.primary_exchange.strip().upper(),
        verified_paper_test_quantity=verified_paper_test_quantity,
    )
    request = OrderRequest(
        symbol=instrument.symbol,
        side=spec.side,
        quantity=spec.quantity,
        order_type=OrderType.LIMIT,
        limit_price=float(spec.limit_price),
    )
    prepared = prepare_ibkr_paper_order_for_instrument(request, instrument, cfg)

    prepared.order.tif = "DAY"
    prepared.order.outsideRth = False
    prepared.order.transmit = False
    return prepared
