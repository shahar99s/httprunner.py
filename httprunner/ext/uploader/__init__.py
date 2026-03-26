""" upload test extension.

If you want to use this extension, you should install the following dependencies first.

- requests_toolbelt
- filetype

Then you can write upload test script as below:

    - test:
        name: upload file
        request:
            url: https://httpbin.org/upload
            method: POST
            headers:
                Cookie: session=AAA-BBB-CCC
            upload:
                file: "data/file_to_upload"
                field1: "value1"
                field2: "value2"
        validate:
            - eq: ["status_code", 200]

For compatibility, you can also write upload test script in old way:

    - test:
        name: upload file
        variables:
            file: "data/file_to_upload"
            field1: "value1"
            field2: "value2"
            m_encoder: ${multipart_encoder(file=$file, field1=$field1, field2=$field2)}
        request:
            url: https://httpbin.org/upload
            method: POST
            headers:
                Content-Type: ${multipart_content_type($m_encoder)}
                Cookie: session=AAA-BBB-CCC
            data: $m_encoder
        validate:
            - eq: ["status_code", 200]

"""

import os
import sys
from typing import Text

from httprunner.models import VariablesMapping, TStep
from loguru import logger

try:
    import filetype
    from requests_toolbelt import MultipartEncoder

    class ManagedMultipartEncoder(MultipartEncoder):
        def __init__(self, *args, file_handlers=None, **kwargs):
            super().__init__(*args, **kwargs)
            self._file_handlers = file_handlers or []

        def close(self):
            for file_handler in self._file_handlers:
                try:
                    file_handler.close()
                except Exception as ex:
                    logger.debug(f"failed to close upload file handler: {ex}")
            self._file_handlers.clear()

    UPLOAD_READY = True
except ModuleNotFoundError:
    UPLOAD_READY = False


def ensure_upload_ready():
    if UPLOAD_READY:
        return

    msg = """
    uploader extension dependencies uninstalled, install first and try again.
    install with pip:
    $ pip install requests_toolbelt filetype

    or you can install httprunner with optional upload dependencies:
    $ pip install "httprunner[upload]"
    """
    logger.error(msg)
    sys.exit(1)


def prepare_upload_step(step: TStep, step_variables: VariablesMapping, functions=None):
    """preprocess for upload step
        replace `upload` info with MultipartEncoder

    Args:
        step: step
            {
                "variables": {},
                "request": {
                    "url": "https://httpbin.org/upload",
                    "method": "POST",
                    "headers": {
                        "Cookie": "session=AAA-BBB-CCC"
                    },
                    "upload": {
                        "file": "data/file_to_upload"
                        "md5": "123"
                    }
                }
            }
        functions: functions mapping

    """
    if not step.request.upload:
        return

    ensure_upload_ready()
    upload_mapping = dict(step.request.upload)
    for key, value in upload_mapping.items():
        step_variables[key] = value

    step_variables["m_encoder"] = multipart_encoder(**upload_mapping)
    step.request.headers["Content-Type"] = multipart_content_type(
        step_variables["m_encoder"]
    )
    step.request.data = step_variables["m_encoder"]


def multipart_encoder(**kwargs):
    """initialize MultipartEncoder with uploading fields.

    Returns:
        MultipartEncoder: initialized MultipartEncoder object

    """

    def get_filetype(file_path):
        file_type = filetype.guess(file_path)
        if file_type:
            return file_type.mime
        else:
            return "text/html"

    ensure_upload_ready()
    fields_dict = {}
    file_handlers = []
    for key, value in kwargs.items():
        if os.path.isabs(value):
            # value is absolute file path
            _file_path = value
            is_exists_file = os.path.isfile(value)
        else:
            # value is not absolute file path, check if it is relative file path
            from httprunner.loader import load_project_meta

            project_meta = load_project_meta("")

            _file_path = os.path.join(project_meta.RootDir, value)
            is_exists_file = os.path.isfile(_file_path)

        if is_exists_file:
            # value is file path to upload
            filename = os.path.basename(_file_path)
            mime_type = get_filetype(_file_path)
            file_handler = open(_file_path, "rb")
            file_handlers.append(file_handler)
            fields_dict[key] = (filename, file_handler, mime_type)
        else:
            fields_dict[key] = value

    return ManagedMultipartEncoder(fields=fields_dict, file_handlers=file_handlers)


def multipart_content_type(m_encoder) -> Text:
    """prepare Content-Type for request headers

    Args:
        m_encoder: MultipartEncoder object

    Returns:
        content type

    """
    ensure_upload_ready()
    return m_encoder.content_type
