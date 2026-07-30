import unittest

from src.ai_asset_platform.developer.file_analyzer import analyze_task
from src.ai_asset_platform.developer.task import DevelopmentTask


class TestDevelopmentFileAnalyzer(unittest.TestCase):
    def test_developer_target_adds_tests_directory(self):
        task = DevelopmentTask(
            title="Developer",
            target_file="src/ai_asset_platform/developer/task.py",
            recommended_test="tests/test_development_task.py",
            readiness="READY",
            priority_score=100,
            executable=True,
            safety_checks=(),
            reasons=(),
        )

        result = analyze_task(task)

        self.assertEqual(
            result.primary_target,
            "src/ai_asset_platform/developer/task.py",
        )
        self.assertIn("tests/", result.related_files)


if __name__ == "__main__":
    unittest.main()
