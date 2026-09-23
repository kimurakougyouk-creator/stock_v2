"""Fail-closed, versioned strategy-promotion policy evaluation.

This module evaluates already-persisted Paper strategy profitability evidence.
It never connects to a broker and never authorizes or performs a Live action.

A policy may exist in a disabled/unapproved state. Disabled or incomplete
policies always block. Even a passing promotion policy does not, by itself,
authorize normal Live strategy deployment; later roadmap phases and explicit
operator approval remain separate gates.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any

from ai_asset_platform.reports.performance import calculate_performance
from ai_asset_platform.reports.strategy_profitability_evidence import (
    audit_strategy_profitability_evidence,
    evidence_record as profitability_evidence_record,
    persist_strategy_profitability_evidence,
)
from ai_asset_platform.reports.strategy_source_attestation import (
    attest_strategy_source,
)

POLICY_SCHEMA_VERSION = 1
DECISION_SCHEMA_VERSION = 1
EXPECTED_PROFITABILITY_SCHEMA_VERSION = 4

DEFAULT_POLICY_PATH = Path("config/strategy_promotion_policy.json")
DEFAULT_PROFITABILITY_REPORT_PATH = Path(
    "results/strategy_profitability_evidence_latest.json"
)
DEFAULT_DECISION_REPORT_PATH = Path(
    "results/strategy_promotion_decision_latest.json"
)

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class StrategyPromotionPolicyError(ValueError):
    """Raised when policy/evidence cannot be interpreted without guessing."""


@dataclass(frozen=True)
class StrategyPromotionPolicy:
    schema_version: int
    policy_version: str
    enabled: bool
    strategy_source_sha: str | None = None
    minimum_closed_trades: int | None = None
    minimum_net_profit_account_currency: float | None = None
    maximum_drawdown_account_currency: float | None = None
    minimum_win_rate: float | None = None
    minimum_profit_factor: float | None = None
    minimum_observation_span_seconds: int | None = None
    maximum_evidence_age_seconds: int | None = None


@dataclass(frozen=True)
class StrategyPromotionDecision:
    status: str
    policy_version: str
    source_sha: str
    strategy_source_sha: str | None
    checked_at: str
    promotion_policy_passed: bool
    normal_live_strategy_deployment_allowed: bool
    blockers: tuple[str, ...]
    observed_closed_trades: int | None
    observed_net_profit_account_currency: float | None
    observed_maximum_drawdown_account_currency: float | None
    observed_win_rate: float | None
    observed_profit_factor: float | None
    observed_observation_span_seconds: int | None
    observed_evidence_age_seconds: int | None


def _exact_int(value: object, *, field: str, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise StrategyPromotionPolicyError(f"{field} must be an exact integer")
    if minimum is not None and value < minimum:
        raise StrategyPromotionPolicyError(f"{field} must be >= {minimum}")
    return value


def _finite_number(
    value: object,
    *,
    field: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StrategyPromotionPolicyError(f"{field} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise StrategyPromotionPolicyError(f"{field} must be finite")
    if minimum is not None and parsed < minimum:
        raise StrategyPromotionPolicyError(f"{field} must be >= {minimum}")
    if maximum is not None and parsed > maximum:
        raise StrategyPromotionPolicyError(f"{field} must be <= {maximum}")
    return parsed


def _optional_finite_number(
    value: object,
    *,
    field: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    if value is None:
        return None
    return _finite_number(
        value,
        field=field,
        minimum=minimum,
        maximum=maximum,
    )


def _parse_timestamp(value: object, *, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise StrategyPromotionPolicyError(f"{field} is missing")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise StrategyPromotionPolicyError(
            f"{field} is not valid ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StrategyPromotionPolicyError(
            f"{field} must be timezone-aware"
        )
    return parsed.astimezone(timezone.utc)


def load_strategy_promotion_policy(path: Path) -> StrategyPromotionPolicy:
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StrategyPromotionPolicyError(
            f"strategy promotion policy is unreadable: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise StrategyPromotionPolicyError(
            "strategy promotion policy must be a JSON object"
        )
    schema_version = _exact_int(
        payload.get("schema_version"),
        field="schema_version",
        minimum=1,
    )
    if schema_version != POLICY_SCHEMA_VERSION:
        raise StrategyPromotionPolicyError(
            "strategy promotion policy schema_version is unsupported"
        )
    policy_version = str(payload.get("policy_version") or "").strip()
    if not policy_version:
        raise StrategyPromotionPolicyError("policy_version is required")
    if type(payload.get("enabled")) is not bool:
        raise StrategyPromotionPolicyError("enabled must be an exact boolean")
    enabled = payload["enabled"]

    if not enabled:
        return StrategyPromotionPolicy(
            schema_version=schema_version,
            policy_version=policy_version,
            enabled=False,
        )

    strategy_source_sha = str(payload.get("strategy_source_sha") or "").strip().lower()
    if not _SHA_RE.fullmatch(strategy_source_sha):
        raise StrategyPromotionPolicyError(
            "strategy_source_sha must be an exact 40-character lowercase git SHA"
        )

    minimum_closed_trades = _exact_int(
        payload.get("minimum_closed_trades"),
        field="minimum_closed_trades",
        minimum=1,
    )
    minimum_net_profit = _finite_number(
        payload.get("minimum_net_profit_account_currency"),
        field="minimum_net_profit_account_currency",
        minimum=0.0,
    )
    maximum_drawdown = _finite_number(
        payload.get("maximum_drawdown_account_currency"),
        field="maximum_drawdown_account_currency",
        minimum=0.0,
    )
    minimum_win_rate = _optional_finite_number(
        payload.get("minimum_win_rate"),
        field="minimum_win_rate",
        minimum=0.0,
        maximum=100.0,
    )
    minimum_profit_factor = _optional_finite_number(
        payload.get("minimum_profit_factor"),
        field="minimum_profit_factor",
        minimum=0.0,
    )
    minimum_observation_span_seconds = _exact_int(
        payload.get("minimum_observation_span_seconds"),
        field="minimum_observation_span_seconds",
        minimum=0,
    )
    maximum_evidence_age_seconds = _exact_int(
        payload.get("maximum_evidence_age_seconds"),
        field="maximum_evidence_age_seconds",
        minimum=1,
    )
    return StrategyPromotionPolicy(
        schema_version=schema_version,
        policy_version=policy_version,
        enabled=True,
        strategy_source_sha=strategy_source_sha,
        minimum_closed_trades=minimum_closed_trades,
        minimum_net_profit_account_currency=minimum_net_profit,
        maximum_drawdown_account_currency=maximum_drawdown,
        minimum_win_rate=minimum_win_rate,
        minimum_profit_factor=minimum_profit_factor,
        minimum_observation_span_seconds=minimum_observation_span_seconds,
        maximum_evidence_age_seconds=maximum_evidence_age_seconds,
    )


def _profit_factor(net_performance: dict) -> float:
    raw = net_performance.get("profit_factor")
    if raw is None and net_performance.get("profit_factor_unbounded") is True:
        return math.inf
    return _finite_number(raw, field="net_performance.profit_factor", minimum=0.0)


def _same_number(left: float, right: float) -> bool:
    if math.isinf(left) or math.isinf(right):
        return left == right
    return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-9)


def _trade_times(realized_trades: object) -> tuple[datetime, datetime]:
    if not isinstance(realized_trades, list) or not realized_trades:
        raise StrategyPromotionPolicyError(
            "fee-aware realized_trades must be a non-empty list"
        )
    observed: list[datetime] = []
    sold_times: list[datetime] = []
    for index, trade in enumerate(realized_trades, start=1):
        if not isinstance(trade, dict):
            raise StrategyPromotionPolicyError(
                f"realized trade #{index} is not an object"
            )
        sold = _parse_timestamp(
            trade.get("sold_at"),
            field=f"realized trade #{index} sold_at",
        )
        sold_times.append(sold)
        observed.append(sold)
        contributions = trade.get("buy_contributions_weighted_average")
        if isinstance(contributions, list):
            for contribution_index, contribution in enumerate(
                contributions,
                start=1,
            ):
                if not isinstance(contribution, dict):
                    raise StrategyPromotionPolicyError(
                        f"realized trade #{index} buy contribution "
                        f"#{contribution_index} is not an object"
                    )
                created_at = contribution.get("created_at")
                if created_at not in (None, ""):
                    observed.append(
                        _parse_timestamp(
                            created_at,
                            field=(
                                f"realized trade #{index} buy contribution "
                                f"#{contribution_index} created_at"
                            ),
                        )
                    )
    return min(observed), max(sold_times)


def evaluate_strategy_promotion(
    profitability_report: dict[str, Any],
    policy: StrategyPromotionPolicy,
    *,
    source_sha: str,
    now: datetime | None = None,
) -> StrategyPromotionDecision:
    checked = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    source = str(source_sha or "").strip().lower()
    blockers: list[str] = []

    if not _SHA_RE.fullmatch(source):
        blockers.append("source_sha is not an exact 40-character lowercase git SHA")

    evidence_source = str(profitability_report.get("source_sha") or "").strip().lower() if isinstance(profitability_report, dict) else ""
    if not _SHA_RE.fullmatch(evidence_source):
        blockers.append("profitability report source_sha is missing or malformed")
    elif evidence_source != source:
        blockers.append("profitability report source_sha does not match evaluated source_sha")

    evidence_age_seconds: int | None = None
    if isinstance(profitability_report, dict):
        try:
            generated = _parse_timestamp(
                profitability_report.get("generated_at"),
                field="profitability report generated_at",
            )
            future_tolerance = timedelta(minutes=5)
            if generated > checked + future_tolerance:
                blockers.append("profitability report generated_at is unexpectedly in the future")
            else:
                evidence_age_seconds = max(
                    0,
                    int((checked - generated).total_seconds()),
                )
        except StrategyPromotionPolicyError as exc:
            blockers.append(str(exc))

    if not policy.enabled:
        blockers.append(
            "strategy-promotion policy is disabled pending explicit threshold approval"
        )

    observed_strategy_source = (
        str(profitability_report.get("strategy_source_sha") or "").strip().lower()
        if isinstance(profitability_report, dict)
        else ""
    )
    if not _SHA_RE.fullmatch(observed_strategy_source):
        blockers.append(
            "profitability report does not prove one exact strategy_source_sha across natural fills"
        )
    elif policy.enabled and observed_strategy_source != policy.strategy_source_sha:
        blockers.append(
            "profitability report strategy_source_sha does not match the policy target"
        )

    if not isinstance(profitability_report, dict):
        blockers.append("profitability report is not a JSON object")
        profitability_report = {}

    if profitability_report.get("schema_version") != EXPECTED_PROFITABILITY_SCHEMA_VERSION:
        blockers.append("profitability report schema_version is not the expected exact version")
    if profitability_report.get("paper_only") is not True:
        blockers.append("profitability report is not explicitly Paper-only")
    if profitability_report.get("broker_connection_used") is not False:
        blockers.append("profitability report unexpectedly used a broker connection")
    if profitability_report.get("order_sent") is not False:
        blockers.append("profitability report unexpectedly indicates an order send")
    if str(profitability_report.get("live_trading") or "").strip().upper() != "PROHIBITED":
        blockers.append("profitability report does not explicitly prohibit Live trading")
    if profitability_report.get("fees_accounted") is not True:
        blockers.append("fees_accounted is not proven true")
    if profitability_report.get("fee_aware") is not True:
        blockers.append("fee_aware is not proven true")

    closed_trades: int | None = None
    net_profit: float | None = None
    maximum_drawdown: float | None = None
    win_rate: float | None = None
    profit_factor: float | None = None
    observation_span_seconds: int | None = None
    evidence_age_observed: int | None = evidence_age_seconds

    try:
        closed_trades = _exact_int(
            profitability_report.get("closed_trade_count"),
            field="closed_trade_count",
            minimum=0,
        )
        net_profit = _finite_number(
            profitability_report.get("net_realized_pnl"),
            field="net_realized_pnl",
        )
        net_performance = profitability_report.get("net_performance")
        if not isinstance(net_performance, dict):
            raise StrategyPromotionPolicyError("net_performance is missing")
        trades = profitability_report.get("realized_trades")
        if not isinstance(trades, list) or len(trades) != closed_trades:
            raise StrategyPromotionPolicyError(
                "realized_trades count does not match closed_trade_count"
            )

        trade_pnls: list[float] = []
        for trade_index, trade in enumerate(trades, start=1):
            if not isinstance(trade, dict):
                raise StrategyPromotionPolicyError(
                    f"realized trade #{trade_index} is not an object"
                )
            trade_pnls.append(
                _finite_number(
                    trade.get("net_realized_pnl_account"),
                    field=(
                        f"realized trade #{trade_index} "
                        "net_realized_pnl_account"
                    ),
                )
            )
        recomputed = calculate_performance(trade_pnls)
        expected_status = (
            "NET_POSITIVE_AFTER_FEES"
            if recomputed.net_profit > 0
            else "NET_NON_POSITIVE_AFTER_FEES"
        )
        if profitability_report.get("evidence_status") != expected_status:
            raise StrategyPromotionPolicyError(
                "profitability evidence_status is inconsistent with realized trades"
            )
        if not _same_number(net_profit, float(recomputed.net_profit)):
            raise StrategyPromotionPolicyError(
                "top-level net_realized_pnl is inconsistent with realized trades"
            )

        reported_total = _exact_int(
            net_performance.get("total_trades"),
            field="net_performance.total_trades",
            minimum=0,
        )
        if reported_total != recomputed.total_trades:
            raise StrategyPromotionPolicyError(
                "net_performance.total_trades is inconsistent with realized trades"
            )
        reported_net_profit = _finite_number(
            net_performance.get("net_profit"),
            field="net_performance.net_profit",
        )
        reported_drawdown = _finite_number(
            net_performance.get("maximum_drawdown"),
            field="net_performance.maximum_drawdown",
            minimum=0.0,
        )
        reported_win_rate = _finite_number(
            net_performance.get("win_rate"),
            field="net_performance.win_rate",
            minimum=0.0,
            maximum=100.0,
        )
        reported_profit_factor = _profit_factor(net_performance)

        if not _same_number(reported_net_profit, float(recomputed.net_profit)):
            raise StrategyPromotionPolicyError(
                "net_performance.net_profit is inconsistent with realized trades"
            )
        if not _same_number(
            reported_drawdown,
            float(recomputed.maximum_drawdown),
        ):
            raise StrategyPromotionPolicyError(
                "net_performance.maximum_drawdown is inconsistent with realized trades"
            )
        if not _same_number(reported_win_rate, float(recomputed.win_rate)):
            raise StrategyPromotionPolicyError(
                "net_performance.win_rate is inconsistent with realized trades"
            )
        if not _same_number(
            reported_profit_factor,
            float(recomputed.profit_factor),
        ):
            raise StrategyPromotionPolicyError(
                "net_performance.profit_factor is inconsistent with realized trades"
            )

        net_profit = float(recomputed.net_profit)
        maximum_drawdown = float(recomputed.maximum_drawdown)
        win_rate = float(recomputed.win_rate)
        profit_factor = float(recomputed.profit_factor)

        first_time, latest_sold = _trade_times(trades)
        observation_span_seconds = max(
            0,
            int((latest_sold - first_time).total_seconds()),
        )
        future_tolerance = timedelta(minutes=5)
        if latest_sold > checked + future_tolerance:
            raise StrategyPromotionPolicyError(
                "latest realized trade timestamp is unexpectedly in the future"
            )
        latest_trade_age_seconds = max(
            0,
            int((checked - latest_sold).total_seconds()),
        )
        evidence_age_observed = max(
            evidence_age_observed or 0,
            latest_trade_age_seconds,
        )
    except StrategyPromotionPolicyError as exc:
        blockers.append(str(exc))

    if policy.enabled and not blockers:
        assert closed_trades is not None
        assert net_profit is not None
        assert maximum_drawdown is not None
        assert win_rate is not None
        assert profit_factor is not None
        assert observation_span_seconds is not None
        assert evidence_age_observed is not None
        assert policy.minimum_closed_trades is not None
        assert policy.minimum_net_profit_account_currency is not None
        assert policy.maximum_drawdown_account_currency is not None
        assert policy.minimum_observation_span_seconds is not None
        assert policy.maximum_evidence_age_seconds is not None

        if closed_trades < policy.minimum_closed_trades:
            blockers.append(
                f"closed trades {closed_trades} < required "
                f"{policy.minimum_closed_trades}"
            )
        if net_profit < policy.minimum_net_profit_account_currency:
            blockers.append(
                f"net profit {net_profit} < required "
                f"{policy.minimum_net_profit_account_currency}"
            )
        if maximum_drawdown > policy.maximum_drawdown_account_currency:
            blockers.append(
                f"maximum drawdown {maximum_drawdown} > allowed "
                f"{policy.maximum_drawdown_account_currency}"
            )
        if (
            policy.minimum_win_rate is not None
            and win_rate < policy.minimum_win_rate
        ):
            blockers.append(
                f"win rate {win_rate} < required {policy.minimum_win_rate}"
            )
        if (
            policy.minimum_profit_factor is not None
            and profit_factor < policy.minimum_profit_factor
        ):
            blockers.append(
                "profit factor is below the policy minimum"
            )
        if observation_span_seconds < policy.minimum_observation_span_seconds:
            blockers.append(
                f"observation span {observation_span_seconds}s < required "
                f"{policy.minimum_observation_span_seconds}s"
            )
        if evidence_age_observed > policy.maximum_evidence_age_seconds:
            blockers.append(
                f"evidence age {evidence_age_observed}s > allowed "
                f"{policy.maximum_evidence_age_seconds}s"
            )

    passed = policy.enabled and not blockers
    return StrategyPromotionDecision(
        status="PROMOTION_POLICY_PASS" if passed else "PROMOTION_POLICY_BLOCKED",
        policy_version=policy.policy_version,
        source_sha=source,
        strategy_source_sha=(
            observed_strategy_source
            if _SHA_RE.fullmatch(observed_strategy_source)
            else None
        ),
        checked_at=checked.isoformat(timespec="seconds"),
        promotion_policy_passed=passed,
        # A policy pass is evidence for Phase 5 only. It is never itself Live
        # authorization; later phases and explicit operator approval remain.
        normal_live_strategy_deployment_allowed=False,
        blockers=tuple(blockers),
        observed_closed_trades=closed_trades,
        observed_net_profit_account_currency=net_profit,
        observed_maximum_drawdown_account_currency=maximum_drawdown,
        observed_win_rate=win_rate,
        observed_profit_factor=(
            None if profit_factor is not None and math.isinf(profit_factor)
            else profit_factor
        ),
        observed_observation_span_seconds=observation_span_seconds,
        observed_evidence_age_seconds=evidence_age_observed,
    )


def decision_record(decision: StrategyPromotionDecision) -> dict:
    return {
        "schema_version": DECISION_SCHEMA_VERSION,
        **asdict(decision),
        "paper_evidence_only": True,
        "broker_connection_used": False,
        "order_sent": False,
        "live_order_sent": False,
        "live_trading": "PROHIBITED",
    }


def _load_json_object(path: Path, *, label: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StrategyPromotionPolicyError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise StrategyPromotionPolicyError(f"{label} must be a JSON object")
    return payload


def _git_head(repository_root: Path = Path(".")) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise StrategyPromotionPolicyError(
            "cannot determine exact strategy source SHA"
        ) from exc
    sha = result.stdout.strip().lower()
    if not _SHA_RE.fullmatch(sha):
        raise StrategyPromotionPolicyError(
            "git HEAD is not an exact 40-character lowercase SHA"
        )
    try:
        attest_strategy_source(sha, repository_root=repository_root)
    except RuntimeError as exc:
        raise StrategyPromotionPolicyError(str(exc)) from exc
    return sha


def persist_blocked_strategy_promotion_failure(
    reason: str,
    *,
    report_path: Path = DEFAULT_DECISION_REPORT_PATH,
) -> None:
    payload = {
        "schema_version": DECISION_SCHEMA_VERSION,
        "status": "PROMOTION_POLICY_BLOCKED",
        "policy_version": "UNAVAILABLE",
        "source_sha": None,
        "strategy_source_sha": None,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "promotion_policy_passed": False,
        "normal_live_strategy_deployment_allowed": False,
        "blockers": [str(reason)],
        "observed_closed_trades": None,
        "observed_net_profit_account_currency": None,
        "observed_maximum_drawdown_account_currency": None,
        "observed_win_rate": None,
        "observed_profit_factor": None,
        "observed_observation_span_seconds": None,
        "observed_evidence_age_seconds": None,
        "paper_evidence_only": True,
        "broker_connection_used": False,
        "order_sent": False,
        "live_order_sent": False,
        "live_trading": "PROHIBITED",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(report_path)


def persist_strategy_promotion_decision(
    decision: StrategyPromotionDecision,
    *,
    report_path: Path = DEFAULT_DECISION_REPORT_PATH,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            decision_record(decision),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(report_path)


def main() -> int:
    try:
        policy = load_strategy_promotion_policy(DEFAULT_POLICY_PATH)
        source_sha = _git_head()

        # Never trust the mutable ignored profitability JSON as the authority
        # for promotion. Rebuild it from the raw Paper fill and commission
        # ledgers in this same attested source run, persist that canonical
        # artifact, and evaluate the exact in-memory record just generated.
        profitability_result = audit_strategy_profitability_evidence()
        persist_strategy_profitability_evidence(
            profitability_result,
            source_sha=source_sha,
        )
        profitability = profitability_evidence_record(
            profitability_result,
            source_sha=source_sha,
        )
        decision = evaluate_strategy_promotion(
            profitability,
            policy,
            source_sha=source_sha,
        )
    except StrategyPromotionPolicyError as exc:
        try:
            persist_blocked_strategy_promotion_failure(str(exc))
        except OSError:
            pass
        print("===== STRATEGY PROMOTION POLICY =====")
        print("STATUS      : PROMOTION_POLICY_BLOCKED")
        print("REASON      :", exc)
        print("LIVE TRADING: PROHIBITED")
        return 1

    persist_strategy_promotion_decision(decision)
    print("===== STRATEGY PROMOTION POLICY =====")
    print("STATUS       :", decision.status)
    print("POLICY       :", decision.policy_version)
    print("SOURCE SHA   :", decision.source_sha)
    print("PASSED       :", decision.promotion_policy_passed)
    print("LIVE ALLOWED :", decision.normal_live_strategy_deployment_allowed)
    print("BLOCKERS     :", list(decision.blockers))
    print("REPORT       :", DEFAULT_DECISION_REPORT_PATH)
    print("BROKER USED  : False")
    print("ORDER SENT   : False")
    print("LIVE TRADING : PROHIBITED")
    return 0 if decision.promotion_policy_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())