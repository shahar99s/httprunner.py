import os
import types
from typing import Callable, Dict, Text

from httprunner.models import ProjectMeta

project_meta: ProjectMeta = None


def load_module_functions(module) -> Dict[Text, Callable]:
    """load python module functions."""
    module_functions = {}
    for name, item in vars(module).items():
        if isinstance(item, types.FunctionType):
            module_functions[name] = item
    return module_functions


def load_module_variables(module) -> Dict[Text, object]:
    """load python module non-callable variables."""
    module_variables = {}
    for name, item in vars(module).items():
        if name.startswith("__"):
            continue
        if isinstance(item, (types.FunctionType, types.ModuleType, type)):
            continue
        module_variables[name] = item
    return module_variables


def load_project_meta(start_path: Text = None, reload: bool = False) -> ProjectMeta:
    """Return a minimal ProjectMeta. The root directory defaults to cwd."""
    global project_meta
    if project_meta and not reload:
        return project_meta
    project_meta = ProjectMeta()
    return project_meta
