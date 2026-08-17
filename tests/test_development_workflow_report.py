from ai_asset_platform.developer.workflow_report import (
    create_workflow_report,
)


def test_create_workflow_report():
    report = create_workflow_report(
        plan="Create feature",
        priority="HIGH",
        readiness=True,
        task="Implement feature",
    )

    assert "Create feature" in report
    assert "HIGH" in report
    assert "READY" in report
    assert "Implement feature" in report
