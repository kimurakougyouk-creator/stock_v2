from ai_asset_platform.brokers.ibkr_probe_thread import start_guarded_ibapi_loop


def test_guarded_ibapi_loop_contains_background_exception():
    def broken_run():
        raise TypeError("serverVersion is None")

    thread, state = start_guarded_ibapi_loop(broken_run, name="test-ibkr-probe")
    thread.join(timeout=1.0)

    assert thread.is_alive() is False
    assert state.exception == "TypeError: serverVersion is None"
