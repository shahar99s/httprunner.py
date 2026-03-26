import os
import unittest

from httprunner import loader


class TestLoader(unittest.TestCase):
    def test_load_module_functions(self):
        import httprunner.builtin.functions as funcs_module
        funcs = loader.load_module_functions(funcs_module)
        self.assertIn("gen_random_string", funcs)
        self.assertIn("get_timestamp", funcs)

    def test_load_module_variables(self):
        import types
        mod = types.ModuleType("test_mod")
        mod.MY_VAR = 42
        mod.my_func = lambda: None
        result = loader.load_module_variables(mod)
        self.assertIn("MY_VAR", result)
        self.assertNotIn("my_func", result)

    def test_load_project_meta(self):
        loader.project_meta = None
        meta = loader.load_project_meta(reload=True)
        self.assertEqual(meta.RootDir, os.getcwd())

    def test_load_project_meta_cached(self):
        loader.project_meta = None
        meta1 = loader.load_project_meta(reload=True)
        meta2 = loader.load_project_meta()
        self.assertIs(meta1, meta2)
