import ai_asset_platform.execution.ibkr_signal_runtime as module


class FakeBroker:
    created_ports = []
    successful_port = None
    accounts_by_port = {}
    delayed_calls_before_arrival_by_port = {}

    def __init__(self, *, config, enable_paper_order_transmission):
        self.config = config
        self.connected = False
        self.disconnect_calls = 0
        self._managed_accounts_calls = 0
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

    def managed_accounts(self):
        self._managed_accounts_calls += 1
        delay = self.__class__.delayed_calls_before_arrival_by_port.get(self.config.port, 0)
        if self._managed_accounts_calls <= delay:
            return ()
        return self.__class__.accounts_by_port.get(self.config.port, ("DU1234567",))


def test_signal_runtime_falls_back_from_gateway_4002_to_tws_7497(monkeypatch):
    FakeBroker.created_ports = []
    FakeBroker.successful_port = 7497
    FakeBroker.accounts_by_port = {}
    FakeBroker.delayed_calls_before_arrival_by_port = {}
    monkeypatch.setattr(module, "IbkrBrokerAdapter", FakeBroker)

    broker = module._connect_first_available_paper_broker()

    assert FakeBroker.created_ports == [4002, 7497]
    assert broker.config.port == 7497
    assert broker.is_connected() is True


def test_signal_runtime_prefers_gateway_4002_when_reachable(monkeypatch):
    FakeBroker.created_ports = []
    FakeBroker.successful_port = 4002
    FakeBroker.accounts_by_port = {}
    FakeBroker.delayed_calls_before_arrival_by_port = {}
    monkeypatch.setattr(module, "IbkrBrokerAdapter", FakeBroker)

    broker = module._connect_first_available_paper_broker()

    assert FakeBroker.created_ports == [4002]
    assert broker.config.port == 4002
    assert broker.is_connected() is True


def test_endpoint_failure_happens_before_any_order_execution(monkeypatch):
    FakeBroker.created_ports = []
    FakeBroker.successful_port = None
    FakeBroker.accounts_by_port = {}
    FakeBroker.delayed_calls_before_arrival_by_port = {}
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


def test_connect_rejects_endpoint_whose_account_is_not_confirmed_paper(monkeypatch):
    """A successful socket connect to a Live-configured endpoint must never be trusted.

    Regression for the 2026-11-14 finding: the account snapshot used by the
    pre-order position guard is a SEPARATE connection from the one actually used
    to place the order. This verifies the guard on the ACTUAL order-placing
    connection returned by _connect_first_available_paper_broker.
    """
    FakeBroker.created_ports = []
    FakeBroker.successful_port = None  # both ports report connect() == True below
    FakeBroker.accounts_by_port = {4002: ("U7654321",), 7497: ("U7654321",)}
    FakeBroker.delayed_calls_before_arrival_by_port = {}
    monkeypatch.setattr(module, "IbkrBrokerAdapter", FakeBroker)

    original_connect = FakeBroker.connect
    FakeBroker.connect = lambda self: True
    try:
        try:
            module._connect_first_available_paper_broker()
        except RuntimeError as exc:
            assert "not confirmed Paper" in str(exc)
            assert "U7654321" not in str(exc)
        else:
            raise AssertionError("a non-DU managed account must never be accepted")
    finally:
        FakeBroker.connect = original_connect

    assert FakeBroker.created_ports == [4002, 7497]


def test_connect_falls_back_when_gateway_account_is_not_confirmed_paper(monkeypatch):
    FakeBroker.created_ports = []
    FakeBroker.accounts_by_port = {4002: ("U7654321",), 7497: ("DU1234567",)}
    FakeBroker.delayed_calls_before_arrival_by_port = {}
    monkeypatch.setattr(module, "IbkrBrokerAdapter", FakeBroker)

    original_connect = FakeBroker.connect
    FakeBroker.connect = lambda self: True
    try:
        broker = module._connect_first_available_paper_broker()
        assert broker.config.port == 7497
        assert broker.managed_accounts() == ("DU1234567",)
    finally:
        FakeBroker.connect = original_connect

    assert FakeBroker.created_ports == [4002, 7497]


def test_connect_waits_for_delayed_managed_accounts_callback(monkeypatch):
    """Codex finding (PR #374): connect() only waits on nextValidId, not managedAccounts.

    managedAccounts can legitimately arrive after connect() returns, so a
    valid Paper endpoint must not be rejected just because its account list
    is still empty on the very first read.
    """
    FakeBroker.created_ports = []
    FakeBroker.successful_port = 4002
    FakeBroker.accounts_by_port = {4002: ("DU1234567",)}
    # Empty on the first 2 reads, present from the 3rd read onward.
    FakeBroker.delayed_calls_before_arrival_by_port = {4002: 2}
    monkeypatch.setattr(module, "IbkrBrokerAdapter", FakeBroker)
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    broker = module._connect_first_available_paper_broker()

    assert broker.config.port == 4002
    assert broker.managed_accounts() == ("DU1234567",)
    assert FakeBroker.created_ports == [4002]


def test_connect_rejects_endpoint_with_zero_managed_accounts(monkeypatch):
    FakeBroker.created_ports = []
    FakeBroker.successful_port = None
    FakeBroker.accounts_by_port = {4002: (), 7497: ()}
    FakeBroker.delayed_calls_before_arrival_by_port = {}
    monkeypatch.setattr(module, "IbkrBrokerAdapter", FakeBroker)

    original_connect = FakeBroker.connect
    FakeBroker.connect = lambda self: True
    try:
        try:
            module._connect_first_available_paper_broker()
        except RuntimeError as exc:
            assert "not confirmed Paper" in str(exc)
        else:
            raise AssertionError("zero managed accounts must never be treated as confirmed Paper")
    finally:
        FakeBroker.connect = original_connect
