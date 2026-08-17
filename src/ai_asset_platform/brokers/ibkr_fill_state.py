from __future__ import annotations

import json
import os
from pathlib import Path


class IbkrFillStateStore:
    """
    IBKRの処理済み累積約定数量をJSONへ安全に保存・復元する。

    注文送信や口座更新は行わない。
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save(self, processed_filled: dict[int, float]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "version": 1,
            "processed_filled": {
                str(order_id): float(quantity)
                for order_id, quantity in processed_filled.items()
            },
        }

        temporary_path = self.path.with_suffix(
            self.path.suffix + ".tmp"
        )

        temporary_path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        os.replace(temporary_path, self.path)

    def load(self) -> dict[int, float]:
        if not self.path.exists():
            return {}

        try:
            payload = json.loads(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                "IBKR約定状態ファイルを読み込めません。"
            ) from exc

        if payload.get("version") != 1:
            raise ValueError(
                "IBKR約定状態ファイルのversionが不正です。"
            )

        raw = payload.get("processed_filled")

        if not isinstance(raw, dict):
            raise ValueError(
                "IBKR約定状態ファイルの形式が不正です。"
            )

        restored: dict[int, float] = {}

        for raw_order_id, raw_quantity in raw.items():
            try:
                order_id = int(raw_order_id)
                quantity = float(raw_quantity)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "IBKR約定状態ファイルの値が不正です。"
                ) from exc

            if order_id < 0:
                raise ValueError(
                    "IBKR order_idは0以上にしてください。"
                )

            if quantity < 0:
                raise ValueError(
                    "IBKR処理済み約定数量は0以上にしてください。"
                )

            restored[order_id] = quantity

        return restored
