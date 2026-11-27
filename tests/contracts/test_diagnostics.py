import unittest
from graph_execution_runtime.diagnostics import classify

class DiagnosticsTests(unittest.TestCase):
    def test_classifications_exclude_raw_data(self):
        r=classify("Traceback (most recent call last)\nUsageLimitExceeded: request_limit=60; key=private-test-value")
        self.assertIn("request_budget",r["signals"])
        self.assertTrue(r["traceback_present"])
        self.assertNotIn("private-test-value",str(r))
    def test_unknown(self):
        self.assertEqual(classify("unrelated failure")["signals"],["unclassified"])
    def test_provider(self):
        self.assertIn("context_overflow",classify("context_length_exceeded")["signals"])
        self.assertIn("provider_rate_limit",classify("RateLimitError")["signals"])
