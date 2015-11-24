import unittest
import mock

from rpaas.ssl_plugins import le


def patch_main(args):
    return "crt", "chain", "key"


class LETest(unittest.TestCase):

    def setUp(self):
        self.patcher = mock.patch('rpaas.ssl_plugins.le._main', patch_main)
        self.patcher.start()
        self.instance = le.LE(['domain'], 'email@corp', ['host1'])

    def tearDown(self):
        self.patcher.stop()

    def test_upload_csr(self):
        self.assertEqual(self.instance.upload_csr('asdasdasdasdadasd'), None)

    def test_download_crt(self):
        with mock.patch.object(le.LE, 'download_crt', return_value=None) as mock_method:
            instance = self.instance
            instance.download_crt(None)
        mock_method.assert_called_once_with(None)
