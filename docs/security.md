# Security and credential handling

## Rules

- Never commit passwords, app passwords, API keys, access tokens, private keys, or `.env` files.
- Runtime credentials must come from environment variables or an ignored local `.env` file.
- `backup/`, `*.save`, `.env`, `.env.*`, and `*.secret` are excluded from normal Git tracking.
- CI runs `python scripts/check_secrets.py` before the test suite.

## If a credential was ever committed

Treat it as compromised even if the file was later deleted.

1. Revoke/disable the exposed credential at the provider.
2. Create a new credential only if the feature still needs one.
3. Store the replacement outside Git (environment variable or ignored `.env`).
4. Confirm the old credential no longer works.
5. Consider Git-history rewriting only after rotation/revocation; history rewriting is disruptive and does not replace revocation.

## Gmail app passwords

A Gmail app password that appeared in Git history must be revoked in the Google Account. Deleting it from the current branch is not sufficient because old commits and PR diffs may remain accessible.
