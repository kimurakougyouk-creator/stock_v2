import logging
import time
from datetime import datetime
from pathlib import Path


class FatalOperationalError(RuntimeError):
    """安全停止すべき致命的な運用エラー"""


def create_daily_logger(name, log_dir="logs", log_file=None, current_date=None):
    """日付ごとのログファイルへ保存するloggerを作成する"""

    if log_file is None:
        date_text = current_date or datetime.utcnow().strftime("%Y-%m-%d")
        log_path = Path(log_dir) / f"{name}_{date_text}.log"
    else:
        log_path = Path(log_file)

    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(f"{name}.{log_path}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)

    return logger


def retry_operation(operation, retries=3, delay_seconds=1, retry_exceptions=(ConnectionError, TimeoutError), logger=None):
    """ネットワーク等の一時的な失敗をリトライして自動復旧する"""

    last_error = None

    for attempt in range(1, retries + 1):
        try:
            return operation()
        except retry_exceptions as exc:
            last_error = exc
            if logger:
                logger.warning("temporary failure on attempt %s/%s: %s", attempt, retries, exc)

            if attempt < retries and delay_seconds > 0:
                time.sleep(delay_seconds)

    if logger:
        logger.exception("operation failed after retries", exc_info=last_error)

    raise last_error


def safe_execute(operation, logger, fatal_exceptions=(FatalOperationalError,), default=None):
    """例外をログへ保存し、致命的エラーは安全停止する"""

    try:
        return operation()
    except fatal_exceptions:
        logger.exception("fatal error; stopping safely")
        raise
    except Exception as exc:
        logger.exception("operation failed safely: %s", exc)
        return default


def safe_stop(message, logger):
    """致命的エラーとしてログに残し、安全停止用例外を送出する"""

    logger.error(message)
    raise FatalOperationalError(message)
