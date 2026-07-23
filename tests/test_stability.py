from pathlib import Path

from stability import FatalOperationalError, create_daily_logger, retry_operation, safe_execute, safe_stop


def test_create_daily_logger_writes_date_rotated_log(tmp_path):
    logger = create_daily_logger("ops", log_dir=tmp_path, current_date="2026-07-23")

    logger.info("hello")

    log_file = tmp_path / "ops_2026-07-23.log"
    assert log_file.exists()
    assert "hello" in log_file.read_text(encoding="utf-8")


def test_retry_operation_recovers_from_temporary_failure():
    attempts = {"count": 0}

    def operation():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ConnectionError("temporary network error")
        return "ok"

    assert retry_operation(operation, retries=3, delay_seconds=0) == "ok"
    assert attempts["count"] == 3


def test_safe_execute_logs_non_fatal_error_and_returns_default(tmp_path):
    logger = create_daily_logger("safe", log_dir=tmp_path, current_date="2026-07-23")

    result = safe_execute(lambda: (_ for _ in ()).throw(ValueError("boom")), logger, default="fallback")

    assert result == "fallback"
    assert "boom" in (tmp_path / "safe_2026-07-23.log").read_text(encoding="utf-8")


def test_safe_stop_logs_and_raises_fatal_error(tmp_path):
    logger = create_daily_logger("fatal", log_dir=tmp_path, current_date="2026-07-23")

    try:
        safe_stop("stop now", logger)
    except FatalOperationalError as exc:
        assert "stop now" in str(exc)
    else:
        raise AssertionError("safe_stop should raise FatalOperationalError")

    assert "stop now" in (tmp_path / "fatal_2026-07-23.log").read_text(encoding="utf-8")
