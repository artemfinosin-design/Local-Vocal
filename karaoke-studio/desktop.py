"""Windows desktop window. Reuses the installed audio runtime and saved projects."""
import hashlib
import html
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from installer import install, native_setup
from runtime import BACKEND_VERSION
from urllib.error import URLError, HTTPError
from urllib.request import urlopen, Request
from urllib.parse import urlparse

HERE = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
URL = 'http://127.0.0.1:8765'
IDENTITY = hashlib.sha256(str(HERE.resolve()).casefold().encode()).hexdigest()
RUNTIME = HERE / '.runtime'


def ready():
    try:
        with urlopen(URL+'/api/health', timeout=2) as response:
            status = json.load(response)
        if status.get('app') != 'sv-local-vocal-studio' or status.get('folder') != IDENTITY:
            raise RuntimeError('Этот адрес занят другой копией студии. Закрой её перед запуском.')
        return status.get('version') == BACKEND_VERSION
    except (URLError, HTTPError, TimeoutError, OSError):
        return False


def retire_previous_server():
    try:
        with urlopen(URL+'/api/health', timeout=2) as response:status=json.load(response)
    except (URLError, HTTPError, TimeoutError, OSError):return
    if status.get('app') != 'sv-local-vocal-studio' or status.get('folder') != IDENTITY:
        raise RuntimeError('Этот адрес занят другой копией студии. Закрой её перед запуском.')
    if status.get('version') == BACKEND_VERSION:return
    try:
        with urlopen(Request(URL+'/api/shutdown',data=b'{}',headers={'Content-Type':'application/json'}),timeout=5) as response:response.read()
    except HTTPError as exc:
        if exc.code == 409:raise RuntimeError('Дождись окончания обработки в старой студии, затем снова открой программу.') from exc
        if exc.code == 404:raise RuntimeError('В фоне работает прежняя версия студии. После этого обновления один раз перезагрузи Windows и снова открой SvoyaVersiya.exe. Проекты сохранены.') from exc
        raise
    for _ in range(120):
        try:
            with urlopen(URL+'/api/health',timeout=1) as response:response.read()
        except (URLError, HTTPError, TimeoutError, OSError):return
        time.sleep(.5)
    raise RuntimeError('Прежняя студия завершает сохранение. Повтори запуск через минуту.')


def ensure_server(python=None):
    if ready():
        return
    retire_previous_server()
    python = python or install(HERE)
    if not python.exists() or not (HERE / 'app.py').exists():
        raise RuntimeError('Не найдены файлы обработки. Распакуй архив целиком. EXE нужно хранить вместе с остальными файлами студии.')
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1',8765)) == 0:
            raise RuntimeError('Адрес студии занят. Закрой прежнюю студию и запусти программу снова.')
    RUNTIME.mkdir(exist_ok=True)
    environment = dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1')
    with (RUNTIME/'desktop-server.log').open('ab') as log:
        server = subprocess.Popen([str(python), '-u', str(HERE/'app.py'), '--desktop'],
            cwd=HERE, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(120):
        if ready():
            return
        if server.poll() is not None:
            raise RuntimeError('Не удалось запустить обработку. Подробности сохранены в .runtime/desktop-server.log. Перезапусти программу для проверки компонентов.')
        time.sleep(.5)
    raise RuntimeError('Обработка запускается дольше обычного. Повтори запуск через минуту; журнал находится в .runtime/desktop-server.log.')


def main():
    def start_update():
        # Run the installer from stable runtime files; the running EXE must exit
        # before it can be replaced. No shell or elevated permissions are needed.
        pending=HERE/'.runtime/pending-update.json'
        if not pending.exists():raise RuntimeError('Сначала скачай обновление в разделе «Обновления»')
        from updater import validate_manifest
        validate_manifest(json.loads(pending.read_text(encoding='utf-8')))
        if not ready():raise RuntimeError('Дождись запуска студии')
        with urlopen(Request(URL+'/api/shutdown',data=b'{}',headers={'Content-Type':'application/json'}),timeout=5) as response:response.read()
        for _ in range(120):
            try:
                with urlopen(URL+'/api/health',timeout=1) as response:response.read()
            except (URLError,HTTPError,TimeoutError,OSError):break
            time.sleep(.5)
        else:raise RuntimeError('Студия завершает сохранение. Повтори через минуту.')
        python=install(HERE)
        runner=RUNTIME/'update-runner';runner.mkdir(exist_ok=True)
        import shutil
        for name in ('updater.py','runtime.py','installer.py'):shutil.copy2(HERE/name,runner/name)
        subprocess.Popen([str(python),str(runner/'updater.py'),str(HERE)],cwd=HERE,stdin=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    class DesktopApi:
        def apply_update(self):
            origin=urlparse(window.get_current_url() or '')
            if origin.scheme!='http' or origin.netloc!='127.0.0.1:8765':return {'error':'Обновление доступно только в локальной студии'}
            try:start_update()
            except Exception as exc:return {'error':str(exc)}
            window.destroy();return {'ok':True}
    if '--install-check' in sys.argv:
        python=install(HERE,lambda **state:print(json.dumps(state,ensure_ascii=False),flush=True))
        RUNTIME.mkdir(exist_ok=True)
        (RUNTIME/'install-check.json').write_text(json.dumps({'python':str(python),'ready':True}),encoding='utf-8')
        return
    # A command-line check verifies the packaged runtime without microphone access or opening a window.
    if '--check' in sys.argv:
        import webview
        import clr
        clr.AddReference('System.Windows.Forms')
        from webview.platforms import edgechromium
        from Microsoft.Web.WebView2.Core import CoreWebView2Environment
        engine = CoreWebView2Environment.GetAvailableBrowserVersionString()
        ensure_server()
        RUNTIME.mkdir(exist_ok=True)
        (RUNTIME/'desktop-check.json').write_text(json.dumps({'ready':ready(),'native_runtime':True,'webview2':str(engine),
            'folder':str(HERE)},ensure_ascii=False),encoding='utf-8')
        return
    python=None
    if not ready():
        retire_previous_server()
        python=native_setup(HERE)
        if python is None:return
    import webview
    webview.settings['ALLOW_DOWNLOADS'] = True
    webview.settings['ALLOW_FILE_URLS'] = False
    first_launch = not (RUNTIME/'desktop-profile').exists()
    window = webview.create_window('Своя версия · вокальная студия', html='''<!doctype html><html lang="ru"><meta charset="utf-8"><style>
    body{margin:0;background:#172127;color:#eef4ec;font:18px Segoe UI;display:grid;place-items:center;height:100vh}
    main{width:430px}small{color:#ff985a;letter-spacing:3px;font-size:12px}h1{font-size:54px;margin:18px 0}p{color:#aec0c4;line-height:1.7}
    .bar{height:3px;background:#334650;overflow:hidden;margin-top:30px}.bar:after{content:'';display:block;width:35%;height:100%;background:#ff985a;animation:move 1.5s infinite alternate}@keyframes move{to{transform:translateX(180%)}}</style>
    <main><small>LOCAL VOCAL STUDIO</small><h1>СВОЯ ВЕРСИЯ.</h1><p>Запускаю локальную обработку.<br>Песни и записи остаются на компьютере.</p><div class="bar"></div></main></html>''',
        width=1360, height=920, min_size=(1024,740), background_color='#172127', text_select=True,js_api=DesktopApi())
    microphone_choice = []
    permissions_bound = False
    def bind_permissions():
        from System import Action
        from System.Windows.Forms import MessageBox, MessageBoxButtons, MessageBoxIcon, DialogResult
        from Microsoft.Web.WebView2.Core import CoreWebView2PermissionKind, CoreWebView2PermissionState
        def on_permission(sender, args):
            origin=urlparse(str(args.Uri))
            trusted=origin.scheme=='http' and origin.netloc=='127.0.0.1:8765'
            if trusted and args.PermissionKind==CoreWebView2PermissionKind.Microphone:
                if not microphone_choice:
                    answer=MessageBox.Show(window.native,'Разрешить микрофон для записи твоего вокала?',
                        'Своя версия',MessageBoxButtons.YesNo,MessageBoxIcon.Question)
                    microphone_choice.append(answer==DialogResult.Yes)
                args.State=CoreWebView2PermissionState.Allow if microphone_choice[0] else CoreWebView2PermissionState.Deny
            else:
                args.State=CoreWebView2PermissionState.Deny
        def attach():
            nonlocal permissions_bound
            if not permissions_bound:
                window.native.webview.CoreWebView2.PermissionRequested += on_permission
                permissions_bound=True
        window.native.Invoke(Action(attach))
    window.events.loaded += bind_permissions
    def launch():
        try:
            ensure_server(python)
            destination = URL
            window.load_url(destination)
        except Exception as exc:
            window.load_html('<html lang="ru"><meta charset="utf-8"><body style="background:#172127;color:#edf3ec;font:18px Segoe UI;padding:70px"><h1>Не получилось запустить студию</h1><p>'+html.escape(str(exc))+'</p></body></html>')
    webview.start(launch, gui='edgechromium', private_mode=False,
                  storage_path=str(RUNTIME/'desktop-profile'),icon=str(HERE/'app.ico'))
    # Leave the local backend running: closing the window must not interrupt separation or training.


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        RUNTIME.mkdir(exist_ok=True)
        (RUNTIME/'desktop-error.log').write_text(str(exc),encoding='utf-8')
        if '--check' not in sys.argv and '--install-check' not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, 'Не удалось открыть окно студии.\n'+str(exc), 'Своя версия', 0x10)
        sys.exit(1)
