from __future__ import annotations


def test_zero_reference_shares_diagnostic_calculation():
    risk_per_share = 113.61
    max_loss_yen = 10_000.0
    lot_size = 100

    raw_risk_shares = (
        int(max_loss_yen // risk_per_share)
        if risk_per_share > 0
        else 0
    )

    assert raw_risk_shares == 88
    assert raw_risk_shares < lot_size
