from __future__ import annotations

import hashlib
import html
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from config import EMAIL_ADDRESS, APP_PASSWORD
from mail import send_mail


def _safe_numeric(value: Any) -> float:
    if value is None:
        return float("nan")
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return float("nan")
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return float("nan")
    if pd.isna(numeric):
        return float("nan")
    return numeric


def _rank_level(value: Any) -> int:
    if value is None:
        return -1
    if isinstance(value, str):
        text = value.strip().upper()
        mapping = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1}
        return mapping.get(text, -1)
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return -1
    if pd.isna(numeric):
        return -1
    return int(numeric)


def _normalize_df(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    if isinstance(df, pd.DataFrame):
        return df.copy()
    return pd.DataFrame(df)


def _build_signature(df: pd.DataFrame) -> str:
    normalized = df.copy()
    columns = ["Ticker", "Signal", "Score", "Rank", "Close", "RSI", "MACD", "ATR", "ReferenceShares", "ReferenceAmountYen", "StopPrice", "PositionSizingReason"]

    def normalize_value(value: Any) -> Any:
        if value is None:
            return ""
        if isinstance(value, str):
            text = value.strip()
            return text if text else ""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if pd.isna(value):
                return ""
            return float(value)
        return str(value).strip() if isinstance(value, str) else str(value)

    for column in normalized.columns:
        normalized[column] = normalized[column].apply(normalize_value)

    normalized = normalized.reindex(columns=columns + [col for col in normalized.columns if col not in columns], fill_value="")
    if "Ticker" in normalized.columns:
        normalized = normalized.sort_values("Ticker", kind="mergesort")
    normalized = normalized.reset_index(drop=True)
    payload = normalized.to_json(orient="records", force_ascii=False, date_format="iso")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe_read_previous(base_dir: Path) -> pd.DataFrame:
    previous_path = base_dir / "previous_signals.xlsx"
    if not previous_path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_excel(previous_path)
    except Exception:
        return pd.DataFrame()
    return df


def _write_excel(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(exist_ok=True, parents=True)
    df.to_excel(path, index=False)


def _history_path(base_dir: Path, timestamp: datetime) -> Path:
    history_dir = base_dir / "history"
    history_dir.mkdir(exist_ok=True, parents=True)
    filename = timestamp.strftime("signals_%Y%m%d_%H%M%S.xlsx")
    return history_dir / filename


def _build_change_rows(previous_df: pd.DataFrame, current_df: pd.DataFrame) -> list[dict[str, Any]]:
    previous_map = {str(row.get("Ticker", "")): row for _, row in previous_df.iterrows() if str(row.get("Ticker", "")).strip()}
    current_map = {str(row.get("Ticker", "")): row for _, row in current_df.iterrows() if str(row.get("Ticker", "")).strip()}
    all_tickers = sorted(set(previous_map) | set(current_map))

    change_rows: list[dict[str, Any]] = []
    for ticker in all_tickers:
        prev_row = previous_map.get(ticker)
        curr_row = current_map.get(ticker)
        if prev_row is None:
            change_rows.append({
                "Ticker": ticker,
                "PreviousSignal": "-",
                "CurrentSignal": str(curr_row.get("Signal", "HOLD")) if curr_row is not None else "-",
                "PreviousScore": 0.0,
                "CurrentScore": _safe_numeric(curr_row.get("Score")) if curr_row is not None else 0.0,
                "ScoreChange": 0.0,
                "PreviousRank": "-",
                "CurrentRank": str(curr_row.get("Rank", "-")) if curr_row is not None else "-",
                "ChangeType": "NewTicker",
                "ChangeReason": "新規銘柄として追加されました。",
                "IsImportant": True,
            })
            continue
        if curr_row is None:
            change_rows.append({
                "Ticker": ticker,
                "PreviousSignal": str(prev_row.get("Signal", "HOLD")),
                "CurrentSignal": "-",
                "PreviousScore": _safe_numeric(prev_row.get("Score")),
                "CurrentScore": 0.0,
                "ScoreChange": 0.0,
                "PreviousRank": str(prev_row.get("Rank", "-")),
                "CurrentRank": "-",
                "ChangeType": "RemovedTicker",
                "ChangeReason": "前回から消えた銘柄です。",
                "IsImportant": True,
            })
            continue

        previous_signal = str(prev_row.get("Signal", "HOLD"))
        current_signal = str(curr_row.get("Signal", "HOLD"))
        previous_score = _safe_numeric(prev_row.get("Score"))
        current_score = _safe_numeric(curr_row.get("Score"))
        previous_rank = _rank_level(prev_row.get("Rank"))
        current_rank = _rank_level(curr_row.get("Rank"))
        score_change = current_score - previous_score
        change_type = "NoChange"
        change_reason = "変更なし"
        is_important = False

        if previous_signal != current_signal and {previous_signal, current_signal} <= {"BUY", "SELL", "HOLD"}:
            change_type = "SignalChange"
            change_reason = f"Signalが {previous_signal} → {current_signal} に変化しました。"
            is_important = True
        elif abs(score_change) >= 15:
            change_type = "ScoreChange"
            change_reason = f"Scoreが {previous_score:.1f} → {current_score:.1f} に変化しました。"
            is_important = True
        elif abs(previous_rank - current_rank) >= 2:
            change_type = "RankChange"
            change_reason = f"Rankが {prev_row.get('Rank', '-')} → {curr_row.get('Rank', '-')} に変化しました。"
            is_important = True

        if change_type != "NoChange":
            change_rows.append({
                "Ticker": ticker,
                "PreviousSignal": previous_signal,
                "CurrentSignal": current_signal,
                "PreviousScore": previous_score,
                "CurrentScore": current_score,
                "ScoreChange": score_change,
                "PreviousRank": prev_row.get("Rank", "-"),
                "CurrentRank": curr_row.get("Rank", "-"),
                "ChangeType": change_type,
                "ChangeReason": change_reason,
                "IsImportant": is_important,
            })

    return change_rows


def update_change_tracking(current_df: pd.DataFrame | None, base_dir: Path | None = None, send_mail_fn: Callable[..., Any] | None = None) -> dict[str, Any]:
    base_dir = Path(base_dir or Path("results"))
    base_dir.mkdir(exist_ok=True, parents=True)

    current_df = _normalize_df(current_df)
    current_df = current_df.copy()
    if "Ticker" not in current_df.columns:
        current_df["Ticker"] = [f"unknown_{index}" for index in range(len(current_df))]
    for column in ["Signal", "Score", "Rank", "Close", "RSI", "MACD", "ATR", "ReferenceShares", "ReferenceAmountYen", "StopPrice", "PositionSizingReason"]:
        if column not in current_df.columns:
            current_df[column] = None
    current_df["Score"] = pd.to_numeric(current_df["Score"], errors="coerce")
    current_df["Rank"] = current_df["Rank"].fillna("")

    previous_df = _safe_read_previous(base_dir)
    previous_df = _normalize_df(previous_df)

    previous_path = base_dir / "previous_signals.xlsx"
    previous_signature = _build_signature(previous_df)
    current_signature = _build_signature(current_df)

    is_first_run = not previous_path.exists() or previous_df.empty
    history_created = False
    if is_first_run:
        _write_excel(previous_path, current_df)
        _write_excel(base_dir / "latest_changes.xlsx", pd.DataFrame(columns=[
            "Ticker",
            "PreviousSignal",
            "CurrentSignal",
            "PreviousScore",
            "CurrentScore",
            "ScoreChange",
            "PreviousRank",
            "CurrentRank",
            "ChangeType",
            "ChangeReason",
            "IsImportant",
        ]))
    else:
        change_rows = _build_change_rows(previous_df, current_df)
        important_changes = [row for row in change_rows if row.get("IsImportant")]
        changes_df = pd.DataFrame(change_rows)
        _write_excel(base_dir / "latest_changes.xlsx", changes_df)
        if important_changes:
            message_lines = ["重要変化通知", ""]
            for row in important_changes:
                message_lines.append(f"- {row['Ticker']}: {row['PreviousSignal']} -> {row['CurrentSignal']} / Score {row['PreviousScore']:.1f} -> {row['CurrentScore']:.1f} / Rank {row['PreviousRank']} -> {row['CurrentRank']} / {row['ChangeReason']}")
            if send_mail_fn is not None:
                send_mail_fn(EMAIL_ADDRESS, APP_PASSWORD, EMAIL_ADDRESS, "重要変化通知", "\n".join(message_lines))
            else:
                send_mail(EMAIL_ADDRESS, APP_PASSWORD, EMAIL_ADDRESS, "重要変化通知", "\n".join(message_lines))

    history_dir = base_dir / "history"
    history_dir.mkdir(exist_ok=True, parents=True)
    history_files = list(history_dir.glob("signals_*.xlsx"))
    current_timestamp = datetime.now()
    history_path = _history_path(base_dir, current_timestamp)
    if is_first_run:
        _write_excel(history_path, current_df)
        history_created = True
    elif previous_signature != current_signature:
        existing_signatures = []
        for history_file in history_files:
            try:
                history_df = pd.read_excel(history_file)
            except Exception:
                continue
            existing_signatures.append(_build_signature(history_df))
        if current_signature not in existing_signatures:
            _write_excel(history_path, current_df)
            history_created = True

    _write_excel(previous_path, current_df)

    changes_df = pd.read_excel(base_dir / "latest_changes.xlsx") if (base_dir / "latest_changes.xlsx").exists() else pd.DataFrame(columns=[
        "Ticker",
        "PreviousSignal",
        "CurrentSignal",
        "PreviousScore",
        "CurrentScore",
        "ScoreChange",
        "PreviousRank",
        "CurrentRank",
        "ChangeType",
        "ChangeReason",
        "IsImportant",
    ])
    important_changes = [row for _, row in changes_df.iterrows() if str(row.get("IsImportant", "")).lower() in {"true", "1", "yes"}]

    return {
        "is_first_run": is_first_run,
        "history_created": history_created,
        "important_change_count": len(important_changes),
        "important_changes": [
            {
                "Ticker": row.get("Ticker"),
                "PreviousSignal": row.get("PreviousSignal"),
                "CurrentSignal": row.get("CurrentSignal"),
                "PreviousScore": row.get("PreviousScore"),
                "CurrentScore": row.get("CurrentScore"),
                "ScoreChange": row.get("ScoreChange"),
                "PreviousRank": row.get("PreviousRank"),
                "CurrentRank": row.get("CurrentRank"),
                "ChangeType": row.get("ChangeType"),
                "ChangeReason": row.get("ChangeReason"),
                "IsImportant": str(row.get("IsImportant", "")).lower() in {"true", "1", "yes"},
            }
            for _, row in changes_df.iterrows()
        ],
        "previous_path": str(previous_path),
        "history_path": str(history_path),
    }


def main() -> None:
    from signal_runner import run_signal_scan

    signal_result = run_signal_scan()
    current_df = pd.DataFrame(signal_result.get("records", []))
    update_change_tracking(current_df, base_dir=Path("results"))


if __name__ == "__main__":
    main()
