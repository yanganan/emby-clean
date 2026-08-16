import unittest

from app.security import api_key_is_valid, delete_request_decision
from app.store import _BACKUP_CONFIG_KEYS


class SecurityTests(unittest.TestCase):
    def test_backup_keys_never_include_credentials(self):
        self.assertNotIn("pwd", _BACKUP_CONFIG_KEYS)
        self.assertNotIn("access_token", _BACKUP_CONFIG_KEYS)
        self.assertNotIn("user_id", _BACKUP_CONFIG_KEYS)

    def test_api_key_uses_constant_time_comparison_semantics(self):
        self.assertTrue(api_key_is_valid("secret", "secret"))
        self.assertFalse(api_key_is_valid("wrong", "secret"))
        self.assertFalse(api_key_is_valid("", "secret"))

    def test_unconfirmed_delete_is_dry_run(self):
        decision = delete_request_decision(confirm=False, dry_run=False, source_type="strm")
        self.assertEqual(decision["status"], "dry_run")
        self.assertIn("confirm", decision["reason"])

    def test_remote_source_delete_is_never_allowed(self):
        decision = delete_request_decision(confirm=True, dry_run=False, source_type="strm")
        self.assertEqual(decision["status"], "rejected")
        self.assertIn("远程", decision["reason"])


if __name__ == "__main__":
    unittest.main()
