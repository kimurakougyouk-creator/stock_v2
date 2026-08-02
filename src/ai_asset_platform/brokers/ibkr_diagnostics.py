from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata, util


@dataclass(frozen=True)
class IbkrEnvironmentDiagnostic:
    status: str
    message: str
    ibapi_installed: bool
    ibapi_version: str | None
    protobuf_version: str | None

    @property
    def is_ready(self) -> bool:
        return self.status == "READY"


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def diagnose_ibkr_environment() -> IbkrEnvironmentDiagnostic:
    """IBKR Python APIを利用できる環境か自動診断する。"""
    ibapi_installed = util.find_spec("ibapi") is not None
    ibapi_version = _package_version("ibapi")
    protobuf_version = _package_version("protobuf")

    if not ibapi_installed or ibapi_version is None:
        return IbkrEnvironmentDiagnostic(
            status="NOT_READY",
            message="IBKR Python API (ibapi) が導入されていません。",
            ibapi_installed=False,
            ibapi_version=ibapi_version,
            protobuf_version=protobuf_version,
        )

    return IbkrEnvironmentDiagnostic(
        status="READY",
        message=f"IBKR Python APIを利用できます。ibapi={ibapi_version}",
        ibapi_installed=True,
        ibapi_version=ibapi_version,
        protobuf_version=protobuf_version,
    )
