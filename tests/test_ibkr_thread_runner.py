import pytest

from ai_asset_platform.brokers.ibkr_thread_runner import run_ibapi_message_loop_safely


class _TeardownRaceClient:
    def run(self):
        raise TypeError("'>=' not supported between instances of 'NoneType' and 'int'")


class _UnexpectedClient:
    def run(self):
        raise TypeError("unexpected type error")


def test_ibapi_teardown_race_is_captured_as_diagnostic():
    errors: list[str] = []
    run_ibapi_message_loop_safely(_TeardownRaceClient(), errors=errors)
    assert len(errors) == 1
    assert "teardown race" in errors[0]
    assert "NoneType" in errors[0]


def test_unrelated_type_error_is_not_suppressed():
    with pytest.raises(TypeError, match="unexpected type error"):
        run_ibapi_message_loop_safely(_UnexpectedClient(), errors=[])
