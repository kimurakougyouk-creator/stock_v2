# Remaining external/manual checks

The repository can automate code, tests, Paper safety guards, and secret re-entry prevention. It cannot prove provider-side account state.

## Issue #6 — Gmail app password

Before closing issue #6, confirm in the Google Account that the historically exposed Gmail app password has been revoked/removed. If Gmail notifications are still required, create a replacement only after revocation and keep it outside Git.

This is intentionally the only provider-side credential check left to the user; code-side checks should be automated in CI.
