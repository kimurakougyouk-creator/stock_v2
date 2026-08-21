# Issue #8 completion mapping

Legacy requirement | Current implementation
--- | ---
`bash scripts/setup.sh` | Existing setup script creates `.venv`, installs requirements, and runs tests.
`bash scripts/run.sh` | Added as a thin wrapper around the existing `start.sh` application flow; it does not duplicate trading logic.
`.env.example` | Added with placeholders only and IBKR Paper disabled by default.
README/start instructions | Canonical minimal commands are documented in `docs/runbook.md`.

This mapping is complete only after CI passes on the branch containing these files.
