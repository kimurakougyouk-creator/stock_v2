from pathlib import Path
from types import SimpleNamespace
from typing import Any

from stability import FatalOperationalError, create_daily_logger, safe_stop

DRY_RUN_MODES = {"dry_run", "dry-run", "paper"}


def load_runtime_config(config_module: Any) -> SimpleNamespace:
    """起動時セルフチェックで利用する設定だけを抽出する"""

    return SimpleNamespace(
        broker_mode=getattr(config_module, "BROKER_MODE", "dry_run"),
        dry_run=getattr(config_module, "DRY_RUN", True),
        ticker_file=getattr(config_module, "TICKER_FILE", "tickers.csv"),
        result_dir=getattr(config_module, "RESULT_DIR", "results"),
        app_password=getattr(config_module, "APP_PASSWORD", ""),
        email_address=getattr(config_module, "EMAIL_ADDRESS", ""),
        log_dir=getattr(config_module, "LOG_DIR", "results"),
    )


def run_startup_self_check(config_module: Any, logger=None) -> bool:
    """運用開始前に安全条件を確認する"""

    runtime = load_runtime_config(config_module)
    logger = logger or create_daily_logger("startup", log_dir=runtime.log_dir)

    result_dir = Path(runtime.result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)

    if not Path(runtime.ticker_file).exists():
        safe_stop(f"ticker file not found: {runtime.ticker_file}", logger)

    broker_mode = runtime.broker_mode.lower()
    if broker_mode not in DRY_RUN_MODES:
        safe_stop("実注文モードは未実装です。BROKER_MODE=dry_run で起動してください。", logger)

    if not runtime.dry_run:
        safe_stop("DRY_RUN が無効です。実注文処理は未実装のため安全停止します。", logger)

    if runtime.email_address and not runtime.app_password:
        logger.warning("APP_PASSWORD is not set; Gmail notification may fail")

    logger.info("startup self-check passed")
    return True


def run_with_safe_shutdown(operation, logger):
    """致命的エラー時にログへ保存して安全に終了する"""

    try:
        return operation()
    except FatalOperationalError:
        logger.exception("application stopped safely")
        raise
