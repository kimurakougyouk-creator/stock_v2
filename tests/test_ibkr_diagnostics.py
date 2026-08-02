from importlib import metadata

from ai_asset_platform.brokers import ibkr_diagnostics


def test_diagnose_ibkr_environment_ready(monkeypatch):
    monkeypatch.setattr(
        ibkr_diagnostics.util,
        "find_spec",
        lambda name: object() if name == "ibapi" else None,
    )

    versions = {
        "ibapi": "10.45.1",
        "protobuf": "5.29.5",
    }
    monkeypatch.setattr(
        ibkr_diagnostics.metadata,
        "version",
        lambda name: versions[name],
    )

    result = ibkr_diagnostics.diagnose_ibkr_environment()

    assert result.status == "READY"
    assert result.is_ready is True
    assert result.ibapi_installed is True
    assert result.ibapi_version == "10.45.1"
    assert result.protobuf_version == "5.29.5"


def test_diagnose_ibkr_environment_not_ready(monkeypatch):
    monkeypatch.setattr(
        ibkr_diagnostics.util,
        "find_spec",
        lambda name: None,
    )

    def missing(name):
        if name == "ibapi":
            raise metadata.PackageNotFoundError
        return "5.29.5"

    monkeypatch.setattr(
        ibkr_diagnostics.metadata,
        "version",
        missing,
    )

    result = ibkr_diagnostics.diagnose_ibkr_environment()

    assert result.status == "NOT_READY"
    assert result.is_ready is False
    assert result.ibapi_installed is False
    assert result.ibapi_version is None
