# Current hardening change scope

This branch is intentionally limited to repository safety, operator automation, and audit evidence:

- secret re-entry guard and CI integration;
- safe environment template;
- setup/run/audit entrypoints and documentation;
- regression tests for security/automation contracts;
- evidence documents for issues #6, #8, #23, and #50.

It must not change trading strategy thresholds, portfolio risk limits, broker order semantics, enable Live Trading, or claim new asset classes as implemented.
