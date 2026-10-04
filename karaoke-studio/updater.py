"""GitHub Releases updates. User audio/runtime are never part of the transaction."""
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import re
import shutil
import subprocess
import sys
import threading
import time
from urllib.request import Request,urlopen
from zipfile import ZipFile
from runtime import BACKEND_VERSION
from installer import download,setup_lock


def repository(root):
    config=json.loads((Path(root)/'update-config.json').read_text(encoding='utf-8'))
    repo=config.get('repository')
    if not isinstance(repo,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise ValueError('Репозиторий обновлений не настроен')
    return repo


def read_json(url):
    request=Request(url,headers={'User-Agent':'Local-Vocal-Updater','Accept':'application/vnd.github+json'})
    with urlopen(request,timeout=15) as response:data=response.read(1024*1024+1)
    if len(data)>1024*1024:raise ValueError('Слишком большой файл описания обновления')
    return json.loads(data)


def allowed_file(name):
    path=PurePosixPath(name)
    if '\\' in name or ':' in name or path.is_absolute() or '..' in path.parts:return False
    if len(path.parts)==1:
        return not name.startswith('.') and (name=='SvoyaVersiya.exe' or path.suffix.lower() in {'.py','.js','.json','.html','.css','.md','.txt','.bat','.ico'})
    return name in {'vendor/three.module.min.js','vendor/three.LICENSE.txt','models/vocal-effects.npz','models/vocal-effects.json','models/download_checks.json','models/mdx_model_data.json','models/vr_model_data.json'}


def validate_manifest(manifest):
    if not isinstance(manifest,dict) or manifest.get('schema')!=1:raise ValueError('Неизвестный формат обновления')
    version=manifest.get('version');size=manifest.get('bytes');files=manifest.get('files')
    if type(version)!=int or not 1<=version<1000000 or type(size)!=int or not 0<size<=100*1024*1024:raise ValueError('Неверная версия или размер обновления')
    if not isinstance(manifest.get('asset'),str) or not re.fullmatch(r'[A-Za-z0-9_.-]+\.zip',manifest['asset']):raise ValueError('Неверное имя архива')
    if not re.fullmatch('[a-f0-9]{64}',str(manifest.get('sha256',''))):raise ValueError('Нет контрольной суммы обновления')
    if not isinstance(files,dict) or not 1<=len(files)<=200 or not {'SvoyaVersiya.exe','runtime.py','desktop.py','app.py'}<=files.keys():raise ValueError('Неполное обновление')
    seen=set();total=0
    for name,record in files.items():
        if not isinstance(name,str) or not allowed_file(name) or name.casefold() in seen:raise ValueError('Недопустимый путь в обновлении')
        seen.add(name.casefold())
        if not isinstance(record,dict) or type(record.get('bytes'))!=int or not 0<=record['bytes']<=100*1024*1024 or not re.fullmatch('[a-f0-9]{64}',str(record.get('sha256',''))):raise ValueError('Неверная контрольная сумма файла')
        total+=record['bytes']
    if total>200*1024*1024:raise ValueError('Распакованное обновление слишком велико')
    return manifest


def destination(root,name):
    root=Path(root).resolve();target=root/name
    if not target.resolve().is_relative_to(root) or target.is_symlink():raise ValueError('Папка обновления содержит ссылку за пределы программы')
    return target


def stage_archive(root,archive,manifest):
    manifest=validate_manifest(manifest);root=Path(root).resolve()
    staging=destination(root,f'.runtime/updates/v{manifest["version"]}/staged');staging.mkdir(parents=True,exist_ok=True)
    if Path(archive).stat().st_size!=manifest['bytes'] or hashlib.sha256(Path(archive).read_bytes()).hexdigest()!=manifest['sha256']:raise ValueError('Контрольная сумма архива не совпала')
    expected={'karaoke-studio/'+name:name for name in manifest['files']}
    with ZipFile(archive) as bundle:
        names=bundle.namelist()
        if len(names)!=len(set(names)) or set(names)!=set(expected):raise ValueError('Содержимое архива не соответствует описанию')
        for member,name in expected.items():
            info=bundle.getinfo(member);record=manifest['files'][name]
            if info.file_size!=record['bytes'] or (info.external_attr>>16)&0o170000==0o120000:raise ValueError('Недопустимый файл в архиве')
            data=bundle.read(member)
            if hashlib.sha256(data).hexdigest()!=record['sha256']:raise ValueError('Повреждён файл обновления: '+name)
            target=destination(staging,name);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    version=re.search(r'^BACKEND_VERSION\s*=\s*(\d+)\s*$',(staging/'runtime.py').read_text(encoding='utf-8'),re.M)
    if version is None or int(version[1])!=manifest['version']:raise ValueError('Версия программы не совпала с описанием')
    plan=destination(root,'.runtime/pending-update.json');temp=plan.with_suffix('.tmp')
    temp.write_text(json.dumps(manifest),encoding='utf-8');temp.replace(plan)
    return staging


def apply_staged(root,report=lambda **state:None,cancel=None):
    root=Path(root).resolve();cancel=cancel or threading.Event()
    with setup_lock(root,report,cancel):
        manifest=validate_manifest(json.loads((root/'.runtime/pending-update.json').read_text(encoding='utf-8')))
        stage=destination(root,f'.runtime/updates/v{manifest["version"]}/staged')
        backup=destination(root,f'.runtime/updates/v{manifest["version"]}/backup');backup.mkdir(parents=True,exist_ok=True)
        names=list(manifest['files']);names.remove('SvoyaVersiya.exe');names.insert(0,'SvoyaVersiya.exe')
        names=[name for name in names if name!='update-config.json']
        for name in names:
            source=destination(stage,name);record=manifest['files'][name]
            if not source.is_file() or source.stat().st_size!=record['bytes'] or hashlib.sha256(source.read_bytes()).hexdigest()!=record['sha256']:raise ValueError('Подготовленное обновление повреждено')
            target=destination(root,name)
            if target.exists():
                saved=destination(backup,name);saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
        changed=[]
        report(stage=2,title='Устанавливаю новую версию',detail='Песни, записи и скачанные модели сохраняются.',done=0,total=len(names))
        try:
            for index,name in enumerate(names):
                if not changed and cancel.is_set():raise InterruptedError('Обновление отменено')
                target=destination(root,name);target.parent.mkdir(parents=True,exist_ok=True)
                temp=target.with_name(target.name+'.update-tmp');shutil.copy2(destination(stage,name),temp)
                # The EXE is first: a still-open window fails before other files change.
                for attempt in range(60):
                    try:temp.replace(target);break
                    except PermissionError:
                        if attempt==59:raise ValueError('Закрой все окна студии и повтори обновление')
                        time.sleep(.5)
                changed.append(name);report(done=index+1,total=len(names))
        except Exception:
            for name in reversed(changed):
                target=destination(root,name);saved=destination(backup,name)
                if saved.exists():
                    temp=target.with_name(target.name+'.rollback-tmp');shutil.copy2(saved,temp);temp.replace(target)
                else:target.unlink(missing_ok=True)
            raise
        (root/'.runtime/pending-update.json').unlink()
        (root/'.runtime/update-result.json').write_text(json.dumps({'version':manifest['version'],'state':'installed'}),encoding='utf-8')
        return root/'SvoyaVersiya.exe'


class Updates:
    def __init__(self,root):
        self.root=Path(root);self.lock=threading.Lock();self.state={'state':'idle','current':BACKEND_VERSION};self.manifest=None;self.asset=None
        pending=self.root/'.runtime/pending-update.json'
        if pending.exists():
            try:
                manifest=validate_manifest(json.loads(pending.read_text(encoding='utf-8')))
                if manifest['version']>BACKEND_VERSION:self.state.update(state='prepared',latest=manifest['version'])
            except (ValueError,OSError):self.state.update(state='error',error='Подготовленное обновление повреждено. Проверь обновления ещё раз.')
    def snapshot(self):
        with self.lock:return dict(self.state)
    def report(self,**state):
        with self.lock:self.state.update(state)
    def start(self,action):
        with self.lock:
            if self.state['state'] in {'checking','downloading'}:raise ValueError('Обновление уже проверяется или скачивается')
            if action=='download' and self.manifest is None:raise ValueError('Сначала проверь обновления')
            self.state.update(state='checking' if action=='check' else 'downloading',error=None,done=0,total=None)
        threading.Thread(target=self.run,args=(action,),daemon=True).start()
    def run(self,action):
        try:
            if action=='check':
                repo=repository(self.root);release=read_json('https://api.github.com/repos/'+repo+'/releases/latest')
                if release.get('draft') or release.get('prerelease'):raise ValueError('Релиз ещё не опубликован')
                assets={a['name']:a for a in release.get('assets',[])}
                def url(name):
                    value=assets.get(name,{}).get('browser_download_url','')
                    if not value.startswith('https://github.com/'+repo+'/releases/download/'):raise ValueError('Файл обновления не принадлежит выбранному репозиторию')
                    return value
                manifest=validate_manifest(read_json(url('update-manifest.json')))
                if manifest['version']<=BACKEND_VERSION:self.report(state='current',latest=manifest['version']);return
                asset=url(manifest['asset'])
                if assets[manifest['asset']].get('size')!=manifest['bytes']:raise ValueError('Размер релиза не совпал')
                self.manifest=manifest;self.asset=asset
                self.report(state='available',latest=manifest['version'],total=manifest['bytes'],release_url=release.get('html_url'),notes=str(release.get('body',''))[:4000])
            else:
                manifest=self.manifest;archive=destination(self.root,f'.runtime/updates/v{manifest["version"]}/'+manifest['asset'])
                download(self.asset,archive,self.report,threading.Event(),manifest['sha256'])
                stage_archive(self.root,archive,manifest);self.report(state='prepared',latest=manifest['version'],done=manifest['bytes'],total=manifest['bytes'])
        except Exception as exc:self.report(state='error',error='Не удалось обновить программу: '+str(exc)[-600:])


if __name__=='__main__':
    from installer import native_setup
    root=Path(sys.argv[1]).resolve()
    executable=native_setup(root,operation=apply_staged)
    if executable:subprocess.Popen([str(executable)],cwd=root,creationflags=subprocess.CREATE_NO_WINDOW)
