# Secret scanner limitations

`scripts/check_secrets.py` is a lightweight repository guard, not a guarantee that every possible secret format will be detected.

It is designed to catch common private-key/token formats and suspicious hard-coded credential assignments in tracked text files. It does not replace provider-side credential revocation, GitHub's own secret-scanning features when available, or a dedicated third-party scanner for broader pattern coverage.

The security completion rule remains: any credential known or suspected to have been exposed must be revoked at the provider even when the repository scan passes.
