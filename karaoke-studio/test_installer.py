"""First-run integrity, interrupted downloads and repair-path checks."""
import hashlib
import http.server
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
import installer


class SetupTests(unittest.TestCase):
    def test_resume_and_integrity(self):
        payload=b'voice-model'*100000
        requests=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                offset=int(self.headers.get('Range','bytes=0-')[6:-1])
                requests.append(offset)
                self.send_response(206 if offset else 200)
                if offset:self.send_header('Content-Range',f'bytes {offset}-{len(payload)-1}/{len(payload)}')
                self.send_header('Content-Length',str(len(payload)-offset));self.end_headers()
                self.wfile.write(payload[offset:])
            def log_message(self,*args):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                target=Path(folder)/'model.bin'
                target.with_name('model.bin.partial').write_bytes(payload[:123456])
                digest=hashlib.sha256(payload).hexdigest()
                url=f'http://127.0.0.1:{server.server_port}/model'
                states=[]
                installer.download(url,target,lambda **s:states.append(s),threading.Event(),digest)
                self.assertEqual(requests,[123456]);self.assertEqual(target.read_bytes(),payload)
                self.assertEqual(states[-1],dict(done=len(payload),total=len(payload)))
                installer.download(url,target,lambda **s:None,threading.Event(),digest)
                self.assertEqual(len(requests),1)
                target.unlink()
                with self.assertRaisesRegex(RuntimeError,'Проверка'):
                    installer.download(url,target,lambda **s:None,threading.Event(),'0'*64)
                self.assertFalse(target.exists())
        finally:server.shutdown();server.server_close();thread.join()

    def test_archive_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=Path(folder)/'bad.zip'
            with ZipFile(archive,'w') as z:z.writestr('../outside.txt','bad')
            with self.assertRaises(ValueError):installer.unpack(archive,Path(folder)/'runtime')
            self.assertFalse((Path(folder)/'outside.txt').exists())

    def test_cancel_before_download(self):
        cancel=threading.Event();cancel.set()
        with tempfile.TemporaryDirectory() as folder,patch('installer.urlopen') as network:
            with self.assertRaises(InterruptedError):
                installer.download('https://example.invalid',Path(folder)/'file',lambda **s:None,cancel)
            network.assert_not_called()

    def test_probe_checks_missing_audio_dependency(self):
        import subprocess
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'.runtime').mkdir()
            failure=subprocess.CompletedProcess([],1,'ModuleNotFoundError: imageio_ffmpeg')
            with patch('installer.subprocess.run',return_value=failure) as probe:
                self.assertFalse(installer.dependencies_ok('python.exe',root))
                self.assertIn('imageio_ffmpeg',probe.call_args.args[0][-1])
            self.assertIn('imageio_ffmpeg',(root/'.runtime/install.log').read_text())


if __name__=='__main__':unittest.main()
