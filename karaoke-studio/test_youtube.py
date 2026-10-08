import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import youtube


class YoutubeChecks(unittest.TestCase):
    def test_youtube_errors_distinguish_rate_limit_and_login(self):
        self.assertIn('требует подтверждения', youtube.download_error('HTTP Error 429: Too Many Requests\nSign in to confirm you are not a bot'))
        self.assertIn('429',youtube.download_error('HTTP Error 429: Too Many Requests'))
        self.assertIn('не использует вход из браузера', youtube.download_error("Sign in to confirm you’re not a bot"))
        self.assertIn('недоступно', youtube.download_error('This video is unavailable'))
        self.assertIn('интернет', youtube.download_error('Unable to download webpage: timed out'))
        self.assertIn('youtube-error.log', youtube.download_error('Unknown extractor error'))

    def test_browser_login_requires_explicit_supported_source(self):
        for source in (None,'edge','chrome','firefox'):
            self.assertEqual(youtube.browser_source(source),source)
        for source in (True,False,[],{},'edge:C:/private','unknown'):
            with self.assertRaises(ValueError):youtube.browser_source(source)
        self.assertIn('Firefox',youtube.download_error('Could not copy Chrome cookie database'))

    def test_authorized_cookies_are_scoped_to_youtube_and_not_saved(self):
        from http.cookiejar import Cookie, CookieJar
        jar=CookieJar()
        for domain in ('.youtube.com','www.youtube.com','.unrelated.test'):
            jar.set_cookie(Cookie(0,'session','test',None,False,domain,True,domain.startswith('.'),'/',True,False,None,True,None,None,{}))
        class Context:
            def __init__(self,options):
                self.options=options;self.cookiejar=jar
                self.path=Path(options['outtmpl'].replace('%(ext)s','webm'))
                assert options['cookiesfrombrowser']==('edge',)
                assert 'cookiefile' not in options
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def extract_info(self,url,download):
                assert {c.domain for c in self.cookiejar}=={'.youtube.com','www.youtube.com'}
                self.path.write_bytes(b'audio');return dict(duration=5,title='Artist - Song')
            def prepare_filename(self,info):return str(self.path)
        def convert(command,**kwargs):
            Path(command[-1]).write_bytes(b'converted');return SimpleNamespace(returncode=0)
        with tempfile.TemporaryDirectory() as tmp,patch('yt_dlp.YoutubeDL',Context),patch('youtube.subprocess.run',convert):
            source,_,_=youtube.download_audio('https://youtu.be/jNQXAC9IVRw',Path(tmp),lambda _:None,150,600,browser='edge')
            self.assertEqual(list(Path(tmp).iterdir()),[source])

    def test_import_uses_existing_processing_and_reports_failure(self):
        import app
        identity='c'*32
        with patch('app.jobs', {identity: {'state':'queued'}}), patch('app.download_audio') as download, patch('app.prepare') as prepare:
            metadata=dict(artist='Artist',title='Song')
            download.return_value=(Path('upload.m4a'),'Artist - Song.m4a',metadata)
            app.import_youtube(identity,'https://youtu.be/jNQXAC9IVRw')
            prepare.assert_called_once_with(identity,Path('upload.m4a'),'Artist - Song.m4a',metadata)
            download.side_effect=ValueError('Видео недоступно')
            app.import_youtube(identity,'https://youtu.be/jNQXAC9IVRw')
            self.assertEqual(app.jobs[identity],dict(state='error',error='Видео недоступно'))

    def test_video_urls_and_rejected_inputs(self):
        expected = 'https://www.youtube.com/watch?v=jNQXAC9IVRw'
        for url in ('https://youtu.be/jNQXAC9IVRw?t=3', expected + '&list=extra',
                    'https://m.youtube.com/shorts/jNQXAC9IVRw', 'https://music.youtube.com/watch?v=jNQXAC9IVRw'):
            self.assertEqual(youtube.video_url(url), expected)
        for url in (None, 3, 'file:///etc/passwd', 'https://127.0.0.1/watch?v=jNQXAC9IVRw',
                    'https://youtube.com.evil.test/watch?v=jNQXAC9IVRw',
                    'https://user@youtube.com/watch?v=jNQXAC9IVRw',
                    'https://youtube.com:443/watch?v=jNQXAC9IVRw',
                    'https://youtube.com/playlist?list=abc', 'https://youtu.be/short'):
            with self.assertRaises(ValueError): youtube.video_url(url)

    def test_download_limits_progress_and_project_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            states = []
            def downloader(options):
                check = options['match_filter']
                self.assertTrue(check({'duration': 601}))
                self.assertTrue(check({'is_live': True, 'duration': 1}))
                self.assertTrue(check({'duration': 5, 'filesize': 151}))
                self.assertTrue(check({}))
                self.assertIsNone(check({}, incomplete=True))
                self.assertTrue(options['noplaylist'])
                self.assertNotIn('cookiefile', options)
                self.assertNotIn('cookiesfrombrowser',options)
                path = Path(options['outtmpl'].replace('%(ext)s', 'webm'))
                def extract(url, download):
                    self.assertEqual(url, 'https://www.youtube.com/watch?v=jNQXAC9IVRw')
                    path.write_bytes(b'audio')
                    hook = options['progress_hooks'][0]
                    with self.assertRaises(ValueError): hook({'downloaded_bytes': 151})
                    hook({'downloaded_bytes': 50, 'total_bytes': 100})
                    return dict(duration=5, title='Artist - Song (Official Video)')
                obj = SimpleNamespace(extract_info=extract, prepare_filename=lambda info: str(path))
                return SimpleNamespace(__enter__=lambda: obj)
            class Context:
                def __init__(self, options): self.obj = downloader(options).__enter__()
                def __enter__(self): return self.obj
                def __exit__(self, *args): pass
            def convert(command, **kwargs):
                Path(command[-1]).write_bytes(b'converted audio')
                return SimpleNamespace(returncode=0)
            with patch('yt_dlp.YoutubeDL', Context), patch('youtube.subprocess.run', convert):
                source, filename, info = youtube.download_audio('https://youtu.be/jNQXAC9IVRw', folder, states.append, 150, 600)
            self.assertEqual(source, folder / 'upload.m4a')
            self.assertTrue(source.is_file())
            self.assertEqual(info, dict(artist='Artist', title='Song'))
            self.assertIn('50%', ' '.join(states))
            self.assertEqual(list(folder.iterdir()), [source])


if __name__ == '__main__': unittest.main()
