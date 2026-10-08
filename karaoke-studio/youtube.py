"""Single public YouTube video import; downloaded audio stays in the project."""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from lyrics import guess_title
from runtime import ffmpeg_path


def download_error(message):
    message = message.lower()
    if any(text in message for text in ('cookie database', 'failed to decrypt', 'failed to load cookies', 'cookies database')):
        return 'Не удалось прочитать вход из браузера. Закрой все его окна и повтори. Если Windows защищает cookies Edge/Chrome, используй Firefox: войди там на YouTube и выбери его в студии.'
    if 'not a bot' in message or 'confirm you' in message:
        return 'YouTube требует подтверждения входа или «Я не робот». Открой видео в браузере и пройди проверку, затем включи «Использовать мой вход YouTube» и выбери этот браузер. Без галочки студия не использует вход из браузера.'
    if '429' in message or 'too many requests' in message:
        return 'YouTube ограничил запросы с этого подключения (429). Не повторяй загрузку подряд. Проверь видео в браузере; если там нужен вход, подтверди его и включи «Использовать мой вход YouTube». Ограничение подключения может сохраняться и после входа.'
    if 'private video' in message or 'members-only' in message or 'age' in message and 'confirm' in message:
        return 'Видео требует доступа к аккаунту или подтверждения возраста. Выбери доступное видео либо аудиофайл.'
    if 'unavailable' in message or 'not available' in message or 'removed' in message:
        return 'Видео недоступно для загрузки: оно удалено или ограничено. Проверь ссылку либо выбери аудиофайл.'
    if any(word in message for word in ('timed out', 'getaddrinfo', 'unable to download', 'connection')):
        return 'Не удалось подключиться к YouTube. Проверь интернет и попробуй снова либо выбери аудиофайл.'
    return 'Не удалось скачать аудио с YouTube. Подробности сохранены в журнале проекта youtube-error.log. Можно выбрать аудиофайл.'


def video_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('Вставь ссылку на видео YouTube')
    try:
        url = urlsplit(value.strip())
        if url.scheme not in ('http', 'https') or url.username or url.password or url.port:
            raise ValueError()
        if url.hostname == 'youtu.be':
            video = url.path.removeprefix('/')
        elif url.hostname in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
            if url.path == '/watch':
                video = parse_qs(url.query).get('v', [''])[0]
            elif url.path.startswith(('/shorts/', '/embed/', '/live/')):
                video = url.path.split('/')[2]
            else:
                raise ValueError()
        else:
            raise ValueError()
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video):
            raise ValueError()
    except ValueError:
        raise ValueError('Нужна ссылка на отдельное видео YouTube, например https://youtu.be/…') from None
    return 'https://www.youtube.com/watch?v=' + video


def browser_source(value):
    if value is not None and (not isinstance(value,str) or value not in {'edge','chrome','firefox'}):
        raise ValueError('Выбери Edge, Chrome или Firefox для входа YouTube')
    return value


def download_audio(url, folder, report, max_bytes, max_duration, browser=None):
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError
    from yt_dlp.cookies import CookieLoadError

    url = video_url(url)
    browser=browser_source(browser)
    def check(info, *, incomplete=False):
        if info.get('is_live') or info.get('live_status') in ('is_live', 'is_upcoming'):
            return 'Прямые эфиры не поддерживаются. Выбери готовую песню.'
        duration = info.get('duration')
        if duration is not None and not 0 < duration <= max_duration:
            return 'Выбери песню длительностью до 10 минут.'
        if not incomplete and duration is None:
            return 'Не удалось определить длительность видео.'
        if (info.get('filesize') or 0) > max_bytes:
            return 'Аудио больше 150 МБ.'

    def progress(data):
        done = data.get('downloaded_bytes', 0)
        if done > max_bytes:
            raise ValueError('Аудио больше 150 МБ.')
        total = data.get('total_bytes') or data.get('total_bytes_estimate')
        percent = min(100, int(done / total * 100)) if total else None
        report('Скачиваю аудио с YouTube' + (f' · {percent}%' if percent is not None else f' · {done / 1024**2:.1f} МБ'))

    warnings = []
    class Quiet:
        def debug(self, message): pass
        def warning(self, message): warnings.append(str(message))
        def error(self, message): pass

    folder = Path(folder)
    with tempfile.TemporaryDirectory(prefix='youtube-', dir=folder) as pending:
        options = dict(format='bestaudio', noplaylist=True, playlistend=1,
            outtmpl=str(Path(pending) / 'audio.%(ext)s'), match_filter=check,
            max_filesize=max_bytes, socket_timeout=30, retries=2, fragment_retries=2,
            progress_hooks=[progress], logger=Quiet(), quiet=True, restrictfilenames=True)
        node = Path(__file__).resolve().parent / '.runtime/node-v22.23.3-win-x64/node.exe'
        node = str(node) if node.is_file() else shutil.which('node')
        if node:
            options['js_runtimes'] = {'node': {'path': node}}
        if browser:
            options['cookiesfrombrowser']=(browser,)
            report('Читаю разрешённый вход YouTube из '+browser)
        try:
            with YoutubeDL(options) as downloader:
                if browser:
                    jar=downloader.cookiejar
                    for cookie in list(jar):
                        domain=cookie.domain.lstrip('.').lower()
                        if domain!='youtube.com' and not domain.endswith('.youtube.com'):
                            jar.clear(cookie.domain,cookie.path,cookie.name)
                    if not len(jar):
                        raise ValueError('В выбранном браузере нет доступных cookies YouTube. Открой YouTube, войди и пройди проверку. Защищённый вход Edge/Chrome можно заменить входом в Firefox.')
                info = downloader.extract_info(url, download=True)
                if not info or info.get('_type') == 'playlist':
                    raise ValueError('Видео недоступно или не подходит для загрузки.')
                rejection = check(info)
                if rejection:
                    raise ValueError(rejection)
                source = Path(downloader.prepare_filename(info))
            if not source.is_file() or not 0 < source.stat().st_size <= max_bytes:
                raise ValueError('Аудио не скачалось или превышает 150 МБ.')
            report('Подготавливаю аудио YouTube')
            destination = folder / 'upload.m4a'
            result = subprocess.run([ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-y',
                '-i', str(source), '-vn', '-t', str(max_duration + .25), '-c:a', 'aac', '-b:a', '192k',
                str(destination)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode:
                destination.unlink(missing_ok=True)
                raise ValueError('Не удалось прочитать аудио видео. Попробуй загрузить файл.')
            title = str(info.get('title') or 'YouTube')[:200]
            metadata = guess_title(title)
            if info.get('track'):
                metadata['title'] = str(info['track'])[:200]
            if info.get('artist'):
                metadata['artist'] = str(info['artist'])[:200]
            return destination, title + '.m4a', metadata
        except (DownloadError,CookieLoadError) as exc:
            details = '\n'.join(warnings + [str(exc)])
            (folder / 'youtube-error.log').write_text(details, encoding='utf-8')
            raise ValueError(download_error(details)) from None
