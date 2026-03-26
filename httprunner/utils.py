import collections
import copy
import itertools
import json
import os
import os.path
import platform
import random
import sys
import time
import uuid
from multiprocessing import Queue
from typing import Any, Dict, List

from loguru import logger

from httprunner import __version__, exceptions
from httprunner.models import VariablesMapping


""" run httpbin as a service
https://github.com/postmanlabs/httpbin

$ docker pull kennethreitz/httpbin
$ docker run -p 80:80 kennethreitz/httpbin
"""
HTTP_BIN_URL = "http://127.0.0.1:80"


def get_platform():
    return {
        "httprunner_version": __version__,
        "python_version": "{} {}".format(
            platform.python_implementation(), platform.python_version()
        ),
        "platform": platform.platform(),
    }


def set_os_environ(variables_mapping):
    """set variables mapping to os.environ"""
    for variable in variables_mapping:
        os.environ[variable] = variables_mapping[variable]
        logger.debug(f"Set OS environment variable: {variable}")


def unset_os_environ(variables_mapping):
    """unset variables mapping to os.environ"""
    for variable in variables_mapping:
        os.environ.pop(variable)
        logger.debug(f"Unset OS environment variable: {variable}")


def get_os_environ(variable_name):
    """get value of environment variable.

    Args:
        variable_name(str): variable name

    Returns:
        value of environment variable.

    Raises:
        exceptions.EnvNotFound: If environment variable not found.

    """
    try:
        return os.environ[variable_name]
    except KeyError:
        raise exceptions.EnvNotFound(variable_name)


def lower_dict_keys(origin_dict):
    """convert keys in dict to lower case

    Args:
        origin_dict (dict): mapping data structure

    Returns:
        dict: mapping with all keys lowered.

    Examples:
        >>> origin_dict = {
            "Name": "",
            "Request": "",
            "URL": "",
            "METHOD": "",
            "Headers": "",
            "Data": ""
        }
        >>> lower_dict_keys(origin_dict)
            {
                "name": "",
                "request": "",
                "url": "",
                "method": "",
                "headers": "",
                "data": ""
            }

    """
    if not origin_dict or not isinstance(origin_dict, dict):
        return origin_dict

    return {key.lower(): value for key, value in origin_dict.items()}


def print_info(info_mapping):
    """print info in mapping.

    Args:
        info_mapping (dict): input(variables) or output mapping.

    Examples:
        >>> info_mapping = {
                "var_a": "hello",
                "var_b": "world"
            }
        >>> info_mapping = {
                "status_code": 500
            }
        >>> print_info(info_mapping)
        ==================== Output ====================
        Key              :  Value
        ---------------- :  ----------------------------
        var_a            :  hello
        var_b            :  world
        ------------------------------------------------

    """
    if not info_mapping:
        return

    content_format = "{:<16} : {:<}\n"
    content = "\n==================== Output ====================\n"
    content += content_format.format("Variable", "Value")
    content += content_format.format("-" * 16, "-" * 29)

    for key, value in info_mapping.items():
        if isinstance(value, (tuple, collections.deque)):
            continue
        elif isinstance(value, (dict, list)):
            value = json.dumps(value)
        elif value is None:
            value = "None"

        content += content_format.format(key, value)

    content += "-" * 48 + "\n"
    logger.info(content)


def omit_long_data(body, omit_len=512):
    """omit too long str/bytes"""
    if not isinstance(body, (str, bytes)):
        return body

    body_len = len(body)
    if body_len <= omit_len:
        return body

    omitted_body = body[0:omit_len]

    appendix_str = f" ... OMITTED {body_len - omit_len} CHARACTORS ..."
    if isinstance(body, bytes):
        appendix_str = appendix_str.encode("utf-8")

    return omitted_body + appendix_str


def format_response_body_for_log(
    body, content_type: str = "", content_disposition: str = "", omit_len: int = 512
):
    """format response body for logs without dumping large binary payloads"""
    lower_content_type = (content_type or "").lower()
    lower_content_disposition = (content_disposition or "").lower()

    if isinstance(body, (dict, list)):
        return body

    if isinstance(body, str):
        return omit_long_data(body, omit_len)

    if isinstance(body, bytes):
        is_text_like = lower_content_type.startswith("text/") or any(
            marker in lower_content_type
            for marker in [
                "json",
                "xml",
                "javascript",
                "x-www-form-urlencoded",
                "html",
            ]
        )
        is_attachment = "attachment" in lower_content_disposition

        if is_text_like and not is_attachment:
            try:
                return omit_long_data(body.decode("utf-8"), omit_len)
            except UnicodeDecodeError:
                pass

        return f"<binary content omitted: {len(body)} bytes, content-type={content_type or 'unknown'}>"

    return body


def sort_dict_by_custom_order(raw_dict: Dict, custom_order: List):
    def get_index_from_list(lst: List, item: Any):
        try:
            return lst.index(item)
        except ValueError:
            # item is not in lst
            return len(lst) + 1

    return dict(
        sorted(raw_dict.items(), key=lambda i: get_index_from_list(custom_order, i[0]))
    )


class ExtendJSONEncoder(json.JSONEncoder):
    """especially used to safely dump json data with python object,
    such as MultipartEncoder"""

    def default(self, obj):
        try:
            return super(ExtendJSONEncoder, self).default(obj)
        except (UnicodeDecodeError, TypeError):
            return repr(obj)


def merge_variables(
    variables: VariablesMapping, variables_to_be_overridden: VariablesMapping
) -> VariablesMapping:
    """merge two variables mapping, the first variables have higher priority.

    None values in `variables` do not override an existing non-None value in
    `variables_to_be_overridden` — None is treated as "unset / keep existing".
    If the key is absent in `variables_to_be_overridden`, None is still
    preserved so the parser sees the key as defined.
    """
    step_new_variables = {}
    for key, value in variables.items():
        # Keep original config value when step variable is only a self-reference
        # like "$base_url".
        if (
            isinstance(value, str)
            and value in (f"${key}", f"${{{key}}}")
            and key in variables_to_be_overridden
        ):
            continue

        # Skip None if the existing mapping already has a concrete value
        if value is None and key in variables_to_be_overridden and variables_to_be_overridden[key] is not None:
            continue

        step_new_variables[key] = value

    merged_variables = copy.copy(variables_to_be_overridden)
    merged_variables.update(step_new_variables)
    return merged_variables


def is_support_multiprocessing() -> bool:
    try:
        Queue()
        return True
    except (ImportError, OSError):
        # system that does not support semaphores
        # (dependency of multiprocessing), like Android termux
        return False


def gen_cartesian_product(*args: List[Dict]) -> List[Dict]:
    """generate cartesian product for lists

    Args:
        args (list of list): lists to be generated with cartesian product

    Returns:
        list: cartesian product in list

    Examples:

        >>> arg1 = [{"a": 1}, {"a": 2}]
        >>> arg2 = [{"x": 111, "y": 112}, {"x": 121, "y": 122}]
        >>> args = [arg1, arg2]
        >>> gen_cartesian_product(*args)
        >>> # same as below
        >>> gen_cartesian_product(arg1, arg2)
            [
                {'a': 1, 'x': 111, 'y': 112},
                {'a': 1, 'x': 121, 'y': 122},
                {'a': 2, 'x': 111, 'y': 112},
                {'a': 2, 'x': 121, 'y': 122}
            ]

    """
    if not args:
        return []
    elif len(args) == 1:
        return args[0]

    product_list = []
    for product_item_tuple in itertools.product(*args):
        product_item_dict = {}
        for item in product_item_tuple:
            product_item_dict.update(item)

        product_list.append(product_item_dict)

    return product_list


LOGGER_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green>"
    + " | <level>{level}</level> | <level>{message}</level>"
)


def init_logger(level: str):
    level = level.upper()
    if level not in ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
        level = "INFO"  # default

    # set log level to INFO
    logger.remove()
    logger.add(sys.stdout, format=LOGGER_FORMAT, level=level)
