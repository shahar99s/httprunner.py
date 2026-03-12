import copy
import sys

from loguru import logger

from httporchestrator.models import VariablesMapping


def lower_dict_keys(origin_dict):
    """convert keys in dict to lower case

    Args:
        origin_dict (dict): mapping data structure

    Returns:
        dict: mapping with all keys lowered.

    Examples:
        >>> origin_dict = {
            "Name": "",
            "RequestStep": "",
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


def format_response_body_for_log(body, content_type: str = "", content_disposition: str = "", omit_len: int = 512):
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


def merge_variables(variables: VariablesMapping, variables_to_be_overridden: VariablesMapping) -> VariablesMapping:
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
        if isinstance(value, str) and value == f"${key}" and key in variables_to_be_overridden:
            continue

        # Skip None if the existing mapping already has a concrete value
        if value is None and key in variables_to_be_overridden and variables_to_be_overridden[key] is not None:
            continue

        step_new_variables[key] = value

    merged_variables = copy.copy(variables_to_be_overridden)
    merged_variables.update(step_new_variables)
    return merged_variables


LOGGER_FORMAT = "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green>" + " | <level>{level}</level> | <level>{message}</level>"


def init_logger(level: str):
    level = level.upper()
    if level not in ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
        level = "INFO"  # default

    # set log level to INFO
    logger.remove()
    logger.add(sys.stdout, format=LOGGER_FORMAT, level=level)
