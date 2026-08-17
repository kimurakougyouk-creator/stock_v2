from ai_asset_platform.developer.workflow_summary import summarize_workflow


def test_summarize_workflow_returns_counts():
    workflow = [
        {"status": "completed"},
        {"status": "completed"},
        {"status": "pending"},
    ]

    summary = summarize_workflow(workflow)

    assert summary == {
        "total": 3,
        "completed": 2,
        "pending": 1,
    }


def test_summarize_workflow_empty():
    assert summarize_workflow([]) == {
        "total": 0,
        "completed": 0,
        "pending": 0,
    }
