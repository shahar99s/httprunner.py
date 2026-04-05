import unittest

from httporchestrator.config import Config


class TestConfig(unittest.TestCase):
    def test_name(self):
        cfg = Config("my workflow")
        self.assertEqual(cfg.name, "my workflow")

    def test_base_url(self):
        cfg = Config("test").base_url("https://example.com")
        data = cfg.struct()
        self.assertEqual(data.base_url, "https://example.com")

    def test_variables(self):
        cfg = Config("test").variables(foo="bar", num=42)
        data = cfg.struct()
        self.assertEqual(data.variables["foo"], "bar")
        self.assertEqual(data.variables["num"], 42)

    def test_variables_chaining(self):
        cfg = Config("test").variables(a="1").variables(b="2")
        data = cfg.struct()
        self.assertEqual(data.variables["a"], "1")
        self.assertEqual(data.variables["b"], "2")

    def test_verify(self):
        cfg = Config("test").verify(True)
        data = cfg.struct()
        self.assertTrue(data.verify)

        cfg2 = Config("test").verify(False)
        data2 = cfg2.struct()
        self.assertFalse(data2.verify)

    def test_add_request_id(self):
        cfg = Config("test").add_request_id(False)
        data = cfg.struct()
        self.assertFalse(data.add_request_id)

    def test_log_details(self):
        cfg = Config("test").log_details(False)
        data = cfg.struct()
        self.assertFalse(data.log_details)

    def test_export(self):
        cfg = Config("test").export("var1", "var2")
        data = cfg.struct()
        self.assertIn("var1", data.export)
        self.assertIn("var2", data.export)

    def test_export_deduplication(self):
        cfg = Config("test").export("var1").export("var1").export("var2")
        data = cfg.struct()
        self.assertEqual(sorted(data.export), ["var1", "var2"])

    def test_defaults(self):
        cfg = Config("default test")
        data = cfg.struct()
        self.assertEqual(data.base_url, "")
        self.assertFalse(data.verify)
        self.assertTrue(data.add_request_id)
        self.assertTrue(data.log_details)
        self.assertEqual(data.export, [])
        self.assertEqual(data.variables, {})

    def test_path_is_set(self):
        cfg = Config("path test")
        data = cfg.struct()
        self.assertIsNotNone(data.path)
        self.assertIn("test_config.py", data.path)

    def test_struct_reinitializes_variables_on_each_call(self):
        # struct() always returns the same internal ConfigData object.
        # Mutating its variables dict and then calling struct() again must restore
        # the original values — both on the freshly-returned reference and on any
        # previously-held reference (they are the same object).
        cfg = Config("test").variables(x="1")
        data1 = cfg.struct()
        data1.variables["x"] = "modified"

        data2 = cfg.struct()

        # The re-initialized value is visible via both references because struct()
        # re-creates the dict in-place on the single shared ConfigData object.
        self.assertEqual(data2.variables["x"], "1")
        self.assertIs(data1, data2, "struct() should return the same ConfigData object each time")
        self.assertEqual(data1.variables["x"], "1", "previously-held reference must also see the reset")
