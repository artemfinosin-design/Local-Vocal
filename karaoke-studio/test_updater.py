import hashlib,json,tempfile,unittest
from pathlib import Path
from zipfile import ZipFile
from unittest.mock import patch
from updater import stage_archive,apply_staged,validate_manifest,Updates


def package(root,extra=None):
    files={'SvoyaVersiya.exe':b'new-exe','runtime.py':b'BACKEND_VERSION = 999\n','desktop.py':b'new-launcher','app.py':b'new-server'}
    archive=root/'release.zip'
    with ZipFile(archive,'w') as z:
        for name,data in files.items():z.writestr('karaoke-studio/'+name,data)
        if extra:z.writestr(extra,b'bad')
    manifest=dict(schema=1,version=999,asset='release.zip',bytes=archive.stat().st_size,
                  sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                  files={name:dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest()) for name,data in files.items()})
    return archive,manifest


class UpdateChecks(unittest.TestCase):
    def test_verified_install_preserves_audio_and_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'data').mkdir();(root/'data/take.wav').write_bytes(b'private-audio')
            (root/'.runtime').mkdir();(root/'.runtime/installed.json').write_bytes(b'runtime')
            (root/'SvoyaVersiya.exe').write_bytes(b'old-exe')
            archive,manifest=package(root);stage_archive(root,archive,manifest)
            self.assertEqual(Updates(root).snapshot()['state'],'prepared')
            apply_staged(root)
            self.assertEqual((root/'SvoyaVersiya.exe').read_bytes(),b'new-exe')
            self.assertEqual((root/'data/take.wav').read_bytes(),b'private-audio')
            self.assertEqual((root/'.runtime/installed.json').read_bytes(),b'runtime')
            self.assertFalse((root/'.runtime/pending-update.json').exists())
    def test_partial_commit_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('SvoyaVersiya.exe','app.py','runtime.py','desktop.py'):(root/name).write_bytes(b'old')
            archive,manifest=package(root);stage_archive(root,archive,manifest)
            original=Path.replace
            def fail(source,target):
                if source.name=='app.py.update-tmp':raise OSError('simulated write failure')
                return original(source,target)
            with patch.object(Path,'replace',fail),self.assertRaises(OSError):apply_staged(root)
            for name in ('SvoyaVersiya.exe','app.py','runtime.py','desktop.py'):self.assertEqual((root/name).read_bytes(),b'old')
    def test_bad_checksum_and_undeclared_or_data_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);archive,manifest=package(root,'../escape.py')
            with self.assertRaises(ValueError):stage_archive(root,archive,manifest)
            archive,manifest=package(root);manifest['sha256']='0'*64
            with self.assertRaises(ValueError):stage_archive(root,archive,manifest)
            manifest['files']['data/take.wav']=manifest['files']['app.py']
            with self.assertRaises(ValueError):validate_manifest(manifest)


if __name__=='__main__':unittest.main()
