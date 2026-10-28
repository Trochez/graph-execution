import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

MODULE = Path(__file__).with_name("model_policy.py")
spec = importlib.util.spec_from_file_location("model_policy", MODULE)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class ModelPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Path(self.temp.name) / "policy.json"
        self.available = {"model-a", "model-b"}

    def tearDown(self):
        self.temp.cleanup()

    def save(self, **updates):
        value = {
            "schema_version": 1,
            "model_id": "model-a",
            "confirmed_on": "2025-12-15",
            "confirmed_month": "2025-12",
            "selection_basis": "user preference",
            "confirmation_note": "I confirm model-a",
        }
        value.update(updates)
        self.config.write_text(json.dumps(value), encoding="utf-8")

    def test_initial_and_status_never_writes(self):
        self.assertEqual(policy.status(self.config, self.available, policy.date(2025, 12, 15)), {
            "requires_confirmation": True, "reason": "initial", "selection": None
        })
        self.assertFalse(self.config.exists())

    def test_reuse(self):
        self.save()
        result = policy.status(self.config, self.available, policy.date(2025, 12, 20))
        self.assertFalse(result["requires_confirmation"])
        self.assertEqual(result["reason"], "reuse")

    def test_new_month_and_missed_months_require_review(self):
        self.save()
        for today in (policy.date(2026, 1, 1), policy.date(2026, 4, 1)):
            with self.subTest(today=today):
                self.assertEqual(policy.status(self.config, self.available, today)["reason"], "monthly_review")

    def test_unavailable_model_requires_confirmation(self):
        self.save()
        result = policy.status(self.config, {"model-b"}, policy.date(2025, 12, 20))
        self.assertEqual(result["reason"], "unavailable")

    def test_malformed_and_future_dates_are_invalid(self):
        self.config.write_text("{bad json", encoding="utf-8")
        self.assertEqual(policy.status(self.config, self.available, policy.date(2025, 12, 20))["reason"], "invalid")
        tomorrow = policy.date.today().toordinal() + 1
        future = policy.date.fromordinal(tomorrow)
        self.save(confirmed_on=future.isoformat(), confirmed_month=future.strftime("%Y-%m"))
        self.assertEqual(policy.status(self.config, self.available, policy.date.today())["reason"], "invalid")

    def test_custom_default_override(self):
        with mock.patch.dict(os.environ, {"CODEX_HOME": self.temp.name}):
            self.assertEqual(policy.default_config_path(), Path(self.temp.name) / "native-plan-executor/model-policy.json")

    def test_confirm_persists_atomically_with_private_mode_and_preserves_extra_fields(self):
        self.save(extra="keep")
        value = policy.confirm(self.config, "model-b", self.available, policy.date(2026, 2, 3), "approved choice", "I confirm model-b")
        loaded = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual(value, loaded)
        self.assertEqual(loaded["model_id"], "model-b")
        self.assertEqual(loaded["confirmed_month"], "2026-02")
        self.assertEqual(loaded["extra"], "keep")
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)

    def test_confirm_rejects_empty_confirmation_and_unavailable_model(self):
        with self.assertRaises(ValueError):
            policy.confirm(self.config, "model-a", self.available, policy.date(2026, 2, 3), "basis", " ")
        with self.assertRaises(ValueError):
            policy.confirm(self.config, "model-c", self.available, policy.date(2026, 2, 3), "basis", "confirmed")
        self.assertFalse(self.config.exists())

    def test_status_rejects_empty_or_blank_inventory(self):
        for available in (set(), {" "}):
            with self.subTest(available=available), self.assertRaisesRegex(ValueError, "available inventory"):
                policy.status(self.config, available, policy.date(2026, 2, 3))

    def test_confirm_rejects_blank_model_and_empty_or_blank_inventory(self):
        for model, available in (("", {""}), ("model-a", set()), ("model-a", {" "})):
            with self.subTest(model=model, available=available), self.assertRaises(ValueError):
                policy.confirm(self.config, model, available, policy.date(2026, 2, 3), "basis", "confirmed")
        self.assertFalse(self.config.exists())

    def test_confirm_refuses_to_overwrite_malformed_config(self):
        self.config.write_text("bad", encoding="utf-8")
        with self.assertRaises(ValueError):
            policy.confirm(self.config, "model-a", self.available, policy.date(2026, 2, 3), "basis", "confirmed")
        self.assertEqual(self.config.read_text(encoding="utf-8"), "bad")


if __name__ == "__main__":
    unittest.main()
