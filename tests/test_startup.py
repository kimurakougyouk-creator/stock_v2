from types import SimpleNamespace

from startup import run_startup_self_check
from stability import FatalOperationalError, create_daily_logger


def _config(tmp_path, **overrides):
    ticker_file = tmp_path / "tickers.csv"
    ticker_file.write_text("Ticker\n7203.T\n", encoding="utf-8")
    values = {
        "BROKER_MODE": "dry_run",
        "DRY_RUN": True,
        "TICKER_FILE": str(ticker_file),
        "RESULT_DIR": str(tmp_path / "results"),
        "APP_PASSWORD": "",
        "EMAIL_ADDRESS": "test@example.com",
        "LOG_DIR": str(tmp_path),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_startup_self_check_passes_in_dry_run(tmp_path):
    logger = create_daily_logger("startup-test", log_dir=tmp_path, current_date="2026-07-23")

    assert run_startup_self_check(_config(tmp_path), logger)


def test_startup_self_check_stops_when_ticker_file_missing(tmp_path):
    logger = create_daily_logger("startup-test", log_dir=tmp_path, current_date="2026-07-23")
    config = _config(tmp_path, TICKER_FILE=str(tmp_path / "missing.csv"))

    try:
        run_startup_self_check(config, logger)
    except FatalOperationalError as exc:
        assert "ticker file not found" in str(exc)
    else:
        raise AssertionError("missing ticker file should stop safely")


def test_startup_self_check_stops_live_mode(tmp_path):
    logger = create_daily_logger("startup-test", log_dir=tmp_path, current_date="2026-07-23")
    config = _config(tmp_path, BROKER_MODE="sbi", DRY_RUN=False)

    try:
        run_startup_self_check(config, logger)
    except FatalOperationalError as exc:
        assert "BROKER_MODE=dry_run" in str(exc)
    else:
        raise AssertionError("live mode should stop safely")
