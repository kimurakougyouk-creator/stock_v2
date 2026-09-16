"""Regression tests for the Codex findings on PR #287 / Issue #285.

Original finding (P1, first review): pytest's `pythonpath = src` setting
(pytest.ini) makes `import ai_asset_platform` succeed inside pytest even when
the package is not actually installed anywhere. That masked the fact that the
IBKR operational wrapper scripts, which invoke `python -m ai_asset_platform...`
directly (not through pytest), had no way to resolve the package once their
explicit `PYTHONPATH` export was removed. Fixed by `scripts/setup.sh` /
`.github/workflows/pytest.yml` running `pip install -e .`.

Follow-up finding (P1, second review): venv activation (`source
.venv/bin/activate`) does not clear a `PYTHONPATH` inherited from the parent
shell/service environment, and inherited `PYTHONPATH` entries resolve before
the venv's own site-packages (where the editable install lives). A stale or
attacker-controlled `PYTHONPATH` could therefore still shadow the editable
install in every operational wrapper. Fixed by adding `unset PYTHONPATH`
immediately after `source .venv/bin/activate` in every wrapper script, before
any `ai_asset_platform` invocation. This file verifies (a) statically that
every such wrapper carries the fix in the right place, and (b) dynamically
that the fix mechanism actually defeats a hostile inherited `PYTHONPATH`.

P2 (offline-safety) design note / responsibility split (post CI #2046):
earlier revisions of this file ran a real `pip install -e .` inside a
disposable venv to prove the editable install resolves to the current
checkout, offline-safe via `/usr/share/python-wheels`. That path was dropped:
the exact contents of `/usr/share/python-wheels` are not guaranteed across
hosts or CI images (CI #2046 failed with `error: invalid command
'bdist_wheel'` because that directory had setuptools but not wheel there),
so a test that depends on it is not reliably offline-safe. That
verification is not this file's job: `.github/workflows/pytest.yml` already
runs the real `pip install -e .` followed by a "Verify plain-python runtime
import" step that asserts `ai_asset_platform.__file__` resolves to this
exact checkout -- and that step passed in CI #2046. This file instead only
needs to prove the *PYTHONPATH-shadowing* property (P1), which does not
require a real editable install: a single `.pth` file pointing at `src/`
reproduces the one thing that matters here -- "ai_asset_platform is
reachable via a site-packages path entry, at lower sys.path priority than an
inherited PYTHONPATH" -- without pip, setuptools, wheel, apt, or the
network.

Follow-up finding (P1, third review): unsetting PYTHONPATH in the wrappers
is only safe once an existing `.venv` is actually editable-installed against
the current checkout. `install_ibkr_readonly_autopilot.sh` (the installer
for the unattended read-only autopilot service) only ran `pytest`, whose
success is masked by pytest.ini's `pythonpath = src` regardless of whether
`.venv` has ai_asset_platform installed at all. An operator upgrading an
older install (pre editable-install, when the wrapper relied on an
externally exported PYTHONPATH) could restart the service, have the wrapper
correctly `unset PYTHONPATH`, and then hit `ModuleNotFoundError` under
plain `python -m ai_asset_platform...` -- silently stopping the read-only
monitor. Fixed by having the installer run `pip install -e .` (migrating
any pre-existing `.venv`) and the new shared fail-closed checker
`scripts/verify_exact_checkout_import.py` -- under `set -euo pipefail`, so a
failed migration/verification aborts before `systemctl --user restart` is
ever reached -- immediately after activating `.venv` and before the
pytest-based checks. `scripts/setup.sh` now calls the same shared checker
(previously an inline duplicate) so the fresh-setup and existing-install
paths share one verification.

Follow-up finding (P1, fourth review / Codex + ChatGPT audit, PR #287):
two remaining gaps in the same family.

(a) `ibkr_closed_spy_fx_ledger_repair_once.sh` and
`ibkr_verified_derivative_ledger_cleanup_once.sh` wrapped `source
.venv/bin/activate` + `unset PYTHONPATH` inside `if [[ -f .venv/bin/activate
]]; then ... fi`. When `.venv` is missing, that whole block -- including
`unset PYTHONPATH` -- is skipped, but the later `pytest`/`python -m
ai_asset_platform...` calls are unconditional, so an inherited PYTHONPATH
would still leak through. Fixed by making the `.venv` check fail-closed
(`if [[ ! -f .venv/bin/activate ]]; then ... exit 2; fi`) and moving
`source`/`unset` to unconditional top-level statements, matching the
pattern the other wrappers already use.

(b) `ibkr_readonly_soak_once.sh` activates `.venv` and runs `python -m
pytest -q`, then delegates to `bash ./ibkr_auto.sh` -- it never invokes
`ai_asset_platform` directly, so `_discover_operational_wrappers()` (which
only matches direct `python -m ai_asset_platform` invocations) never saw
it, and it was missing `unset PYTHONPATH` entirely. Fixed by adding `unset
PYTHONPATH` immediately after `source .venv/bin/activate`, and covered here
by a dedicated test rather than widening `_discover_operational_wrappers()`
(which would also start matching unrelated pytest-only scripts like
`scripts/setup.sh` that are already independently exact-checkout-safe via
`scripts/verify_exact_checkout_import.py` and don't need this check).

(c) `install_ibkr_readonly_autopilot.sh` ran `pip install -e .` and the
fail-closed verifier with the parent environment's `PYTHONPATH` still set,
so a stale/hostile inherited PYTHONPATH could shadow the editable install
during the migration/verification itself. Fixed by adding `unset
PYTHONPATH` immediately after `source .venv/bin/activate`, before `pip
install -e .`.

This file also adds a structural check (`_bash_conditional_depths`) to
`test_all_operational_wrappers_clear_inherited_pythonpath_before_first_use`:
finding `unset PYTHONPATH` textually between `activate` and the first
`ai_asset_platform` call is not enough on its own -- (a) above passed that
check while still being vulnerable, because `unset` sat inside an `if`
block that the first invocation could reach without. The added check
tracks bash `if`/`fi` nesting depth per line and requires `unset`'s depth
to be no deeper than the first invocation's, so `unset` can never be
skippable via a path the invocation itself isn't also skipped by.

Follow-up finding (P1, fifth review / Codex, PR #287): `_WRAPPER_INVOCATION_RE`
only matched `python -m ai_asset_platform...`, so `ibkr_future_whatif_once.sh`
-- which runs `python - <<'PY'` and `import`s `ai_asset_platform` from
*inside* the heredoc body, not via `-m` -- was invisible to
`_discover_operational_wrappers()` and missing `unset PYTHONPATH` entirely.
A read-only audit of every root and `scripts/*.sh` file for `python -`,
`python3 -c`, and any other `import ai_asset_platform`/`from
ai_asset_platform` invocation form found no other instance of this pattern
(`ibkr_auto.sh` and `ibkr_overnight_e2e_once.sh` also use `python -
<<'PY'`, but only for a socket-wait loop that never imports
ai_asset_platform, so they were never affected). Fixed by adding `unset
PYTHONPATH` immediately after `source .venv/bin/activate` in
`ibkr_future_whatif_once.sh`, and by generalizing detection:
`_find_first_ai_asset_platform_invocation` now also recognizes a `python -`
/ `python3 -` heredoc whose body contains an `ai_asset_platform` import, so
`_discover_operational_wrappers()` and the main structural test cover both
invocation forms, and any future stdin-based wrapper that forgets `unset
PYTHONPATH` will fail this test.

Follow-up finding (P1, sixth review / Codex, PR #287): `ibkr_auto.sh` has
its own independent self-update path -- it runs `git pull --ff-only origin
main` on every cycle, unrelated to `install_ibkr_readonly_autopilot.sh`'s
migration/verification (which only runs when the installer itself is
re-run). An older `.venv` (created by a pre-editable-install
`scripts/setup.sh`) could pull in a newer checkout, correctly `unset
PYTHONPATH`, and then hit `ModuleNotFoundError` or resolve
`ai_asset_platform` to a stale/wrong checkout once the first `python -m
ai_asset_platform...` call runs. Fixed by reusing the exact same pattern
already established (and CI/operator-tested) in
`install_ibkr_readonly_autopilot.sh`: immediately after `unset PYTHONPATH`
and before any `ai_asset_platform` invocation, `ibkr_auto.sh` now runs
`python -m pip install -e .` (migrating the `.venv`) and the shared
`scripts/verify_exact_checkout_import.py` checker -- no new/duplicate
verifier, no new flags. `set -euo pipefail` (already at the top of the
file) means a failed migration or verification aborts the rest of the
cycle before any ai_asset_platform module runs. This does not add a new
network dependency: the preceding `git pull` on the same execution path
already requires network reachability, and this exact `pip install -e .`
invocation (no `--no-build-isolation`/`--no-index`) is the same one already
used and passing in `scripts/setup.sh`, `install_ibkr_readonly_autopilot.sh`,
and `.github/workflows/pytest.yml`.

Follow-up finding (P1-A/P1-B, seventh review / Codex, cross-cutting, PR
#287 Stage1): the sixth-review fix above was a one-off patch of
`ibkr_auto.sh` alone, and it was itself unsafe. A read-only, mechanical
audit of every root and `scripts/*.sh` file for a git self-update
(`pull`/`fetch`/`switch`/`checkout`) found 31 self-updating wrappers, not
just `ibkr_auto.sh` -- e.g. `ibkr_crypto_whatif_once.sh`,
`ibkr_future_whatif_once.sh`, `ibkr_option_paper_roundtrip_once.sh`, and
27 others, all with the same P1-A shape (self-update -> activate -> unset
PYTHONPATH -> direct `ai_asset_platform` use, with no migration/verify at
all). Patching each individually, copy-pasting `pip install -e .` +
`verify_exact_checkout_import.py` into every one of them, was rejected: it
also reproduces P1-B -- unconditionally calling `pip install -e .` breaks
`ibkr_auto.sh`'s own documented contract of continuing read-only
monitoring when `git pull` fails/origin is unreachable, because PEP 517
build isolation needs the network to fetch the build backend
(`setuptools>=68`, per `pyproject.toml`), and this repo's own `.venv` does
*not* retain setuptools/wheel after its own initial editable install
(verified empirically: a fresh `python3 -m venv .venv` plus a real
`pip install -e .` leaves neither `setuptools` nor `wheel` importable
afterward), so `--no-build-isolation` cannot be assumed to work on an
arbitrary already-set-up `.venv` either.

Fixed with one shared helper, `scripts/ensure_exact_checkout_runtime.sh`,
reusing (not duplicating) `scripts/verify_exact_checkout_import.py`:
verify first; only migrate (`pip install -e .`) if that verify fails; then
re-verify; fail closed if either check still fails. In the steady state
(the common case: `.venv` already migrated once), this never calls `pip`
and never touches the network -- verified empirically to complete in
under 50ms with no build backend contacted, versus several seconds with
real network I/O when migration is actually needed. This makes every
self-updating wrapper's `git`-pull-failure-tolerance (where it has one)
and offline-capability strictly no worse than before, while still
guaranteeing `ai_asset_platform` is bound to the exact current checkout
before use, or the wrapper fails closed. All 30 self-updating wrappers with
a direct `ai_asset_platform` use now call this one helper (`ibkr_auto.sh`
itself was changed from its sixth-review inline pip+verify to the same
helper call, for one design instead of two); `ibkr_readonly_soak_once.sh`
is self-updating but never uses `ai_asset_platform` directly (it only runs
`pytest` and delegates to `bash ./ibkr_auto.sh`, which gates itself), so it
does not need its own gate. `scripts/setup.sh` and
`install_ibkr_readonly_autopilot.sh` were left unchanged: neither has a
"continue when offline" contract (the installer doesn't even `git pull`),
so their existing unconditional `pip install -e .` + verify is already
safe for their own contract, and rewriting already-tested, working files
without a safety need would be scope creep beyond this Stage1 fix.

The cross-cutting discovery this file uses (`_discover_self_updating_wrappers`)
is mechanical (matches on `git pull`/`fetch`/`switch`/`checkout`, not a
hard-coded filename list), so a future self-updating wrapper that forgets
this helper will fail `test_all_self_updating_wrappers_bind_exact_checkout_before_first_use`
automatically.

Follow-up finding (P1, eighth review / Codex, `ibkr_all_readonly_completion_once.sh`):
the helper call being present and correctly *positioned* before the first
ai_asset_platform use is not enough -- a failed helper call must actually
stop the script from reaching that use. `ibkr_all_readonly_completion_once.sh`
ran under `set -uo pipefail` (no `-e`, intentionally, so `run_readonly_step`
can collect individual audit-step failures instead of aborting on the
first one) with a bare, unchecked helper call, so a failed exact-checkout
binding would not have stopped anything. Fixed by explicitly checking the
helper's exit status (`if ! bash scripts/ensure_exact_checkout_runtime.sh;
then echo BLOCKED...; exit 2; fi`) without touching `set -uo pipefail` or
the "run every audit step" design elsewhere in the file.
`_helper_failure_is_fail_closed`/`_classify_helper_call_control_flow`
verify this for every helper-calling wrapper.

Follow-up finding (P1, ninth review / ChatGPT re-audit): the first version
of that control-flow check treated "the helper call is the condition of
some `if`" as sufficient proof of safety on its own. It is not:
`if ! helper; then echo; fi` and `if helper; then echo ok; fi` both let a
helper failure fall straight through to later code, and both would have
been misclassified as safe. `_classify_helper_call_control_flow` now
requires an actual unconditional `exit`/`return`/`exec` reachable on the
failure path (`if ! helper; then ... exit ...; fi`, or `helper || exit N`
/ `helper || { ...; exit N; }` on the same line) -- a non-negated
`if helper; then ...; fi` (or anything more complex: elif chains, a
while/until condition, a pipeline, a case statement, a multi-line
continuation) is never assumed safe; it is either proven safe by this
narrow set of recognized patterns or treated as unverified/unsafe.

Follow-up finding (P1, tenth review / ChatGPT re-audit): for `if ! helper;
then ...; fi`, the exit-search originally scanned the *entire* if/fi
block at the `then` body's depth, not just the `then` branch specifically.
Since `elif`/`else` don't change depth in `_bash_conditional_depths` (they
are siblings of `then`, not nested inside it), an `exit` sitting in an
`else` or `elif` branch -- which only runs on *success*, never on the
helper *failure* this whole check is about -- was being read as proof the
failure path exits too, which it does not:
`if ! helper; then echo failed; else exit 2; fi` was misclassified safe.
`_then_branch_end_index` now bounds the exit search to the `then` branch
only (from the `if` line up to the first `elif`/`else` at that same
depth, or the block's own `fi` if there is none).

Follow-up finding (P1, eleventh review / ChatGPT re-audit): two more
false-SAFE vectors in the same static proof. (a) `_EXIT_STATEMENT_RE`
accepted `return` and bare `exec` as proof of an unconditional exit;
`return` does not exit a top-level wrapper script (only a function), and
a bare/redirection-only `exec` (e.g. `exec >log.txt`) does not replace
the process or exit either -- both let control fall through just like no
statement at all, and neither is used as an exit mechanism anywhere in
this repo. Only a literal `exit` now counts. (b) the `helper || ...`
same-line check was a loose "`||` appears, and the word exit appears
somewhere after it" search, which treated `|| echo "please exit 2"`,
`|| true  # exit 2`, and `|| printf 'exit 2\n'` as if they exited, when
none of them do -- "exit" as text inside a string/comment/printf format
is not an executed exit statement. `_HELPER_OR_EXIT_RE` now requires the
*entire* line to be exactly `bash scripts/.../ensure_exact_checkout_runtime.sh
|| exit [status]`; a brace-group form (`helper || { ...; exit N; }`) is no
longer recognized as safe either -- not used by any real wrapper, and
correctly parsing a brace group's contents (multiple statements, nested
quoting) is beyond what this line-based check can prove, so it is now
treated as unverified/unsafe rather than assumed safe.
"""
import os
import re
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
EXPECTED_INIT_FILE = (SRC_DIR / "ai_asset_platform" / "__init__.py").resolve()

# `/tmp` is tmpfs (RAM-backed) on some dev hosts with little RAM and no swap;
# building a venv there competes with the running system for memory. Prefer a
# disk-backed temp root (`/var/tmp`) when one is available and writable, and
# fall back to the platform default (e.g. plain CI runners) otherwise.
_DISK_BACKED_TMP = (
    "/var/tmp" if os.path.isdir("/var/tmp") and os.access("/var/tmp", os.W_OK) else None
)

_WRAPPER_INVOCATION_RE = re.compile(r"python3?\s+(\S+\s+)*-m\s+ai_asset_platform\b")
_ACTIVATE_RE = re.compile(r"^\s*source \.venv/bin/activate\s*$")
_UNSET_PYTHONPATH_RE = re.compile(r"^\s*unset PYTHONPATH\s*$")

# `python -`/`python3 -` stdin heredoc invocation, e.g. `python - <<'PY'` or
# `python - "$ARG" <<'PY'`. Captures the heredoc delimiter so the body can be
# scanned for an ai_asset_platform import (Codex PR #287 P1, fifth review).
_STDIN_PYTHON_HEREDOC_RE = re.compile(r"^python3?\b.*<<\s*['\"]?(\w+)['\"]?\s*$")
_AI_ASSET_PLATFORM_IMPORT_RE = re.compile(r"^\s*(import ai_asset_platform\b|from ai_asset_platform\b)")


def _find_stdin_python_ai_asset_platform_invocation(lines):
    """Line index of a `python -`/`python3 -` heredoc whose body imports
    ai_asset_platform, or None. Distinct from `-m ai_asset_platform`
    invocations, which pytest.ini's collection-time path injection and
    `_WRAPPER_INVOCATION_RE` already cover.
    """
    for i, line in enumerate(lines):
        m = _STDIN_PYTHON_HEREDOC_RE.match(line.strip())
        if not m:
            continue
        delimiter = m.group(1)
        for body_line in lines[i + 1 :]:
            if body_line.strip() == delimiter:
                break
            if _AI_ASSET_PLATFORM_IMPORT_RE.match(body_line):
                return i
    return None


def _find_first_ai_asset_platform_invocation(lines):
    """Earliest line index where this wrapper invokes ai_asset_platform,
    across both known invocation forms (`-m ai_asset_platform...` and a
    `python -` stdin heredoc that imports it), or None if neither is
    present.
    """
    candidates = [
        idx
        for idx in (
            next((i for i, l in enumerate(lines) if _WRAPPER_INVOCATION_RE.search(l)), None),
            _find_stdin_python_ai_asset_platform_invocation(lines),
        )
        if idx is not None
    ]
    return min(candidates) if candidates else None

_INSTALLER_PATH = ROOT_DIR / "install_ibkr_readonly_autopilot.sh"
_VERIFY_SCRIPT_PATH = ROOT_DIR / "scripts" / "verify_exact_checkout_import.py"
_HELPER_PATH = ROOT_DIR / "scripts" / "ensure_exact_checkout_runtime.sh"
_PIP_EDITABLE_INSTALL_RE = re.compile(r"pip install\s+-e\s+\.\s*$")
_VERIFY_SCRIPT_CALL_RE = re.compile(r"verify_exact_checkout_import\.py")
# Requires the `bash` invocation prefix (not just the bare filename), so a
# comment that merely *mentions* the helper (e.g. "See
# scripts/ensure_exact_checkout_runtime.sh for detail") is never mistaken
# for the actual call -- found via ibkr_auto.sh's own explanatory comment
# (added in an earlier fix in this same PR) being picked as `helper_idx`
# ahead of the real call on the next line, silently defeating the
# control-flow check below (ChatGPT re-audit).
_HELPER_CALL_RE = re.compile(r"\bbash\s+scripts/ensure_exact_checkout_runtime\.sh\b")
_SYSTEMCTL_RESTART_RE = re.compile(r"systemctl --user restart")

_SOAK_PATH = ROOT_DIR / "ibkr_readonly_soak_once.sh"
_SOAK_FIRST_USE_RE = re.compile(r"python3?\s+(\S+\s+)*-m\s+pytest\b|^pytest\b|\bbash \./\S+\.sh\b")

# Self-update indicators: any command that can change this checkout's own
# tracked source before the wrapper keeps running.
_GIT_UPDATE_RE = re.compile(r"^(if\s+)?git\s+(pull|fetch)\b|^git\s+switch\b|^git\s+checkout\b")

# Bash `if ...; then` / `fi` nesting depth tracker, single-line-conditional
# only (matches this codebase's actual style -- verified against all
# discovered wrappers). `elif`/`else` don't change depth: they're
# alternatives within the same enclosing `if`, not new nesting.
_IF_OPEN_RE = re.compile(r"^if\b.*;\s*then\s*$")
_FI_RE = re.compile(r"^fi(?:\s*;.*)?$")


def _bash_conditional_depths(lines):
    """if/fi nesting depth *at* each line: how many enclosing conditional
    blocks a statement on that line is inside. Used to catch `unset
    PYTHONPATH` sitting inside an `if` block that a later, unconditional
    invocation can bypass (Codex PR #287 P1, fourth review).
    """
    depths = []
    depth = 0
    for raw in lines:
        stripped = raw.strip()
        if _FI_RE.match(stripped):
            depth = max(depth - 1, 0)
            depths.append(depth)
            continue
        depths.append(depth)
        if _IF_OPEN_RE.match(stripped):
            depth += 1
    return depths


def _discover_operational_wrappers():
    """Every *.sh script (repo root + scripts/) that invokes ai_asset_platform,
    via `-m ai_asset_platform...` or a `python -` stdin heredoc import.
    """
    candidates = sorted(ROOT_DIR.glob("*.sh")) + sorted((ROOT_DIR / "scripts").glob("*.sh"))
    wrappers = [
        path
        for path in candidates
        if _find_first_ai_asset_platform_invocation(
            path.read_text(encoding="utf-8").splitlines()
        )
        is not None
    ]
    return wrappers


def test_all_operational_wrappers_clear_inherited_pythonpath_before_first_use():
    """Static proof that every wrapper neutralizes inherited PYTHONPATH.

    Every wrapper must `unset PYTHONPATH` after `source .venv/bin/activate`
    and before its first `ai_asset_platform` invocation, so an inherited
    PYTHONPATH from the parent shell/service can never shadow the editable
    install. Textual presence between the two lines is not sufficient on its
    own -- `unset` must also not be reachable-but-skippable relative to the
    first invocation: it must sit at an `if`-nesting depth no deeper than
    that invocation, or a path exists (an un-migrated `.venv`, a false
    conditional) where `unset` is skipped but the invocation still runs.
    """
    wrappers = _discover_operational_wrappers()
    assert len(wrappers) >= 30, (
        f"expected at least 30 ai_asset_platform operational wrappers, found {len(wrappers)}: "
        f"{[w.name for w in wrappers]}"
    )

    failures = []
    for path in wrappers:
        lines = path.read_text(encoding="utf-8").splitlines()
        depths = _bash_conditional_depths(lines)
        activate_idx = next((i for i, l in enumerate(lines) if _ACTIVATE_RE.match(l)), None)
        first_use_idx = _find_first_ai_asset_platform_invocation(lines)
        if activate_idx is None or first_use_idx is None:
            failures.append(f"{path.name}: could not locate activate/first-use lines")
            continue
        if activate_idx >= first_use_idx:
            failures.append(
                f"{path.name}: venv activation (line {activate_idx + 1}) does not precede "
                f"first ai_asset_platform invocation (line {first_use_idx + 1})"
            )
            continue
        unset_idx = next(
            (
                i
                for i in range(activate_idx + 1, first_use_idx)
                if _UNSET_PYTHONPATH_RE.match(lines[i])
            ),
            None,
        )
        if unset_idx is None:
            failures.append(
                f"{path.name}: no 'unset PYTHONPATH' between venv activation "
                f"(line {activate_idx + 1}) and first ai_asset_platform invocation "
                f"(line {first_use_idx + 1})"
            )
            continue
        if depths[unset_idx] > depths[first_use_idx]:
            failures.append(
                f"{path.name}: 'unset PYTHONPATH' (line {unset_idx + 1}, if-depth "
                f"{depths[unset_idx]}) is nested inside a conditional that the first "
                f"ai_asset_platform invocation (line {first_use_idx + 1}, if-depth "
                f"{depths[first_use_idx]}) can still reach when that conditional is "
                "skipped -- inherited PYTHONPATH could leak through"
            )

    assert not failures, "wrappers vulnerable to inherited PYTHONPATH shadowing:\n" + "\n".join(
        failures
    )


def _site_packages_dir(venv_dir: Path) -> Path:
    return venv_dir / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"


@pytest.fixture(scope="module")
def src_path_venv():
    """A disposable, pip-free venv whose site-packages points at this checkout's src/.

    No `pip install`, no setuptools/wheel, no network, no dependency on
    `/usr/share/python-wheels`. A `.pth` file in site-packages is all that's
    needed to reproduce the sys.path property this file actually tests: that
    `ai_asset_platform` is reachable via a site-packages path entry, which
    inherited `PYTHONPATH` entries take priority over. This is *not* a claim
    that `pip install -e .` itself works offline -- that is verified by
    `.github/workflows/pytest.yml`'s own `pip install -e .` step plus its
    "Verify plain-python runtime import" step, independently of this file.
    """
    with tempfile.TemporaryDirectory(
        prefix="ai_asset_platform_pythonpath_regression_", dir=_DISK_BACKED_TMP
    ) as tmp:
        venv_dir = Path(tmp) / "venv"
        venv.EnvBuilder(with_pip=False).create(venv_dir)
        venv_python = venv_dir / "bin" / "python"
        assert venv_python.exists(), "venv creation did not produce a python executable"

        site_packages = _site_packages_dir(venv_dir)
        assert site_packages.is_dir(), f"expected venv site-packages at {site_packages}"
        (site_packages / "ai_asset_platform_checkout.pth").write_text(
            str(SRC_DIR) + "\n", encoding="utf-8"
        )

        yield venv_python


def test_wrapper_pattern_defeats_hostile_inherited_pythonpath(src_path_venv, tmp_path):
    """Dynamic proof, via the real wrapper invocation pattern, of the P1 fix.

    Simulates a parent shell/service that leaks a hostile PYTHONPATH into the
    wrapper's environment, then runs the exact sequence every operational
    wrapper now uses (`source .venv/bin/activate` -> `unset PYTHONPATH` ->
    plain `python`) and asserts resolution lands on this checkout, not the
    hostile path. Entirely offline: no pip, no network, no apt.
    """
    hostile_dir = tmp_path / "hostile_pythonpath"
    hostile_pkg = hostile_dir / "ai_asset_platform"
    hostile_pkg.mkdir(parents=True)
    hostile_init = hostile_pkg / "__init__.py"
    hostile_init.write_text("HOSTILE = True\n", encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(hostile_dir)

    import_snippet = (
        "import ai_asset_platform, os; "
        "print(os.path.realpath(ai_asset_platform.__file__))"
    )

    # Sanity check: without the fix, the hostile inherited PYTHONPATH really
    # does shadow the src/ path entry. This proves the test setup actually
    # reproduces the Codex finding rather than trivially passing.
    vulnerable = subprocess.run(
        [str(src_path_venv), "-c", import_snippet],
        cwd=tempfile.gettempdir(),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert vulnerable.returncode == 0, (
        f"hostile-PYTHONPATH sanity import failed:\n"
        f"stdout={vulnerable.stdout}\nstderr={vulnerable.stderr}"
    )
    assert Path(vulnerable.stdout.strip()).resolve() == hostile_init.resolve(), (
        "test setup did not reproduce the hostile-PYTHONPATH-shadowing precondition; "
        f"resolved to {vulnerable.stdout.strip()!r} instead of the hostile package"
    )

    # The actual fix: `source .venv/bin/activate` followed by
    # `unset PYTHONPATH`, exactly as every operational wrapper now does
    # before its first ai_asset_platform invocation.
    venv_dir = src_path_venv.parent.parent
    activate_script = venv_dir / "bin" / "activate"
    fixed = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{activate_script}" && unset PYTHONPATH && python -c "{import_snippet}"',
        ],
        cwd=tempfile.gettempdir(),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert fixed.returncode == 0, (
        f"wrapper-pattern invocation failed:\nstdout={fixed.stdout}\nstderr={fixed.stderr}"
    )
    resolved = Path(fixed.stdout.strip()).resolve()
    assert resolved == EXPECTED_INIT_FILE, (
        f"wrapper pattern (activate + unset PYTHONPATH) resolved to {resolved}, "
        f"expected {EXPECTED_INIT_FILE} (hostile inherited PYTHONPATH was not defeated)"
    )


def test_install_autopilot_migrates_and_verifies_before_restart():
    """Static proof that the installer migrates and verifies before restart.

    `install_ibkr_readonly_autopilot.sh` must, in order: activate `.venv`,
    clear inherited PYTHONPATH (so it can't shadow the migration/verification
    themselves), editable-install the current checkout into it (migrating
    any pre-existing `.venv`), run the fail-closed exact-checkout checker,
    and only then restart the systemd service. Under `set -euo pipefail`, a
    failed migration or verification aborts the script before the restart
    line is ever reached.
    """
    assert _INSTALLER_PATH.is_file(), f"missing {_INSTALLER_PATH}"
    lines = _INSTALLER_PATH.read_text(encoding="utf-8").splitlines()

    activate_idx = next((i for i, l in enumerate(lines) if _ACTIVATE_RE.match(l)), None)
    unset_idx = next((i for i, l in enumerate(lines) if _UNSET_PYTHONPATH_RE.match(l)), None)
    pip_idx = next(
        (i for i, l in enumerate(lines) if _PIP_EDITABLE_INSTALL_RE.search(l)), None
    )
    verify_idx = next(
        (i for i, l in enumerate(lines) if _VERIFY_SCRIPT_CALL_RE.search(l)), None
    )
    restart_idx = next(
        (i for i, l in enumerate(lines) if _SYSTEMCTL_RESTART_RE.search(l)), None
    )

    assert activate_idx is not None, "installer must source .venv/bin/activate"
    assert unset_idx is not None, "installer must unset inherited PYTHONPATH"
    assert pip_idx is not None, "installer must editable-install into the existing .venv"
    assert verify_idx is not None, "installer must run the exact-checkout fail-closed verifier"
    assert restart_idx is not None, "installer must restart the systemd service"

    assert activate_idx < unset_idx < pip_idx < verify_idx < restart_idx, (
        "installer must activate -> unset PYTHONPATH -> editable-install -> "
        "fail-closed verify -> restart, in that order; got "
        f"activate={activate_idx} unset={unset_idx} pip={pip_idx} "
        f"verify={verify_idx} restart={restart_idx}"
    )


def test_ibkr_readonly_soak_clears_pythonpath_before_first_use():
    """`ibkr_readonly_soak_once.sh` never invokes ai_asset_platform directly
    (it runs `python -m pytest`, then delegates to `bash ./ibkr_auto.sh`), so
    `_discover_operational_wrappers()` cannot see it. Covered separately:
    must `unset PYTHONPATH` right after `source .venv/bin/activate`, before
    its first pytest/python/delegated-wrapper invocation.
    """
    assert _SOAK_PATH.is_file(), f"missing {_SOAK_PATH}"
    lines = _SOAK_PATH.read_text(encoding="utf-8").splitlines()

    activate_idx = next((i for i, l in enumerate(lines) if _ACTIVATE_RE.match(l)), None)
    first_use_idx = next(
        (i for i, l in enumerate(lines) if _SOAK_FIRST_USE_RE.search(l)), None
    )
    assert activate_idx is not None, "ibkr_readonly_soak_once.sh must source .venv/bin/activate"
    assert first_use_idx is not None, (
        "ibkr_readonly_soak_once.sh must have a pytest/python/delegated-wrapper invocation"
    )
    assert activate_idx < first_use_idx, (
        f"venv activation (line {activate_idx + 1}) does not precede first "
        f"pytest/python/bash invocation (line {first_use_idx + 1})"
    )

    unset_idx = next(
        (
            i
            for i in range(activate_idx + 1, first_use_idx)
            if _UNSET_PYTHONPATH_RE.match(lines[i])
        ),
        None,
    )
    assert unset_idx is not None, (
        "ibkr_readonly_soak_once.sh: no 'unset PYTHONPATH' between venv activation "
        f"(line {activate_idx + 1}) and first pytest/python/bash invocation "
        f"(line {first_use_idx + 1})"
    )


def test_verify_exact_checkout_import_script_is_fail_closed(src_path_venv, tmp_path):
    """The shared checker only passes for *this* checkout, and fails closed
    when a hostile/stale PYTHONPATH shadows it -- exactly what an
    un-migrated existing .venv (or a leaked parent-process PYTHONPATH) would
    do to `install_ibkr_readonly_autopilot.sh`'s new verification step.
    Entirely offline: no pip, no network, no broker/TWS/order APIs.
    """
    assert _VERIFY_SCRIPT_PATH.is_file(), f"missing {_VERIFY_SCRIPT_PATH}"

    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    correct = subprocess.run(
        [str(src_path_venv), str(_VERIFY_SCRIPT_PATH)],
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert correct.returncode == 0, (
        f"checker must pass for this checkout with PYTHONPATH unset:\n"
        f"stdout={correct.stdout}\nstderr={correct.stderr}"
    )
    assert "OK:" in correct.stdout

    hostile_dir = tmp_path / "hostile_pythonpath_for_checker"
    hostile_pkg = hostile_dir / "ai_asset_platform"
    hostile_pkg.mkdir(parents=True)
    hostile_pkg_init = hostile_pkg / "__init__.py"
    hostile_pkg_init.write_text("HOSTILE = True\n", encoding="utf-8")

    hostile_env = dict(os.environ)
    hostile_env["PYTHONPATH"] = str(hostile_dir)
    shadowed = subprocess.run(
        [str(src_path_venv), str(_VERIFY_SCRIPT_PATH)],
        cwd=ROOT_DIR,
        env=hostile_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert shadowed.returncode != 0, (
        "checker must fail closed when a hostile PYTHONPATH shadows ai_asset_platform, "
        f"got returncode 0:\nstdout={shadowed.stdout}\nstderr={shadowed.stderr}"
    )
    assert "FATAL" in shadowed.stderr
    assert "OK:" not in shadowed.stdout


def test_stdin_heredoc_wrapper_is_discovered_and_checked():
    """`ibkr_future_whatif_once.sh` imports ai_asset_platform from inside a
    `python - <<'PY'` heredoc body, not via `-m`. Prove the detector actually
    finds it (not just wrappers using `-m`), that it is included in
    `_discover_operational_wrappers()`, and that the detected invocation
    line is the `python -` launch line itself -- not a coincidental match
    somewhere else -- so the activate < unset < stdin-python-use ordering
    check in `test_all_operational_wrappers_clear_inherited_pythonpath_before_first_use`
    is actually exercised for this file.
    """
    stdin_wrapper_path = ROOT_DIR / "ibkr_future_whatif_once.sh"
    assert stdin_wrapper_path.is_file(), f"missing {stdin_wrapper_path}"

    lines = stdin_wrapper_path.read_text(encoding="utf-8").splitlines()

    # Sanity: this file has no `-m ai_asset_platform` invocation at all, so a
    # detector limited to that pattern would find nothing here.
    assert not any(_WRAPPER_INVOCATION_RE.search(l) for l in lines), (
        f"{stdin_wrapper_path.name} unexpectedly contains a '-m ai_asset_platform' "
        "invocation; this test assumes it is stdin-heredoc-only"
    )

    first_use_idx = _find_first_ai_asset_platform_invocation(lines)
    assert first_use_idx is not None, (
        f"stdin-heredoc detector failed to find the ai_asset_platform import in "
        f"{stdin_wrapper_path.name}"
    )
    assert lines[first_use_idx].strip().startswith("python"), (
        f"detected invocation line {first_use_idx + 1} is not the 'python -' "
        f"heredoc launch line: {lines[first_use_idx]!r}"
    )
    assert "<<" in lines[first_use_idx], (
        f"detected invocation line {first_use_idx + 1} is not a stdin heredoc "
        f"launch: {lines[first_use_idx]!r}"
    )

    wrappers = _discover_operational_wrappers()
    assert stdin_wrapper_path in wrappers, (
        f"{stdin_wrapper_path.name} must be included in "
        "_discover_operational_wrappers() via the stdin-heredoc detection path"
    )

    activate_idx = next((i for i, l in enumerate(lines) if _ACTIVATE_RE.match(l)), None)
    assert activate_idx is not None, f"{stdin_wrapper_path.name} must source .venv/bin/activate"
    unset_idx = next(
        (
            i
            for i in range(activate_idx + 1, first_use_idx)
            if _UNSET_PYTHONPATH_RE.match(lines[i])
        ),
        None,
    )
    assert unset_idx is not None, (
        f"{stdin_wrapper_path.name}: no 'unset PYTHONPATH' between venv activation "
        f"(line {activate_idx + 1}) and the stdin-python first use "
        f"(line {first_use_idx + 1})"
    )
    assert activate_idx < unset_idx < first_use_idx, (
        "expected activate < unset PYTHONPATH < stdin-python first use; got "
        f"activate={activate_idx} unset={unset_idx} first_use={first_use_idx}"
    )


_IBKR_AUTO_PATH = ROOT_DIR / "ibkr_auto.sh"
_GIT_PULL_RE = re.compile(r"git pull --ff-only origin main")
_STRICT_MODE_RE = re.compile(r"^set -euo pipefail\s*$")


def test_ibkr_auto_migrates_venv_after_pull_before_first_use():
    """`ibkr_auto.sh` self-updates via `git pull`, independently of
    `install_ibkr_readonly_autopilot.sh`'s own migration/verification (which
    only runs when the installer itself is re-run). An older `.venv`
    (created before editable install was required) could then pull a newer
    checkout and, once PYTHONPATH is correctly unset, hit
    ModuleNotFoundError or resolve ai_asset_platform to a stale/wrong
    checkout. Must, in order: `set -euo pipefail` -> git pull -> activate ->
    unset PYTHONPATH -> the shared runtime-binding helper (verify-first,
    migrate-only-on-failure) -> only then the first ai_asset_platform
    invocation. `set -euo pipefail` being active before the pull means a
    failed migration/verification later aborts the rest of the cycle before
    any ai_asset_platform module runs. `ibkr_auto.sh` must NOT call `pip` or
    the verifier directly -- it must go through the one shared helper, so a
    verify-first (no-network-when-already-correct) design applies here too,
    preserving this script's "keep monitoring even when origin is
    unreachable" contract.
    """
    assert _IBKR_AUTO_PATH.is_file(), f"missing {_IBKR_AUTO_PATH}"
    lines = _IBKR_AUTO_PATH.read_text(encoding="utf-8").splitlines()

    strict_mode_idx = next((i for i, l in enumerate(lines) if _STRICT_MODE_RE.match(l)), None)
    pull_idx = next((i for i, l in enumerate(lines) if _GIT_PULL_RE.search(l)), None)
    activate_idx = next((i for i, l in enumerate(lines) if _ACTIVATE_RE.match(l)), None)
    unset_idx = next((i for i, l in enumerate(lines) if _UNSET_PYTHONPATH_RE.match(l)), None)
    helper_idx = next((i for i, l in enumerate(lines) if _HELPER_CALL_RE.search(l)), None)
    first_use_idx = _find_first_ai_asset_platform_invocation(lines)

    assert strict_mode_idx is not None, "ibkr_auto.sh must have 'set -euo pipefail'"
    assert pull_idx is not None, "ibkr_auto.sh must git pull --ff-only origin main"
    assert activate_idx is not None, "ibkr_auto.sh must source .venv/bin/activate"
    assert unset_idx is not None, "ibkr_auto.sh must unset inherited PYTHONPATH"
    assert helper_idx is not None, (
        "ibkr_auto.sh must call the shared runtime-binding helper "
        "(scripts/ensure_exact_checkout_runtime.sh) before using ai_asset_platform"
    )
    assert first_use_idx is not None, "ibkr_auto.sh must invoke ai_asset_platform"

    assert strict_mode_idx < pull_idx < activate_idx < unset_idx < helper_idx < first_use_idx, (
        "ibkr_auto.sh must run: set -euo pipefail -> git pull -> activate -> "
        "unset PYTHONPATH -> runtime-binding helper -> first ai_asset_platform "
        f"use, in that order; got strict_mode={strict_mode_idx} pull={pull_idx} "
        f"activate={activate_idx} unset={unset_idx} helper={helper_idx} "
        f"first_use={first_use_idx}"
    )

    # ibkr_auto.sh must not duplicate the migration/verification logic
    # itself; it must go through the one shared helper/verifier.
    assert not any(_PIP_EDITABLE_INSTALL_RE.search(l) for l in lines), (
        "ibkr_auto.sh must not call 'pip install -e .' directly -- it must go "
        "through scripts/ensure_exact_checkout_runtime.sh, so the common case "
        "(already-correct .venv) never touches pip/network"
    )
    assert not any(_VERIFY_SCRIPT_CALL_RE.search(l) for l in lines), (
        "ibkr_auto.sh must not call verify_exact_checkout_import.py directly -- "
        "it must go through the shared helper"
    )

    # Reuses the one shared checker/helper (also usable by scripts/setup.sh
    # and install_ibkr_readonly_autopilot.sh) -- no duplicate verifier.
    assert _VERIFY_SCRIPT_PATH.is_file(), f"missing {_VERIFY_SCRIPT_PATH}"
    assert _HELPER_PATH.is_file(), f"missing {_HELPER_PATH}"


def _discover_self_updating_wrappers():
    """Every *.sh script (repo root + scripts/) whose own execution can
    change its checkout's tracked source (git pull/fetch/switch/checkout),
    mechanically -- not a hard-coded filename list, so a future
    self-updating wrapper is automatically covered.
    """
    candidates = sorted(ROOT_DIR.glob("*.sh")) + sorted((ROOT_DIR / "scripts").glob("*.sh"))
    return [
        path
        for path in candidates
        if any(_GIT_UPDATE_RE.match(l.strip()) for l in path.read_text(encoding="utf-8").splitlines())
    ]


# Short combined `set` flags only (e.g. `set -euo pipefail`, `set +e`) --
# verified this codebase never uses the long `set -o`/`set +o` form.
_SET_FLAGS_RE = re.compile(r"^set\s+([+-])([A-Za-z]+)\b")
# Only a literal `exit` statement counts as proof a branch terminates the
# script (ChatGPT re-audit): `return` outside a function does not exit a
# top-level wrapper script, and bare/redirection-only `exec` (e.g.
# `exec >log.txt`) does not replace the process or exit either -- both
# would let control fall through to later code just like no statement at
# all. Neither is used as an exit mechanism anywhere in this repo's
# wrappers, so excluding them costs nothing real and removes two
# false-SAFE vectors.
_EXIT_STATEMENT_RE = re.compile(r"^exit\b")

# `helper || exit [status]` matched as the *entire* line, not merely
# "`||` appears somewhere before the word exit" (ChatGPT re-audit): a
# loose substring/word-boundary search treats `|| echo "please exit 2"`,
# `|| true  # exit 2`, and `|| printf 'exit 2\n'` as if they exited, when
# none of them do. A brace-group form (`helper || { ...; exit N; }`) is
# deliberately NOT recognized as safe here either -- not used by any real
# wrapper, and parsing it correctly (multiple statements, nested quoting)
# is more than this line-based check can prove; treated as unverified.
_HELPER_OR_EXIT_RE = re.compile(
    r"^bash\s+scripts/ensure_exact_checkout_runtime\.sh\s*\|\|\s*exit(?:\s+\d+)?\s*$"
)


def _errexit_active_before(lines, idx):
    """Whether bash `errexit` (`set -e`, or `e` in a combined flag string
    like `set -euo pipefail`) is active immediately before `lines[idx]`, by
    scanning `set` toggles from the top of the file in order. `set +e`
    (or `+` with `e` in the flags) turns it back off.
    """
    active = False
    for l in lines[:idx]:
        m = _SET_FLAGS_RE.match(l.strip())
        if not m:
            continue
        sign, flags = m.groups()
        if "e" in flags:
            active = sign == "-"
    return active


def _block_end_index(lines, if_idx, depths):
    """Index of the `fi` line that closes the if-block opened at
    `lines[if_idx]` (which must match `_IF_OPEN_RE`), found via `if`/`fi`
    depth tracking. None if no matching `fi` is found.
    """
    target_depth = depths[if_idx]
    for i in range(if_idx + 1, len(lines)):
        if _FI_RE.match(lines[i].strip()) and depths[i] == target_depth:
            return i
    return None


def _block_has_unconditional_exit(lines, depths, start, end, body_depth):
    """Whether lines[start:end] contains an `exit`/`return`/`exec` at
    exactly `body_depth` -- i.e. not itself buried in a further nested
    conditional that could skip it.
    """
    return any(
        depths[i] == body_depth and _EXIT_STATEMENT_RE.match(lines[i].strip())
        for i in range(start, end)
    )


_ELIF_OR_ELSE_RE = re.compile(r"^elif\b|^else\s*$")


def _then_branch_end_index(lines, depths, if_idx, block_end, body_depth):
    """Exclusive end index of the `then` branch specifically -- the first
    `elif`/`else` at `body_depth` between `if_idx` and `block_end`, or
    `block_end` itself if there is none. `elif`/`else` don't change depth
    in `_bash_conditional_depths` (they're siblings of `then`, not nested
    inside it), so they -- and anything inside them -- are recorded at the
    same `body_depth` as the `then` branch's own content and must be
    excluded explicitly, not just by depth (ChatGPT re-audit: an `exit` in
    an `else` branch was being read as proof the `then`/failure branch
    exits too, which it does not).
    """
    for i in range(if_idx + 1, block_end):
        if depths[i] == body_depth and _ELIF_OR_ELSE_RE.match(lines[i].strip()):
            return i
    return block_end


def _classify_helper_call_control_flow(lines, depths, helper_idx, errexit_active):
    """Whether a non-zero exit from the runtime-binding helper call at
    `lines[helper_idx]` necessarily terminates this script's control flow
    before it can reach any later ai_asset_platform invocation (Codex
    PR #287 P1, `ibkr_all_readonly_completion_once.sh` review, and its
    follow-up: the helper call being the *condition* of an `if` is not, by
    itself, proof of anything -- `if helper; then ...; fi` and
    `if ! helper; then echo; fi` both let a failure fall straight through).

    Returns True (verified safe), False (verified unsafe), or None (cannot
    be statically verified here) -- callers must treat None the same as
    False, never assume safety when it can't be shown.
    """
    line = lines[helper_idx].strip()

    # `helper || exit N`, matched as the entire line: on failure, `exit`
    # runs unconditionally. Anything else after `||` (a brace group, any
    # other command) is not recognized here -- see `_HELPER_OR_EXIT_RE`.
    if _HELPER_OR_EXIT_RE.match(line):
        return True

    # `if [!] <...helper...>; then` -- the helper call is itself the
    # if-condition.
    if re.match(r"^if\b", line):
        negated = bool(re.match(r"^if\s*!\s*", line))
        if not negated:
            # Failure -> the `then` body is skipped, and execution falls
            # straight through past `fi` regardless of what the `then`
            # body (or any else/elif) contains. Not verified safe by this
            # analysis -- treated conservatively as unsafe rather than
            # trying to reason about else/elif chains.
            return False
        block_end = _block_end_index(lines, helper_idx, depths)
        if block_end is None:
            return None
        body_depth = depths[helper_idx] + 1
        # Only the `then` branch runs on failure (this is `if !`); an
        # `exit` in `else`/`elif` never executes then and is not evidence
        # of anything.
        then_end = _then_branch_end_index(lines, depths, helper_idx, block_end, body_depth)
        return _block_has_unconditional_exit(lines, depths, helper_idx + 1, then_end, body_depth)

    # A bare statement: the entire line is just the helper invocation,
    # nothing else -- errexit is what would stop the script here. (Note
    # this is *not* checked for the `if`/`||` cases above: a command's
    # exit status used as an if/while condition, or as part of `||`/`&&`,
    # is exempt from triggering errexit regardless of whether it's active.)
    if line == "bash scripts/ensure_exact_checkout_runtime.sh":
        return errexit_active

    # Anything else (part of a pipeline, a while/until condition, a case
    # statement, `&&`, a multi-line continuation, ...) is not statically
    # verified here -- never assumed safe.
    return None


def _helper_failure_is_fail_closed(lines, depths, helper_idx):
    errexit_active = _errexit_active_before(lines, helper_idx)
    return bool(
        _classify_helper_call_control_flow(lines, depths, helper_idx, errexit_active)
    )


def _check_exact_checkout_binding(name, lines):
    """Verify one wrapper's own lines correctly bind the exact checkout
    before its own first ai_asset_platform use. Returns a list of failure
    strings (empty if safe).

    Three things must all hold:
    - if this file performs any self-update (git pull/fetch/switch/checkout)
      before its first ai_asset_platform use, the *last* such update must
      precede venv activation -- not just the first one. A second update
      inserted after activation/the helper (e.g. a future edit adding
      another `git pull` later in the file) would re-change the checkout
      after binding was verified, invalidating it; using the first match
      would miss that (Codex/ChatGPT re-audit, PR #287 Stage1).
    - activate < unset PYTHONPATH < the runtime-binding helper < first use,
      with the helper not hidden behind a deeper `if`/`fi` conditional than
      the invocation it's meant to gate.
    - a non-zero exit from the helper call must actually stop the script
      before first use (`_helper_failure_is_fail_closed`) -- textual
      ordering alone is not enough: `ibkr_all_readonly_completion_once.sh`
      had the helper correctly *positioned* before every audit step, but
      ran under `set -uo pipefail` (no `-e`) with a bare, unchecked call,
      so a failed binding would not have stopped the script at all.

    A file with no self-update at all (last_update_idx is None) is not
    required to have one here -- this function also serves as the
    per-node check for delegate-chain verification, where a delegate
    target may correctly rely on its caller's earlier update.
    """
    first_use_idx = _find_first_ai_asset_platform_invocation(lines)
    if first_use_idx is None:
        return [f"{name}: has no direct ai_asset_platform invocation to check"]

    depths = _bash_conditional_depths(lines)
    update_indices_before_first_use = [
        i for i, l in enumerate(lines) if _GIT_UPDATE_RE.match(l.strip()) and i < first_use_idx
    ]
    last_update_idx = max(update_indices_before_first_use) if update_indices_before_first_use else None
    activate_idx = next((i for i, l in enumerate(lines) if _ACTIVATE_RE.match(l)), None)
    unset_idx = next((i for i, l in enumerate(lines) if _UNSET_PYTHONPATH_RE.match(l)), None)
    helper_idx = next((i for i, l in enumerate(lines) if _HELPER_CALL_RE.search(l)), None)

    missing = [
        n
        for n, idx in (
            ("activate", activate_idx),
            ("unset PYTHONPATH", unset_idx),
            ("runtime-binding helper", helper_idx),
        )
        if idx is None
    ]
    if missing:
        return [f"{name}: missing {', '.join(missing)}"]

    if last_update_idx is not None and not (last_update_idx < activate_idx):
        return [
            f"{name}: a self-update (line {last_update_idx + 1}) occurs at or after "
            f"venv activation (line {activate_idx + 1}); the exact-checkout binding "
            "that follows could already be stale by the time ai_asset_platform is used"
        ]

    if not (activate_idx < unset_idx < helper_idx < first_use_idx):
        return [
            f"{name}: expected activate < unset < helper < first_use; got "
            f"activate={activate_idx} unset={unset_idx} helper={helper_idx} "
            f"first_use={first_use_idx}"
        ]

    if depths[helper_idx] > depths[first_use_idx]:
        return [
            f"{name}: runtime-binding helper (line {helper_idx + 1}, if-depth "
            f"{depths[helper_idx]}) is nested inside a conditional that the first "
            f"ai_asset_platform invocation (line {first_use_idx + 1}, if-depth "
            f"{depths[first_use_idx]}) can still reach when that conditional is skipped"
        ]

    if not _helper_failure_is_fail_closed(lines, depths, helper_idx):
        return [
            f"{name}: a failed runtime-binding helper (line {helper_idx + 1}) would "
            "not stop this script before ai_asset_platform is used -- no active "
            "'set -e' at that point and the call is not itself checked (e.g. "
            "'if ! bash scripts/ensure_exact_checkout_runtime.sh; then ... exit ...; fi')"
        ]

    return []


# Delegate detection: `bash ./xxx.sh`, `bash path/to/xxx.sh`, `bash
# "$DYNAMIC/target.sh"`, optionally preceded by env-var assignments on the
# same line (those aren't captured). Deliberately broad (any non-whitespace
# run ending in `.sh`) so a dynamically-built target is still *captured*
# here and can be explicitly rejected as unresolvable in
# `_resolve_delegate_path`, rather than silently not matching at all.
_DELEGATE_RE = re.compile(r"\bbash\s+(\S+\.sh)\b")


def _find_delegate_targets(lines):
    """Repo-relative delegate script paths this wrapper invokes via `bash`."""
    targets = []
    for l in lines:
        targets.extend(m.group(1) for m in _DELEGATE_RE.finditer(l))
    return targets


def _resolve_delegate_path(raw, root):
    """Resolve a delegate target string to a file under `root`, or None if
    it can't be statically resolved (a shell-variable-built path, or one
    that escapes `root`, or one that doesn't exist) -- callers must treat
    an unresolved target as unverified/unsafe, never assume it's SAFE.
    """
    if "$" in raw:
        return None
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def _verify_delegate_chain(path, root, visiting=None):
    """Recursively verify that `path` -- and, if it has no direct
    ai_asset_platform use, everything it delegates to via `bash` -- ends up
    exact-checkout-bound before ai_asset_platform is ever used. Returns a
    list of failure strings (empty if safe). A delegate cycle is a failure,
    not an infinite loop. An unresolved delegate target is a failure, not
    an assumed-safe skip.
    """
    visiting = list(visiting) if visiting else []
    if path in visiting:
        cycle = " -> ".join(p.name for p in visiting + [path])
        return [f"delegate cycle detected: {cycle}"]
    visiting = visiting + [path]

    lines = path.read_text(encoding="utf-8").splitlines()
    if _find_first_ai_asset_platform_invocation(lines) is not None:
        return _check_exact_checkout_binding(path.name, lines)

    delegates = _find_delegate_targets(lines)
    if not delegates:
        return [
            f"{path.name}: no direct ai_asset_platform use and no delegate target "
            "found -- cannot verify exact-checkout binding"
        ]

    failures = []
    for raw in delegates:
        resolved = _resolve_delegate_path(raw, root)
        if resolved is None:
            failures.append(
                f"{path.name}: delegate target {raw!r} could not be statically "
                "resolved to a repo script (dynamic path or outside repo) -- "
                "treating as unverified/unsafe rather than assuming it is gated"
            )
            continue
        failures.extend(_verify_delegate_chain(resolved, root, visiting))
    return failures


def test_all_self_updating_wrappers_bind_exact_checkout_before_first_use():
    """Cross-cutting proof for every self-updating wrapper (P1-A), not just
    `ibkr_auto.sh`: a self-update (git pull/fetch/switch/checkout) can bring
    in a newer checkout than an older, never-migrated `.venv` has installed.
    Every such wrapper that directly uses `ai_asset_platform` must bind the
    exact checkout (see `_check_exact_checkout_binding`) before that use.

    Wrappers that self-update but never call `ai_asset_platform` directly
    (e.g. `ibkr_readonly_soak_once.sh`, which only runs `pytest` and
    delegates to `bash ./ibkr_auto.sh`) are verified via
    `_verify_delegate_chain` instead of being skipped -- the delegate chain
    must itself resolve to a gated wrapper, recursively, with cycles and
    unresolved (dynamic/external) targets treated as failures.
    """
    wrappers = _discover_self_updating_wrappers()
    assert len(wrappers) >= 25, (
        f"expected at least 25 self-updating wrappers, found {len(wrappers)}: "
        f"{[w.name for w in wrappers]}"
    )

    failures = []
    direct_use_checked = 0
    delegate_checked = 0
    for path in wrappers:
        lines = path.read_text(encoding="utf-8").splitlines()
        if _find_first_ai_asset_platform_invocation(lines) is not None:
            direct_use_checked += 1
            failures.extend(_check_exact_checkout_binding(path.name, lines))
        else:
            delegate_checked += 1
            failures.extend(_verify_delegate_chain(path, ROOT_DIR))

    assert direct_use_checked >= 25, (
        "expected at least 25 self-updating wrappers with a direct ai_asset_platform "
        f"use, found {direct_use_checked}"
    )
    assert delegate_checked >= 1, (
        "expected at least one delegate-only self-updating wrapper (e.g. "
        f"ibkr_readonly_soak_once.sh) to exercise delegate-chain verification, found {delegate_checked}"
    )
    assert not failures, (
        "self-updating wrappers not exact-checkout-bound before first use:\n"
        + "\n".join(failures)
    )


def _write_fake_python(bin_dir: Path) -> None:
    """A `python` stand-in used only to test scripts/ensure_exact_checkout_runtime.sh
    in isolation: no real venv, no real pip, no network. Behavior is driven
    entirely by env vars the test sets, and every call is logged so tests
    can assert whether pip was ever invoked.
    """
    fake = bin_dir / "python"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys, pathlib\n"
        'state_dir = pathlib.Path(os.environ["FAKE_PYTHON_STATE_DIR"])\n'
        'with (state_dir / "calls.log").open("a") as f:\n'
        '    f.write(repr(sys.argv[1:]) + "\\n")\n'
        "argv = sys.argv[1:]\n"
        'if argv and argv[0] == "scripts/verify_exact_checkout_import.py":\n'
        '    count_file = state_dir / "verify_count"\n'
        "    n = int(count_file.read_text()) if count_file.exists() else 0\n"
        "    n += 1\n"
        "    count_file.write_text(str(n))\n"
        '    code = int(os.environ.get(f"FAKE_VERIFY_EXIT_{n}", os.environ.get("FAKE_VERIFY_EXIT_DEFAULT", "0")))\n'
        '    print(f"FAKE VERIFY call #{n} exit={code}")\n'
        "    sys.exit(code)\n"
        'if "pip" in argv and "install" in argv:\n'
        '    (state_dir / "pip_called").write_text("1")\n'
        '    code = int(os.environ.get("FAKE_PIP_EXIT", "0"))\n'
        '    print(f"FAKE PIP install exit={code}")\n'
        "    sys.exit(code)\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)


def _run_helper_with_fake_python(tmp_path, env_overrides):
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    _write_fake_python(bin_dir)
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FAKE_PYTHON_STATE_DIR"] = str(state_dir)
    env.pop("PYTHONPATH", None)
    env.update(env_overrides)

    result = subprocess.run(
        ["bash", str(_HELPER_PATH)],
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    pip_called = (state_dir / "pip_called").exists()
    return result, pip_called


def test_ensure_exact_checkout_runtime_passes_without_pip_when_already_correct(tmp_path):
    """Helper scenario 1: first verify PASSes -> no migration, no pip call."""
    result, pip_called = _run_helper_with_fake_python(tmp_path, {"FAKE_VERIFY_EXIT_1": "0"})
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert not pip_called, "helper must not call pip when the first verify already passes"


def test_ensure_exact_checkout_runtime_migrates_then_succeeds(tmp_path):
    """Helper scenario 2: first verify FAILs -> migration succeeds -> re-verify PASSes."""
    result, pip_called = _run_helper_with_fake_python(
        tmp_path,
        {"FAKE_VERIFY_EXIT_1": "1", "FAKE_PIP_EXIT": "0", "FAKE_VERIFY_EXIT_2": "0"},
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert pip_called, "helper must migrate when the first verify fails"


def test_ensure_exact_checkout_runtime_fails_closed_when_migration_fails(tmp_path):
    """Helper scenario 3: first verify FAILs -> migration itself fails -> fail closed."""
    result, pip_called = _run_helper_with_fake_python(
        tmp_path, {"FAKE_VERIFY_EXIT_1": "1", "FAKE_PIP_EXIT": "1"}
    )
    assert result.returncode != 0, "helper must fail closed when migration fails"
    assert pip_called


def test_ensure_exact_checkout_runtime_fails_closed_when_reverify_fails(tmp_path):
    """Helper scenario 4: migration succeeds but re-verify still FAILs -> fail closed."""
    result, pip_called = _run_helper_with_fake_python(
        tmp_path,
        {"FAKE_VERIFY_EXIT_1": "1", "FAKE_PIP_EXIT": "0", "FAKE_VERIFY_EXIT_2": "1"},
    )
    assert result.returncode != 0, (
        "helper must fail closed when ai_asset_platform still does not resolve "
        "correctly after a successful migration"
    )
    assert pip_called


def test_ensure_exact_checkout_runtime_real_verifier_already_correct_skips_pip_offline(
    src_path_venv,
):
    """Helper scenario 6, with the *real* verifier (not faked): a venv that
    already resolves ai_asset_platform to this checkout (via the offline
    `.pth` fixture, no pip installed at all -- `with_pip=False`) must pass
    without ever invoking pip. `PIP_NO_INDEX=1` simulates an explicit
    offline policy; since this venv cannot run pip at all, any success here
    mathematically proves pip was never invoked.
    """
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PATH"] = f"{src_path_venv.parent}:{env['PATH']}"
    env["PIP_NO_INDEX"] = "1"

    result = subprocess.run(
        ["bash", str(_HELPER_PATH)],
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "OK:" in result.stdout


def test_ensure_exact_checkout_runtime_hostile_pythonpath_fails_closed_not_silently(
    src_path_venv, tmp_path
):
    """Helper scenario 5, with the *real* verifier: if a caller forgot to
    `unset PYTHONPATH` (or it leaked back in), a hostile inherited
    PYTHONPATH makes the first verify see the wrong package and fail. The
    helper then tries to migrate; in this pip-free venv (`with_pip=False`)
    that migration itself fails, so the helper fails closed -- it never
    treats the hostile package as a valid resolution.
    """
    hostile_dir = tmp_path / "hostile_pythonpath_for_helper"
    hostile_pkg = hostile_dir / "ai_asset_platform"
    hostile_pkg.mkdir(parents=True)
    (hostile_pkg / "__init__.py").write_text("HOSTILE = True\n", encoding="utf-8")

    env = dict(os.environ)
    env["PATH"] = f"{src_path_venv.parent}:{env['PATH']}"
    env["PYTHONPATH"] = str(hostile_dir)

    result = subprocess.run(
        ["bash", str(_HELPER_PATH)],
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0, (
        "helper must fail closed rather than accept a hostile-PYTHONPATH-shadowed "
        f"resolution:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "OK:" not in result.stdout


def test_synthetic_update_after_helper_is_flagged():
    """Regression proof for the discovery-logic fix: a self-update placed
    *after* the runtime-binding helper (a future edit could introduce
    this, e.g. a second `git pull` added later in a file) must be caught.
    Using the *first* self-update line (the old logic) would have missed
    this, since that first update still precedes activate/unset/helper --
    only the *last* update before first-use matters, and it must still
    precede activation.
    """
    content = (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "git switch main\n"
        "source .venv/bin/activate\n"
        "unset PYTHONPATH\n"
        "bash scripts/ensure_exact_checkout_runtime.sh\n"
        "git pull --ff-only origin main\n"  # update AFTER the helper
        "python -m ai_asset_platform.brokers.something\n"
    )
    lines = content.splitlines()

    # Sanity: the *first*-match logic this replaces would have missed it.
    first_update_idx = next((i for i, l in enumerate(lines) if _GIT_UPDATE_RE.match(l.strip())), None)
    activate_idx = next((i for i, l in enumerate(lines) if _ACTIVATE_RE.match(l)), None)
    assert first_update_idx is not None and first_update_idx < activate_idx, (
        "test setup did not reproduce the first-update-still-precedes-activate "
        "precondition that made the old (first-match) logic blind to this case"
    )

    failures = _check_exact_checkout_binding("synthetic_wrapper.sh", lines)
    assert failures, "expected a failure: a self-update occurs after the runtime-binding helper"
    assert any("self-update" in f for f in failures), failures


def test_delegate_chain_safe_target_passes(tmp_path):
    """A delegate-only wrapper whose delegate target is itself fully gated
    (self-update -> activate -> unset -> helper -> first use) must pass.
    """
    target = tmp_path / "gated_target.sh"
    target.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "git pull --ff-only origin main\n"
        "source .venv/bin/activate\n"
        "unset PYTHONPATH\n"
        "bash scripts/ensure_exact_checkout_runtime.sh\n"
        "python -m ai_asset_platform.brokers.something\n",
        encoding="utf-8",
    )
    delegator = tmp_path / "delegator.sh"
    delegator.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "git pull --ff-only origin main\n"
        f"bash {target.name}\n",
        encoding="utf-8",
    )

    failures = _verify_delegate_chain(delegator, tmp_path)
    assert not failures, failures


def test_delegate_chain_ungated_target_fails(tmp_path):
    """A delegate-only wrapper whose delegate target directly uses
    ai_asset_platform but never calls the runtime-binding helper must fail
    -- delegation must not be a way to silently bypass the gate.
    """
    target = tmp_path / "ungated_target.sh"
    target.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "git pull --ff-only origin main\n"
        "source .venv/bin/activate\n"
        "unset PYTHONPATH\n"
        "python -m ai_asset_platform.brokers.something\n",  # no helper call
        encoding="utf-8",
    )
    delegator = tmp_path / "delegator.sh"
    delegator.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "git pull --ff-only origin main\n"
        f"bash {target.name}\n",
        encoding="utf-8",
    )

    failures = _verify_delegate_chain(delegator, tmp_path)
    assert failures
    assert any("runtime-binding helper" in f for f in failures), failures


def test_delegate_chain_cycle_fails(tmp_path):
    """A delegate cycle (A -> B -> A) must be a failure, not an infinite
    loop or a silent pass.
    """
    a = tmp_path / "a.sh"
    b = tmp_path / "b.sh"
    a.write_text("#!/usr/bin/env bash\nset -euo pipefail\nbash b.sh\n", encoding="utf-8")
    b.write_text("#!/usr/bin/env bash\nset -euo pipefail\nbash a.sh\n", encoding="utf-8")

    failures = _verify_delegate_chain(a, tmp_path)
    assert failures
    assert any("cycle" in f for f in failures), failures


def test_delegate_chain_unresolvable_target_is_unsafe_not_assumed_safe(tmp_path):
    """A delegate target that can't be statically resolved (a dynamically
    built path, or one that escapes the repo) must be treated as
    unverified/unsafe -- never silently assumed SAFE.
    """
    delegator = tmp_path / "delegator.sh"
    delegator.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "git pull --ff-only origin main\n"
        'bash "$SCRIPT_DIR/target.sh"\n',
        encoding="utf-8",
    )

    failures = _verify_delegate_chain(delegator, tmp_path)
    assert failures
    assert any("could not be statically resolved" in f for f in failures), failures


def _synthetic_wrapper_lines(set_line, helper_block):
    return (
        "#!/usr/bin/env bash\n"
        f"{set_line}\n"
        "git pull --ff-only origin main\n"
        "source .venv/bin/activate\n"
        "unset PYTHONPATH\n"
        f"{helper_block}"
        "python -m ai_asset_platform.brokers.something\n"
    ).splitlines()


def test_synthetic_helper_failure_propagation_errexit_active_passes():
    """Scenario 1: `set -euo pipefail` + a bare helper call -- a failed
    helper aborts the script via errexit, so this is fail-closed.
    """
    lines = _synthetic_wrapper_lines(
        "set -euo pipefail",
        "bash scripts/ensure_exact_checkout_runtime.sh\n",
    )
    failures = _check_exact_checkout_binding("synthetic_errexit.sh", lines)
    assert not failures, failures


def test_synthetic_helper_failure_propagation_explicit_check_passes():
    """Scenario 2: `set -uo pipefail` (no `-e`) + an explicit
    `if ! helper; then exit; fi` check -- still fail-closed even without
    errexit, because the failure is checked directly.
    """
    lines = _synthetic_wrapper_lines(
        "set -uo pipefail",
        "if ! bash scripts/ensure_exact_checkout_runtime.sh; then\n"
        '  echo "BLOCKED: exact checkout runtime binding failed. No order was sent."\n'
        "  exit 2\n"
        "fi\n",
    )
    failures = _check_exact_checkout_binding("synthetic_explicit_check.sh", lines)
    assert not failures, failures


def test_synthetic_helper_failure_propagation_no_errexit_bare_call_fails():
    """Scenario 3 (the actual `ibkr_all_readonly_completion_once.sh` bug):
    `set -uo pipefail` (no `-e`) + a bare, unchecked helper call -- a
    failed helper does NOT stop the script, so this must be flagged.
    """
    lines = _synthetic_wrapper_lines(
        "set -uo pipefail",
        "bash scripts/ensure_exact_checkout_runtime.sh\n",
    )
    failures = _check_exact_checkout_binding("synthetic_no_errexit_bare.sh", lines)
    assert failures, "expected a failure: helper failure would not stop the script"
    assert any("would not stop this script" in f for f in failures), failures


def test_synthetic_helper_failure_propagation_set_plus_e_after_helper_is_irrelevant():
    """`set +e` appearing *after* the helper call must not matter -- only
    the errexit state at the point of the call does.
    """
    lines = _synthetic_wrapper_lines(
        "set -euo pipefail",
        "bash scripts/ensure_exact_checkout_runtime.sh\nset +e\n",
    )
    failures = _check_exact_checkout_binding("synthetic_set_plus_e_after.sh", lines)
    assert not failures, failures


def test_synthetic_helper_failure_propagation_set_plus_e_before_helper_fails():
    """`set +e` appearing *before* the helper call disables errexit at
    that point; without an explicit check, this must be flagged.
    """
    lines = _synthetic_wrapper_lines(
        "set -euo pipefail",
        "set +e\nbash scripts/ensure_exact_checkout_runtime.sh\n",
    )
    failures = _check_exact_checkout_binding("synthetic_set_plus_e_before.sh", lines)
    assert failures, "expected a failure: errexit was disabled before the helper call"
    assert any("would not stop this script" in f for f in failures), failures


def test_synthetic_helper_conditional_negated_with_exit_passes():
    """`if ! helper; then ... exit N; fi` -- failure runs the `then` body,
    which unconditionally exits. Safe, even without errexit. This is the
    actual pattern used by `ibkr_all_readonly_completion_once.sh`.
    """
    lines = _synthetic_wrapper_lines(
        "set -uo pipefail",
        "if ! bash scripts/ensure_exact_checkout_runtime.sh; then\n"
        '  echo "BLOCKED: exact checkout runtime binding failed. No order was sent."\n'
        "  exit 2\n"
        "fi\n",
    )
    failures = _check_exact_checkout_binding("synthetic_negated_with_exit.sh", lines)
    assert not failures, failures


def test_synthetic_helper_conditional_negated_without_exit_fails():
    """`if ! helper; then echo; fi` (no `exit`/`return`/`exec` in the
    body) -- on failure, the body runs but doesn't stop the script, and
    execution falls through past `fi` to whatever comes next. Must be
    flagged: merely being an if-condition is not proof of anything.
    """
    lines = _synthetic_wrapper_lines(
        "set -uo pipefail",
        "if ! bash scripts/ensure_exact_checkout_runtime.sh; then\n"
        '  echo "binding failed"\n'
        "fi\n",
    )
    failures = _check_exact_checkout_binding("synthetic_negated_without_exit.sh", lines)
    assert failures, "expected a failure: the then-body never exits on helper failure"
    assert any("would not stop this script" in f for f in failures), failures


def test_synthetic_helper_conditional_plain_fails():
    """`if helper; then echo ok; fi` (not negated, no else) -- on
    *failure*, the `then` body is skipped entirely and execution falls
    straight through past `fi`; the failure path has no handling at all.
    Must be flagged.
    """
    lines = _synthetic_wrapper_lines(
        "set -uo pipefail",
        "if bash scripts/ensure_exact_checkout_runtime.sh; then\n"
        '  echo "ok"\n'
        "fi\n",
    )
    failures = _check_exact_checkout_binding("synthetic_plain_if.sh", lines)
    assert failures, "expected a failure: the failure path is entirely unhandled"
    assert any("would not stop this script" in f for f in failures), failures


def test_synthetic_helper_or_exit_same_line_passes():
    """`helper || exit N` on one line -- failure unconditionally exits.
    Safe, even without errexit.
    """
    lines = _synthetic_wrapper_lines(
        "set -uo pipefail",
        "bash scripts/ensure_exact_checkout_runtime.sh || exit 2\n",
    )
    failures = _check_exact_checkout_binding("synthetic_or_exit.sh", lines)
    assert not failures, failures


def test_synthetic_helper_or_exit_brace_group_is_not_recognized_as_safe():
    """`helper || { ...; exit N; }` -- deliberately NOT recognized as safe:
    not used by any real wrapper, and a line-based check can't reliably
    prove a brace group always exits (nested quoting, multiple
    statements). Conservative default: treated as unverified/unsafe.
    """
    lines = _synthetic_wrapper_lines(
        "set -uo pipefail",
        'bash scripts/ensure_exact_checkout_runtime.sh || { echo "failed"; exit 2; }\n',
    )
    failures = _check_exact_checkout_binding("synthetic_or_exit_brace.sh", lines)
    assert failures, "brace-group `||` must not be assumed safe"


def test_synthetic_helper_or_exit_non_exit_command_fails():
    """`helper || echo "please exit 2"` -- the word "exit" appearing in an
    echoed string must not be mistaken for an actual exit statement.
    """
    lines = _synthetic_wrapper_lines(
        "set -uo pipefail",
        'bash scripts/ensure_exact_checkout_runtime.sh || echo "please exit 2"\n',
    )
    failures = _check_exact_checkout_binding("synthetic_or_echo.sh", lines)
    assert failures, "expected a failure: the failure path only echoes, it never exits"
    assert any("would not stop this script" in f for f in failures), failures


def test_synthetic_helper_or_true_with_exit_in_comment_fails():
    """`helper || true  # exit 2` -- "exit 2" is a comment, not code; the
    actual failure-path command is `true`, which never exits the script.
    """
    lines = _synthetic_wrapper_lines(
        "set -uo pipefail",
        "bash scripts/ensure_exact_checkout_runtime.sh || true  # exit 2\n",
    )
    failures = _check_exact_checkout_binding("synthetic_or_true_comment.sh", lines)
    assert failures, "expected a failure: '# exit 2' is a comment, not an executed exit"
    assert any("would not stop this script" in f for f in failures), failures


def test_synthetic_helper_or_printf_with_exit_text_fails():
    """`helper || printf 'exit 2\\n'` -- "exit 2" is printed text, not an
    executed exit statement.
    """
    lines = _synthetic_wrapper_lines(
        "set -uo pipefail",
        "bash scripts/ensure_exact_checkout_runtime.sh || printf 'exit 2\\n'\n",
    )
    failures = _check_exact_checkout_binding("synthetic_or_printf.sh", lines)
    assert failures, "expected a failure: printf'ing the text 'exit 2' does not exit"
    assert any("would not stop this script" in f for f in failures), failures


def test_synthetic_helper_conditional_negated_return_does_not_pass():
    """`if ! helper; then return N; fi` -- `return` does not exit a
    top-level wrapper script (only a function); must not be treated as an
    unconditional exit.
    """
    lines = _synthetic_wrapper_lines(
        "set -uo pipefail",
        "if ! bash scripts/ensure_exact_checkout_runtime.sh; then\n  return 2\nfi\n",
    )
    failures = _check_exact_checkout_binding("synthetic_negated_return.sh", lines)
    assert failures, "expected a failure: 'return' does not exit a top-level script"
    assert any("would not stop this script" in f for f in failures), failures


def test_synthetic_helper_conditional_negated_bare_exec_does_not_pass():
    """`if ! helper; then exec >log.txt; fi` -- a bare/redirection-only
    `exec` does not replace the process or exit; execution continues with
    the redirection applied. Must not be treated as an unconditional exit.
    """
    lines = _synthetic_wrapper_lines(
        "set -uo pipefail",
        "if ! bash scripts/ensure_exact_checkout_runtime.sh; then\n  exec >log.txt\nfi\n",
    )
    failures = _check_exact_checkout_binding("synthetic_negated_exec.sh", lines)
    assert failures, "expected a failure: a bare/redirection-only 'exec' does not exit"
    assert any("would not stop this script" in f for f in failures), failures


def test_synthetic_helper_conditional_negated_then_exits_else_does_not_passes():
    """Scenario A: `if ! helper; then exit 2; else echo ok; fi` -- the
    `then` (failure) branch itself unconditionally exits. Safe, regardless
    of what `else` (the success branch) does.
    """
    lines = _synthetic_wrapper_lines(
        "set -uo pipefail",
        "if ! bash scripts/ensure_exact_checkout_runtime.sh; then\n"
        "  exit 2\n"
        "else\n"
        '  echo "ok"\n'
        "fi\n",
    )
    failures = _check_exact_checkout_binding("synthetic_then_exit_else_ok.sh", lines)
    assert not failures, failures


def test_synthetic_helper_conditional_negated_else_exits_then_does_not_fails():
    """Scenario B: `if ! helper; then echo failed; else exit 2; fi` -- on
    helper *failure*, only the `then` branch runs, and it does not exit.
    The `exit` sitting in `else` (the success branch, which never runs on
    failure) must NOT be read as proof the failure path exits -- that was
    the exact bug this test guards against.
    """
    lines = _synthetic_wrapper_lines(
        "set -uo pipefail",
        "if ! bash scripts/ensure_exact_checkout_runtime.sh; then\n"
        '  echo "binding failed"\n'
        "else\n"
        "  exit 2\n"
        "fi\n",
    )
    failures = _check_exact_checkout_binding("synthetic_then_echo_else_exit.sh", lines)
    assert failures, "expected a failure: the failure (then) branch never exits"
    assert any("would not stop this script" in f for f in failures), failures


def test_synthetic_helper_conditional_negated_elif_exit_does_not_cover_then_fails():
    """Scenario C: `if ! helper; then echo failed; elif ...; then exit 2;
    fi` -- the `elif` branch is not part of the `then` (failure) branch
    either; its `exit` must not count.
    """
    lines = _synthetic_wrapper_lines(
        "set -uo pipefail",
        "if ! bash scripts/ensure_exact_checkout_runtime.sh; then\n"
        '  echo "binding failed"\n'
        'elif [[ -n "$SOMETHING" ]]; then\n'
        "  exit 2\n"
        "fi\n",
    )
    failures = _check_exact_checkout_binding("synthetic_then_echo_elif_exit.sh", lines)
    assert failures, "expected a failure: the elif branch's exit does not cover the then branch"
    assert any("would not stop this script" in f for f in failures), failures


def test_synthetic_helper_conditional_negated_nested_if_exit_fails():
    """Scenario D: `if ! helper; then if something; then exit 2; fi; fi`
    -- the `exit` is inside a further nested conditional, so a helper
    failure alone does not guarantee it runs. Must be flagged.
    """
    lines = _synthetic_wrapper_lines(
        "set -uo pipefail",
        "if ! bash scripts/ensure_exact_checkout_runtime.sh; then\n"
        '  if [[ -n "$SOMETHING" ]]; then\n'
        "    exit 2\n"
        "  fi\n"
        "fi\n",
    )
    failures = _check_exact_checkout_binding("synthetic_then_nested_if_exit.sh", lines)
    assert failures, (
        "expected a failure: the exit is inside a further nested conditional, "
        "not unconditional on the outer helper failure"
    )
    assert any("would not stop this script" in f for f in failures), failures
