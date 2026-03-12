import os
import tempfile
import unittest

from httprunner.ext.uploader import UPLOAD_READY, multipart_encoder


@unittest.skipUnless(UPLOAD_READY, "upload dependencies are not installed")
class TestManagedMultipartEncoder(unittest.TestCase):
    def test_close_closes_owned_file_handlers(self):
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(b"payload")
            file_path = temp_file.name

        try:
            encoder = multipart_encoder(file=file_path, field1="value")
            file_handler = encoder._file_handlers[0]

            self.assertFalse(file_handler.closed)

            encoder.close()

            self.assertTrue(file_handler.closed)
        finally:
            os.remove(file_path)