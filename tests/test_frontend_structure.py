from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "app/static/index.html").read_text(encoding="utf-8")


class FrontendStructureTests(unittest.TestCase):
    def test_uses_media_operations_workspace_structure(self) -> None:
        required_landmarks = (
            'data-ui="workspace-shell"',
            'data-ui="primary-navigation"',
            'data-ui="server-status"',
            'data-ui="scan-workflow"',
            'data-ui="results-workbench"',
        )
        for landmark in required_landmarks:
            with self.subTest(landmark=landmark):
                self.assertIn(landmark, INDEX)

    def test_every_page_has_a_clear_title_and_description(self) -> None:
        for page in ("scan", "results", "tasks", "settings", "storage", "logs"):
            with self.subTest(page=page):
                self.assertIn(f'data-page-heading="{page}"', INDEX)

    def test_design_system_is_extracted_and_avoids_old_glass_shell(self) -> None:
        self.assertIn('href="/static/styles.css"', INDEX)
        self.assertTrue((ROOT / "app/static/styles.css").is_file())
        self.assertNotIn('class="glass ', INDEX)
        self.assertNotIn('class="glass-strong ', INDEX)

    def test_existing_frontend_actions_and_api_contract_remain_available(self) -> None:
        actions = (
            "startScan", "deleteSelected", "ignoreSelected", "syncNow",
            "saveTask", "saveConfig", "testWebhook", "refreshLibrary",
            "exportConfig", "importConfig", "retryFailed", "clearDone",
            "removeIgnored", "clearLogs", "openEmby",
        )
        endpoints = (
            "/api/status", "/api/config", "/api/libraries", "/api/scan",
            "/api/delete", "/api/ignore", "/api/sync", "/api/tasks",
            "/api/delete-queue", "/api/refresh-library", "/api/test_webhook",
            "/api/logs", "/ws",
        )
        for action in actions:
            with self.subTest(action=action):
                self.assertIn(action, INDEX)
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                self.assertIn(endpoint, INDEX)


if __name__ == "__main__":
    unittest.main()
