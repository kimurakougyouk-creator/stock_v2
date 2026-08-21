# Automation policy

Automate repository-side work before asking the operator to perform manual steps.

Manual operator work is reserved for external actions that cannot be safely performed from the repository, such as provider login, identity verification, provider-side credential revocation, and a deliberately approved real Paper-order test.

Do not split one unavoidable operator action into many small copy/paste steps when it can be safely consolidated. Prefer setup, run, and audit entrypoints over ad-hoc command sequences.
