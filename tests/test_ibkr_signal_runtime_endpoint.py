import ai_asset_platform.execution.ibkr_signal_runtime as module


class FakeBroker:
    created_ports = []
    successful_port = None

    def __init__(self, *, config, enable_paper_order_transmission):
        self.config = config
        self.connected = False
        self.disconnect_calls = 0
        assert enable_paper_order_transmission is True
        self.__class__.created_ports.append(config.port)

    def connect(self):
        self.connected = self.config.port == self.__class__.successful_port
        return self.connected

    def is_connected(self):
        return self.connected

    def disconnect(self):
        self.disconnect_calls += 1
        self.connected = False


def test_signal_runtime_falls_back_from_gateway_4002_to_tws_7497(monkeypatch):
    FakeBroker.created_ports = []
    FakeBroker.successful_port = 7497
    monkeypatch.setattr(module, "IbkrBrokerAdapter", FakeBroker)

    broker = module._connect_first_available_paper_broker()

    assert FakeBroker.created_ports == [4002, 7497]
    assert broker.config.port == 7497
    assert broker.is_connected() is True


def test_signal_runtime_prefers_gateway_4002_when_reachable(monkeypatch):
    FakeBroker.created_ports = []
    FakeBroker.successful_port = 4002
    monkeypatch.setattr(module, "IbkrBrokerAdapter", FakeBroker)

    broker = module._connect_first_available_paper_broker()

    assert FakeBroker.created_ports == [4002]
    assert broker.config.port == 4002
    assert broker.is_connected() is True


def test_endpoint_failure_happens_before_any_order_execution(monkeypatch):
    FakeBroker.created_ports = []
    FakeBroker.successful_port = None
    monkeypatch.setattr(module, "IbkrBrokerAdapter", FakeBroker)

    called = {"execute": 0}
    monkeypatch.setattr(
        module,
        "execute_signal_via_ibkr_paper",
        lambda **kwargs: called.__setitem__("execute", called["execute"] + 1),
    )

    try:
        module._connect_first_available_paper_broker()
    except RuntimeError as exc:
        assert "4002" in str(exc)
        assert "7497" in str(exc)
    else:
        raise AssertionError("unreachable Paper endpoints must fail closed")

    assert called["execute"] == 0
    assert FakeBroker.created_ports == [4002, 7497]
