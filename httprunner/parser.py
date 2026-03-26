import ast
from typing import Any, Text
from urllib.parse import urlparse

from httprunner import exceptions


def parse_string_value(str_value: Text) -> Any:
    """parse string to number if possible
    e.g. "123" => 123
         "12.2" => 12.3
         "abc" => "abc"
    """
    try:
        return ast.literal_eval(str_value)
    except (ValueError, SyntaxError):
        return str_value


def build_url(base_url, step_url):
    """prepend url with base_url unless it's already an absolute URL"""
    o_step_url = urlparse(step_url)
    if o_step_url.netloc != "":
        return step_url

    o_base_url = urlparse(base_url)
    if o_base_url.netloc == "":
        raise exceptions.ParamsError("base url missed!")

    path = o_base_url.path.rstrip("/") + "/" + o_step_url.path.lstrip("/")
    o_step_url = (
        o_step_url._replace(scheme=o_base_url.scheme)
        ._replace(netloc=o_base_url.netloc)
        ._replace(path=path)
    )
    return o_step_url.geturl()
