from scripts import check_secrets


def _is_ignored_assignment(source: str) -> bool:
    match = check_secrets.CREDENTIAL_ASSIGNMENT.search(source)
    assert match is not None
    value = match.group(1)
    return check_secrets.is_placeholder(value) or check_secrets.is_runtime_reference(value)


def _assignment(name: str, value: str) -> str:
    # Build scanner-negative test fixtures at runtime so this test file does not
    # itself contain a credential-shaped assignment that the repository scanner
    # is correctly required to reject.
    return f'{name}="{value}"'


def test_shell_parameter_passthrough_is_not_hardcoded_credential() -> None:
    assert _is_ignored_assignment(_assignment("APP_PASSWORD", "${APP_PASSWORD:-}"))
    assert _is_ignored_assignment(_assignment("OPENAI_API_KEY", "$OPENAI_API_KEY"))


def test_literal_credential_remains_detectable() -> None:
    literal_password = "literal" + "-secret-value"
    literal_api_key = "literal" + "-api-key-value"
    assert not _is_ignored_assignment(_assignment("APP_PASSWORD", literal_password))
    assert not _is_ignored_assignment(_assignment("OPENAI_API_KEY", literal_api_key))


def test_mixed_shell_text_is_not_treated_as_pure_runtime_reference() -> None:
    mixed_reference = "prefix-" + "${APP_PASSWORD}"
    assert not _is_ignored_assignment(_assignment("APP_PASSWORD", mixed_reference))
