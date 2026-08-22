"""Static import/safety smoke check for the historical FX fallback wiring.

CI-only helper. It imports the broker-only modules and verifies their public
symbols exist. It never connects to IBKR and never creates/transmits an order.
"""
from ai_asset_platform.brokers.ibkr_fx_evidence import resolve_ibkr_paper_fx_evidence
from ai_asset_platform.brokers.ibkr_fx_historical import preview_ibkr_paper_historical_fx_rate


assert callable(resolve_ibkr_paper_fx_evidence)
assert callable(preview_ibkr_paper_historical_fx_rate)
print("historical FX fallback import smoke check: PASS")
