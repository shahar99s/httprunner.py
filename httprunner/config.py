import copy
import inspect
from typing import Text

from httprunner.models import TConfig, VariablesMapping


class Config(object):
    def __init__(self, name: Text) -> None:
        caller_frame = inspect.stack()[1]
        self.__name: Text = name
        self.__base_url: Text = ""
        self.__variables: VariablesMapping = {}
        self.__config = TConfig(name=name, path=caller_frame.filename)
        self.__add_request_id = True

    @property
    def name(self) -> Text:
        return self.__config.name

    @property
    def path(self) -> Text:
        return self.__config.path

    def variables(self, **variables) -> "Config":
        self.__variables.update(variables)
        return self

    def base_url(self, base_url: Text) -> "Config":
        self.__base_url = base_url
        return self

    def verify(self, verify: bool) -> "Config":
        self.__config.verify = verify
        return self

    def add_request_id(self, add_request_id: bool) -> "Config":
        self.__config.add_request_id = add_request_id
        return self

    def export(self, *export_var_name: Text) -> "Config":
        self.__config.export.extend(export_var_name)
        self.__config.export = list(set(self.__config.export))
        return self

    def struct(self) -> TConfig:
        self.__init()
        return self.__config

    def __init(self) -> None:
        self.__config.name = self.__name
        self.__config.base_url = self.__base_url
        self.__config.variables = copy.copy(self.__variables)
