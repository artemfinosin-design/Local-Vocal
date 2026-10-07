"""Repairable first-run setup. Downloads are verified before they become usable."""
import hashlib
import base64
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from urllib.request import Request, urlopen
from zipfile import ZipFile


def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def check_cancel(cancel):
    if cancel.is_set():raise InterruptedError('Установка остановлена. Можно продолжить при следующем запуске.')


def download(url, target, report, cancel, digest=None):
    """Range resume; a partial file never masquerades as a finished component."""
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists() and digest and sha256(target)==digest:return target
    partial=target.with_name(target.name+'.partial')
    if partial.exists() and digest and sha256(partial)==digest:
        count=partial.stat().st_size;partial.replace(target);report(done=count,total=count);return target
    offset=partial.stat().st_size if partial.exists() else 0
    headers={'User-Agent':'SvoyaVersiya/1.0'}
    if offset:headers['Range']='bytes='+str(offset)+'-'
    check_cancel(cancel)
    with urlopen(Request(url,headers=headers),timeout=45) as response:
        resumed=offset and response.status==206
        if resumed and not response.headers.get('Content-Range','').startswith('bytes '+str(offset)+'-'):
            raise RuntimeError('Сервер вернул неверный диапазон загрузки. Повтори установку.')
        if not resumed:offset=0
        size=response.headers.get('Content-Length')
        total=offset+int(size) if size and size.isdigit() else None
        downloaded=offset;last=0
        with partial.open('ab' if resumed else 'wb') as output:
            while True:
                check_cancel(cancel)
                block=response.read(256*1024)
                if not block:break
                output.write(block);downloaded+=len(block)
                if time.monotonic()-last>.15:
                    report(done=downloaded,total=total);last=time.monotonic()
        if total is not None and downloaded!=total:
            raise RuntimeError('Загрузка прервалась. Уже скачанная часть сохранена — нажми «Повторить».')
    if digest and sha256(partial)!=digest:
        # Keep a rejected download as a diagnostic file, never install or execute it.
        partial.replace(partial.with_name(partial.name+'.rejected'))
        raise RuntimeError('Проверка загруженного файла не прошла. Нажми «Повторить», чтобы скачать его заново.')
    partial.replace(target);report(done=downloaded,total=total)
    return target


def unpack(archive, destination):
    destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True)
    with ZipFile(archive) as zipped:
        for member in zipped.infolist():
            resolved=(destination/member.filename).resolve()
            if not resolved.is_relative_to(destination):raise ValueError('Недопустимый путь в архиве компонента')
            if (member.external_attr>>16)&0o170000==0o120000:raise ValueError('Ссылка в архиве компонента')
        zipped.extractall(destination)


def run(command, root, report, cancel, label):
    """Capture output while polling cancellation; no command windows or silent hangs."""
    root=Path(root);log=root/'.runtime/install.log';log.parent.mkdir(exist_ok=True)
    report(detail=label,done=None,total=None)
    environment=dict(os.environ,PYTHONUTF8='1',PYTHONUNBUFFERED='1',PIP_DISABLE_PIP_VERSION_CHECK='1')
    process=subprocess.Popen(list(map(str,command)),cwd=root,env=environment,stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',
        creationflags=subprocess.CREATE_NO_WINDOW)
    lines=queue.Queue();tail=[]
    def read():
        for line in process.stdout:lines.put(line)
        lines.put(None)
    threading.Thread(target=read,daemon=True).start()
    try:
        with log.open('a',encoding='utf-8') as output:
            while True:
                check_cancel(cancel)
                try:line=lines.get(timeout=.2)
                except queue.Empty:continue
                if line is None:break
                output.write(line);output.flush();tail=(tail+[line.strip()])[-12:]
                match=re.search(r'(?:Downloading|Collecting|Installing collected packages:)\s+([^\s(]+)',line)
                if match:report(detail=label+' · '+match.group(1).rsplit('/',1)[-1].split('?')[0][:80])
        code=process.wait()
        if code:
            last='\n'.join(tail)
            if 'No space left' in last or 'not enough space' in last:
                raise RuntimeError('Не хватает места на диске. Освободи место и нажми «Повторить».')
            if any(word in last for word in ('ConnectionError','ReadTimeout','ConnectTimeout','CERTIFICATE_VERIFY_FAILED','Max retries')):
                raise RuntimeError('Не удалось скачать компонент. Проверь интернет и нажми «Повторить». Подробности — в журнале.')
            raise RuntimeError('Не удалось завершить этап «'+label+'». Нажми «Повторить». Подробности — в журнале установки.')
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        process.stdout.close()


def usable_python(path):
    if not Path(path).exists():return False
    try:
        result=subprocess.run([str(path),'-c','import sys,struct;sys.exit(0 if sys.version_info[:2] in ((3,11),(3,12)) and struct.calcsize("P")==8 else 1)'],
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
        return result.returncode==0
    except (OSError,subprocess.TimeoutExpired):return False


PROBE='''import imageio_ffmpeg,numpy,scipy,pyworld,librosa,torch,torchvision,torchaudio,sklearn,stable_whisper,yt_dlp,yt_dlp_ejs,parselmouth
from audio_separator.separator import Separator
from runtime import ffmpeg_path
import subprocess
subprocess.run([ffmpeg_path(),'-version'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
'''


def dependencies_ok(python, root):
    try:
        result=subprocess.run([str(python),'-c',PROBE],cwd=root,stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',
            timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            with (Path(root)/'.runtime/install.log').open('a',encoding='utf-8') as log:log.write(result.stdout+'\n')
        return result.returncode==0
    except (OSError,subprocess.TimeoutExpired):return False


def _install(root, report, cancel, force):
    root=Path(root).resolve();cancel=cancel or threading.Event()
    runtime=root/'.runtime';runtime.mkdir(exist_ok=True)
    manifest=json.loads((root/'install-manifest.json').read_text(encoding='utf-8'))
    def stage(number,title):report(stage=number,title=title,detail='',done=None,total=None)
    stage(1,'Проверяю компоненты')
    python=root/'.venv/Scripts/python.exe'
    if not usable_python(python):
        python=runtime/'python/python.exe'
        if not usable_python(python):
            stage(1,'Скачиваю среду обработки')
            item=manifest['python'];archive=download(item['url'],runtime/'downloads/python.zip',report,cancel,item['sha256'])
            unpack(archive,python.parent)
            (python.parent/'python312._pth').write_text('python312.zip\n.\nLib/site-packages\n../../\nimport site\n',encoding='utf-8')
            if not usable_python(python):raise RuntimeError('Не удалось подготовить среду обработки. Нажми «Повторить».')
    if python.parent == runtime/'python':
        (python.parent/'python312._pth').write_text('python312.zip\n.\nLib/site-packages\n../../\nimport site\n',encoding='utf-8')
    stage(2,'Проверяю обработку звука')
    if force or not dependencies_ok(python,root):
        if shutil.disk_usage(root).free<2*1024**3:
            raise RuntimeError('Для установки нужно минимум 2 ГБ свободного места на диске.')
        stage(2,'Подготавливаю установку')
        item=manifest['pip'];wheel=download(item['url'],runtime/'downloads/pip.whl',report,cancel,item['sha256'])
        # Embedded Python has no pip or venv. Its own site-packages is fully local.
        site=python.parent/'Lib/site-packages' if python.parent.name=='python' else root/'.venv/Lib/site-packages'
        probe=subprocess.run([str(python),'-m','pip','--version'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        if probe.returncode:unpack(wheel,site)
        stage(2,'Скачиваю и устанавливаю обработку звука')
        # Pin official CPU wheels, including during repairs, so pip cannot switch builds.
        tag=subprocess.check_output([str(python),'-c','import sys;print("cp%d%d"%sys.version_info[:2])'],text=True,creationflags=subprocess.CREATE_NO_WINDOW).strip()
        cpu=manifest['cpu'][tag]
        cpu_probe="import torch,torchvision,torchaudio;assert (torch.__version__,torchvision.__version__,torchaudio.__version__)==('2.5.1+cpu','0.20.1+cpu','2.5.1+cpu')"
        cpu_ready=subprocess.run([str(python),'-c',cpu_probe],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW).returncode==0
        wheels=[]
        if force or not cpu_ready:
            for item in cpu:
                report(detail='Обработка голоса · '+item['name'],done=None,total=None)
                wheels.append(download(item['url'],runtime/'downloads'/item['filename'],report,cancel,item['sha256']))
        if not cpu_ready:
            run([python,'-m','pip','install','--progress-bar','off',*wheels],root,report,cancel,'Подготавливаю обработку голоса')
        # Embedded Python ignores pip's temporary build PYTHONPATH. Pure Python
        # packages therefore build against these local tools, without isolation.
        run([python,'-m','pip','install','--progress-bar','off','setuptools==75.8.2','wheel==0.45.1'],root,report,cancel,'Подготавливаю аудиокомпоненты')
        constraints=runtime/'cpu-constraints.txt'
        constraints.write_text('torch==2.5.1+cpu\ntorchvision==0.20.1+cpu\ntorchaudio==2.5.1+cpu\n',encoding='utf-8')
        command=[python,'-m','pip','install','--no-build-isolation','--progress-bar','off','--timeout','40','--retries','3','-c',constraints,'-r',root/'requirements.txt',*wheels]
        if force:command.append('--force-reinstall')
        run(command,root,report,cancel,'Аудиокомпоненты')
        if not dependencies_ok(python,root):
            raise RuntimeError('Компоненты скачаны, но проверка звука не прошла. Нажми «Повторить» для восстановления установки.')
    item=manifest['youtube_runtime']
    node=runtime/item['folder']/'node.exe'
    if force or not usable_node(node):
        stage(2,'Подготавливаю загрузку с YouTube')
        archive=download(item['url'],runtime/'downloads/node.zip',report,cancel,item['sha256'])
        unpack(archive,runtime)
        if not usable_node(node):raise RuntimeError('Не удалось подготовить загрузку с YouTube. Нажми «Повторить».')
    for index,item in enumerate(manifest['models']):
        stage(3,'Загружаю модели · '+str(index+1)+' / '+str(len(manifest['models'])))
        target=root/item['path']
        report(detail=['Отделение вокала от музыки','Ведущий и фоновый вокал','Текст и время слов'][index])
        download(item['url'],target,report,cancel,item['sha256'])
    stage(4,'Проверяю готовность')
    check_cancel(cancel)
    (runtime/'installed.json').write_text(json.dumps({'python':str(python),'requirements':sha256(root/'requirements.txt')},ensure_ascii=False),encoding='utf-8')
    return python


def usable_node(path):
    if not Path(path).is_file():return False
    try:
        result=subprocess.run([str(path),'--version'],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,text=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
        return result.returncode==0 and result.stdout.strip()=='v22.23.3'
    except (OSError,subprocess.TimeoutExpired):return False


@contextmanager
def setup_lock(root, report, cancel):
    # A second launch waits instead of changing the same environment concurrently.
    import msvcrt
    root=Path(root).resolve();cancel=cancel or threading.Event()
    (root/'.runtime').mkdir(exist_ok=True)
    with (root/'.runtime/install.lock').open('a+b') as lock:
        lock.seek(0);lock.write(b'0');lock.flush()
        while True:
            check_cancel(cancel);lock.seek(0)
            try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);break
            except OSError:
                report(stage=1,title='Ожидаю завершения другой установки',detail='Окно можно закрыть.',done=None,total=None)
                cancel.wait(.5)
        try:yield
        finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)


def install(root, report=lambda **state:None, cancel=None, force=False):
    cancel=cancel or threading.Event()
    with setup_lock(root,report,cancel):return _install(root,report,cancel,force)


def native_setup(root,operation=None):
    """Native progress window works even before WebView2 or backend Python is installed."""
    import clr
    clr.AddReference('System.Windows.Forms');clr.AddReference('System.Drawing')
    from System import Action
    from System.Drawing import Color,Font,FontStyle,Point,Size,Icon
    from System.Threading import Thread,ThreadStart,ApartmentState
    from System.Windows.Forms import Form,Label,Button,ProgressBar,ProgressBarStyle,Application,FormStartPosition,Timer
    result=[];cancel=threading.Event();workers=[]
    def show():
        form=Form();form.Text='Своя версия · подготовка';form.ClientSize=Size(740,450);form.StartPosition=FormStartPosition.CenterScreen
        form.BackColor=Color.FromArgb(23,33,39);form.ForeColor=Color.FromArgb(237,244,236)
        form.MaximizeBox=False
        if (Path(root)/'app.ico').exists():form.Icon=Icon(str(Path(root)/'app.ico'))
        def label(text,x,y,width,height,size=12,bold=False):
            control=Label();control.Text=text;control.Location=Point(x,y);control.Size=Size(width,height)
            control.Font=Font('Segoe UI',size,FontStyle.Bold if bold else FontStyle.Regular);form.Controls.Add(control);return control
        label('СВОЯ ВЕРСИЯ.',36,30,660,60,28,True)
        title=label('Готовлю программу к запуску',40,112,660,40,16,True)
        detail=label('Проверяю установленные компоненты…',40,165,660,65)
        progress=ProgressBar();progress.Location=Point(40,242);progress.Size=Size(660,12);progress.Style=ProgressBarStyle.Marquee;form.Controls.Add(progress)
        amount=label('Первый запуск требует интернета. Следующие — работают локально.',40,270,660,46,10)
        label('Можно закрыть окно и продолжить позже. Загрузка сохранится.',40,385,660,40,10)
        retry=Button();retry.Text='Повторить';retry.Location=Point(40,330);retry.Size=Size(160,36);retry.Visible=False;form.Controls.Add(retry)
        journal=Button();journal.Text='Журнал';journal.Location=Point(215,330);journal.Size=Size(120,36);journal.Visible=False;form.Controls.Add(journal)
        close=Button();close.Text='Закрыть';close.Location=Point(560,330);close.Size=Size(140,36);form.Controls.Add(close)
        closed=False;busy=False;force=False;started=time.monotonic();known=False
        def update(**state):
            if closed:return
            def paint():
                nonlocal known
                if 'title' in state:title.Text=str(state.get('stage',''))+' / 4 · '+state['title']
                if 'detail' in state:detail.Text=state['detail']
                if 'done' in state:
                    known=state.get('total') is not None
                    progress.Style=ProgressBarStyle.Continuous if known else ProgressBarStyle.Marquee
                    if known:
                        done,total=state['done'],state['total'];progress.Value=min(100,int(done/max(total,1)*100))
                        amount.Text=f'{done/1048576:.1f} / {total/1048576:.1f} МБ · {progress.Value}%'
            if form.IsHandleCreated and not form.IsDisposed:form.BeginInvoke(Action(paint))
        timer=Timer();timer.Interval=1000
        def tick(sender,args):
            if busy and not known:amount.Text='Идёт подготовка · '+str(int((time.monotonic()-started)//60))+':'+str(int(time.monotonic()-started)%60).zfill(2)
        timer.Tick+=tick;timer.Start()
        def worker():
            nonlocal busy,force
            try:
                if operation is not None:
                    python=operation(root,update,cancel)
                else:
                    python=install(root,update,cancel,force)
                    # Install the official, signed WebView2 runtime only when it is missing.
                    with setup_lock(root,update,cancel):
                        from webview.platforms import edgechromium
                        from Microsoft.Web.WebView2.Core import CoreWebView2Environment
                        try:engine=CoreWebView2Environment.GetAvailableBrowserVersionString()
                        except Exception:engine=None
                        if not engine:
                            update(stage=4,title='Подготавливаю окно программы',detail='Скачиваю Microsoft WebView2',done=None,total=None)
                            setup=download('https://go.microsoft.com/fwlink/p/?LinkId=2124703',Path(root)/'.runtime/downloads/webview2.exe',update,cancel)
                            validate_signed_installer(setup,root,update,cancel)
                            run([setup,'/silent','/install'],root,update,cancel,'Встроенное окно Microsoft')
                            CoreWebView2Environment.GetAvailableBrowserVersionString()
                result.append(python)
                if not closed:form.BeginInvoke(Action(lambda:form.Close()))
            except InterruptedError:pass
            except Exception as exc:
                message=str(exc)
                import traceback
                with (Path(root)/'.runtime/install.log').open('a',encoding='utf-8') as output:output.write(traceback.format_exc()+'\n')
                if isinstance(exc,(TimeoutError,ConnectionError)) or 'urlopen error' in message:
                    message='Связь с сервером загрузки прервалась. Проверь интернет и нажми «Повторить»: готовые компоненты сохранены.'
                elif 'HTTP Error' in message:
                    message='Сервер загрузки сейчас не отдал компонент. Нажми «Повторить» позже. Подробности — в журнале.'
                def failed():
                    nonlocal busy,force
                    busy=False;force='восстановления' in message
                    title.Text='Не получилось завершить подготовку';detail.Text=message
                    progress.Style=ProgressBarStyle.Continuous;progress.Value=0
                    amount.Text='Готовые компоненты сохранены. Повтори установку после устранения причины.'
                    retry.Visible=journal.Visible=True
                if not closed:form.BeginInvoke(Action(failed))
        def start(sender=None,args=None):
            nonlocal busy,started
            if busy:return
            busy=True;started=time.monotonic();retry.Visible=journal.Visible=False
            job=threading.Thread(target=worker,daemon=True);workers.append(job);job.start()
        def closing(sender,args):
            nonlocal closed
            closed=True;cancel.set();timer.Stop()
        form.FormClosing+=closing;form.Shown+=start;retry.Click+=start
        close.Click+=lambda sender,args:form.Close()
        journal.Click+=lambda sender,args:subprocess.Popen(['notepad.exe',str(Path(root)/'.runtime/install.log')])
        Application.Run(form)
    thread=Thread(ThreadStart(show));thread.SetApartmentState(ApartmentState.STA);thread.Start();thread.Join()
    for job in workers:job.join()
    return result[0] if result else None


def validate_signed_installer(path,root,report,cancel):
    # Signature and chain must be valid before executing a downloaded Microsoft installer.
    literal=str(Path(path).resolve()).replace("'","''")
    command="$s=Get-AuthenticodeSignature -LiteralPath '"+literal+"'; if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {exit 1}"
    encoded=base64.b64encode(command.encode('utf-16-le')).decode('ascii')
    run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded],root,report,cancel,'Проверка Microsoft WebView2')
