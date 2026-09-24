from scripts import check_secrets


def _is_ignored_assignment(source: str) -> bool:
    match = check_secrets.CREDENTIAL_ASSIGNMENT.search(source)
    assert match is not None
    value = match.group(1)
    return check_secrets.is_placeholder(value) or check_secrets.is_runtime_reference(value)


def test_shell_parameter_passthrough_is_not_hardcoded_credential() -> None:
    assert _is_ignored_assignment('APP_PASSWORD="${APP_PASSWORD:-}"')
    assert _is_ignored_assignment('OPENAI_API_KEY="$OPENAI_API_KEY"')


def test_literal_credential_remains_detectable() -> None:
    assert not _is_ignored_assignment('APP_PASSWORD="literal-secret-value"')
    assert not _is_ignored_assignment('OPENAI_API_KEY="literal-api-key-value"')


def test_mixed_shell_text_is_not_treated_as_pure_runtime_reference() -> None:
    assert not _is_ignored_assignment('APP_PASSWORD="prefix-${APP_PASSWORD}"')
