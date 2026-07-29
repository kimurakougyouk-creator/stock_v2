from ai_asset_platform.reports.performance import (
    calculate_performance,
    calculate_performance_health,
)


def test_performance_health_returns_no_data() -> None:
    performance = calculate_performance([])

    health = calculate_performance_health(performance)

    assert health.score == 0
    assert health.grade == "N/A"
    assert health.status == "NO_DATA"


def test_performance_health_returns_excellent() -> None:
    performance = calculate_performance(
        [
            1000.0,
            1000.0,
            1000.0,
            -500.0,
            1000.0,
            1000.0,
            -500.0,
            1000.0,
            1000.0,
            1000.0,
            -500.0,
            1000.0,
            1000.0,
            -500.0,
            1000.0,
            1000.0,
            1000.0,
            -500.0,
            1000.0,
            1000.0,
        ]
    )

    health = calculate_performance_health(performance)

    assert health.score == 100
    assert health.grade == "A"
    assert health.status == "EXCELLENT"
    assert health.sample_score == 25
    assert health.win_rate_score == 25
    assert health.profit_factor_score == 25
    assert health.risk_reward_score == 25


def test_performance_health_penalizes_weak_results() -> None:
    performance = calculate_performance(
        [1000.0, -3000.0, -1000.0]
    )

    health = calculate_performance_health(performance)

    assert health.score == 3
    assert health.grade == "D"
    assert health.status == "POOR"
    assert health.sample_score == 3
    assert health.win_rate_score == 0
    assert health.profit_factor_score == 0
    assert health.risk_reward_score == 0


def test_performance_health_scores_each_component() -> None:
    performance = calculate_performance(
        [
            1000.0,
            1000.0,
            -1000.0,
            1000.0,
            -1000.0,
            1000.0,
            -1000.0,
            1000.0,
            -1000.0,
            -1000.0,
        ]
    )

    health = calculate_performance_health(performance)

    assert health.sample_score == 15
    assert health.win_rate_score == 20
    assert health.profit_factor_score == 10
    assert health.risk_reward_score == 0
    assert health.score == 45
    assert health.grade == "C"
    assert health.status == "CAUTION"
