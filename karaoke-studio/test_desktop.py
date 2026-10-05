"""Checks backend identity and reuse without opening a window or using a microphone."""
import io
import json
from unittest.mock import patch
from urllib.error import URLError
import desktop


def reply(app='sv-local-vocal-studio',folder=desktop.IDENTITY,version=desktop.BACKEND_VERSION):
    return io.BytesIO(json.dumps({'app':app,'folder':folder,'version':version}).encode())


def main():
    with patch('desktop.BACKEND_VERSION',9),patch('desktop.urlopen',return_value=reply(version=14)):
        assert desktop.ready(), 'frozen launcher must use installed backend version'
    with patch('desktop.urlopen',return_value=reply()),patch('desktop.subprocess.Popen') as launch:
        desktop.ensure_server()
        launch.assert_not_called()
    for response in (reply(app='other-program'),reply(folder='another-installation')):
        with patch('desktop.urlopen',return_value=response):
            try:
                desktop.ready()
                raise AssertionError('another app or installation was accepted')
            except RuntimeError:
                pass
    with patch('desktop.urlopen',side_effect=URLError('offline')):
        assert desktop.ready() is False
    with patch('desktop.urlopen',return_value=reply(version=4)):
        assert desktop.ready() is False
    print('Desktop identity, backend reuse and connection failure checks passed')


if __name__=='__main__':main()
