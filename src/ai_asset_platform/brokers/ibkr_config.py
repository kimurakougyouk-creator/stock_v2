from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IbkrConnectionConfig:
    host: str = "127.0.0.1"
    port: int = 4002
    client_id: int = 0
    paper_trading: bool = True
    allow_live_trading: bool = False

    def validate(self) -> None:
        if not self.host.strip():
            raise ValueError("IBKR hostが設定されていません。")

        if not 1 <= self.port <= 65535:
            raise ValueError("IBKR portが不正です。")

        if self.client_id < 0:
            raise ValueError("IBKR client_idは0以上にしてください。")

        if not self.paper_trading and not self.allow_live_trading:
            raise RuntimeError(
                "IBKR Live Tradingは安全ロックされています。"
            )


def create_ibkr_paper_config(
    *,
    use_gateway: bool = True,
) -> IbkrConnectionConfig:
    return IbkrConnectionConfig(
        host="127.0.0.1",
        port=4002 if use_gateway else 7497,
        client_id=0,
        paper_trading=True,
        allow_live_trading=False,
    )
