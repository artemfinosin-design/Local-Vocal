"""Local-only karaoke server. Run with python app.py."""

import json
import copy
import math
import shutil
import subprocess
import sys
import threading
import uuid
import wave
import webbrowser
import hashlib
import tempfile
from datetime import datetime, timezone
from voice import calibrate, tuning_options, TUNE_PRESETS
from feedback import make_bundle, selected_takes
import personalization
from updater import Updates
import numpy as np
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from audio_core import analyze, markers, mix, read_wav, read_reference, role_guide, save_meta, write_wav
from runtime import ffmpeg_path, BACKEND_VERSION
from lyrics import guess_title, lookup
from effects import train as train_effects, REPORT, analyze_effects, SPACE_MODES

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
DATA.mkdir(exist_ok=True)
MAX_UPLOAD = 150 * 1024 * 1024
MAX_DURATION = 10 * 60
ALLOWED = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}
jobs = {}
lock = threading.Lock()
processing_lock = threading.Lock()
learning = {'state': 'idle'}
active_posts = 0
stopping = False
updates=Updates(HERE)
EXAMPLES = DATA / 'effect-examples'


def voice_profile():
    path = DATA / 'voice-profile.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def effect_examples():
    with lock:
        project_sources = [DATA / job_id / 'vocals.wav' for job_id, job in jobs.items()
                           if job.get('state') == 'ready' and not job.get('diagnostic_copy_of')]
    return sorted(set(EXAMPLES.glob('*.wav')) | {path for path in project_sources if path.exists()})


def learn_effects():
    try:
        while True:
            with lock:
                learning['pending'] = False
            with processing_lock:
                def update(message):
                    with lock:
                        learning.update(message=message)
                report = train_effects(effect_examples(), update)
            with lock:
                if learning.get('pending'):
                    continue
                learning.update(state='ready', report=report, message='Обучение завершено')
                break
    except Exception as exc:
        with lock:
            learning.update(state='error', message=str(exc)[-1000:])


def save_job(job_id, touch=True):
    folder = DATA / job_id
    saved=folder/'project.json'
    if touch or 'updated_at' not in jobs[job_id]:
        timestamp=datetime.now(timezone.utc).timestamp() if touch or not saved.exists() else saved.stat().st_mtime
        jobs[job_id]['updated_at']=timestamp
    pending = folder / "project.tmp"
    pending.write_text(json.dumps(jobs[job_id], ensure_ascii=False), encoding="utf-8")
    pending.replace(folder / "project.json")


def restore_jobs():
    outdated = []
    for saved in DATA.glob("*/project.json"):
        folder = saved.parent
        if len(folder.name) != 32 or not all(c in "0123456789abcdef" for c in folder.name):
            continue
        try:
            job = json.loads(saved.read_text(encoding="utf-8"))
            if job.get("state") == "ready" and all((folder / (name + ".wav")).is_file()
                                                    for name in ("vocals", "instrumental")):
                if job.get("version", 1) < 2:
                    meta = analyze(read_wav(folder / "vocals.wav"))
                    save_meta(folder / "analysis.json", meta)
                    job["roles"] = [{key: value for key, value in role.items() if key != "mask"}
                                    for role in meta["roles"]]
                    job["markers"] = markers(meta)
                    job["version"] = 2
                    for track in job.get("tracks", []):
                        track["role"] = "lead"
                meta = json.loads((folder / "analysis.json").read_text(encoding="utf-8"))
                if meta.get('effect_version', 0) < 2:
                    backup = folder / 'analysis-effects-v1-backup.json'
                    if not backup.exists(): shutil.copy2(folder / 'analysis.json', backup)
                    for name, profile in meta['profiles'].items():
                        blocks = analyze_effects(read_wav(folder / (name + '.wav')))
                        profile['effects'] = blocks
                        profile['echo'] = [bool(blocks[min(int(i * profile['hop'] / 4), len(blocks)-1)]['delay_wet']) for i in range(len(profile['rms']))]
                        profile['echo_delay'] = next((b['delay'] for b in blocks if b['delay_wet']), 0)
                    meta['effect_version'] = 2
                    save_meta(folder / 'analysis.json', meta)
                    job['markers'] = markers(meta)
                if not job.get('song_info'):
                    original = next(folder.glob('upload.*'), None)
                    if original:
                        job['song_info'] = song_info(original, job.get('filename', ''))
                save_guides(folder, meta)
                jobs[folder.name] = job
                save_job(folder.name,touch=False)
                if (job.get('version', 2) < 3 or meta.get('version', 0) < 12) and all((folder / (name + '.wav')).is_file() for name in ('lead','backing')):
                    outdated.append(folder.name)
        except (OSError, ValueError, TypeError):
            continue
    for job_id in outdated:
        jobs[job_id]['analysis_state'] = 'processing'
        threading.Thread(target=refresh_analysis, args=(job_id,), daemon=True).start()


def save_guides(folder, meta, force=False):
    for role in meta["roles"]:
        guide = folder / ("guide-" + role["id"] + ".wav")
        if force or not guide.exists():
            source = read_reference(folder, role["reference"])
            write_wav(guide, role_guide(source, role, meta["hop"]))


def command(*args):
    run = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace")
    if run.returncode:
        raise RuntimeError(run.stdout[-1800:])


def convert(source, destination, channels, max_duration=MAX_DURATION):
    command(ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-t", str(max_duration + 0.25),
            "-ar", "44100", "-ac", str(channels), "-c:a", "pcm_s16le", str(destination))
    with wave.open(str(destination), "rb") as wav:
        if not 0 < wav.getnframes() / wav.getframerate() <= max_duration:
            raise ValueError(f"Аудио должно быть короче {max_duration} секунд")


def song_info(source, filename):
    info = guess_title(filename)
    run = subprocess.run([ffmpeg_path(), '-hide_banner','-loglevel','error','-i',str(source),'-f','ffmetadata','-'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace')
    for line in run.stdout.splitlines():
        key, separator, value = line.partition('=')
        if separator and key.lower() in {'artist','title'} and 0 < len(value) <= 200:
            info[key.lower()] = value.replace('\\=', '=').strip()
    return info


def prepare(job_id, uploaded, filename=""):
    folder = DATA / job_id
    try:
        with lock:
            jobs[job_id]["state"] = "Преобразую файл"
        convert(uploaded, folder / "song.wav", 2)
        with lock:
            jobs[job_id]["state"] = "Разделяю вокал и музыку — это может занять несколько минут"
        with processing_lock:
            command(sys.executable, str(HERE / "separate_audio.py"), str(folder / "song.wav"),
                    str(folder), str(HERE / "models"))
        with lock:
            jobs[job_id]["state"] = "Размечаю партии и обработку голоса"
        meta = analyze(read_wav(folder / "lead.wav"), read_wav(folder / "backing.wav"), read_wav(folder / "vocals.wav"))
        if not meta["roles"]:
            raise ValueError("В этой песне не удалось обнаружить вокальную партию")
        save_meta(folder / "analysis.json", meta)
        save_guides(folder, meta)
        with lock:
            jobs[job_id] = {"state": "ready", "markers": markers(meta),
                            "duration": round(len(read_wav(folder / "instrumental.wav")) / 44100, 1),
                            "roles": [{key: value for key, value in role.items() if key != "mask"}
                                      for role in meta["roles"]],
                            "version": 3, "filename": filename, "song_info": song_info(uploaded, filename),
                            "tracks": [], "renders": []}
            save_job(job_id)
            start_learning = learning['state'] != 'processing'
            if start_learning:
                learning.update(state='processing', message='Учусь на вокале новой песни')
            else:
                learning['pending'] = True
        if start_learning:
            threading.Thread(target=learn_effects, daemon=True).start()
    except Exception as exc:
        with lock:
            jobs[job_id] = {"state": "error", "error": str(exc)[-1800:]}


def public_roles(meta):
    return [{key: value for key, value in role.items() if key != 'mask'} for role in meta['roles']]


def replace_separation(folder):
    """Finish inference before replacing anything; retain a recoverable stem snapshot."""
    names=('vocals','instrumental','lead','backing')
    with tempfile.TemporaryDirectory(prefix='separation-pending-',dir=folder) as pending:
        stage=Path(pending)
        command(sys.executable,str(HERE/'separate_audio.py'),str(folder/'song.wav'),str(stage),str(HERE/'models'))
        for name in names:
            audio=read_wav(stage/(name+'.wav'))
            if not len(audio) or not np.isfinite(audio).all():raise ValueError('Разделение вернуло пустую дорожку')
        # Validate analysis before touching the previous source stems.
        meta=analyze(read_wav(stage/'lead.wav'),read_wav(stage/'backing.wav'),read_wav(stage/'vocals.wav'))
        if not meta['roles']:raise ValueError('В новом разделении не найден вокал; прежние дорожки сохранены')
        backup=folder/('separation-backup-'+uuid.uuid4().hex);backup.mkdir()
        files=[folder/(name+'.wav') for name in names]+[folder/'analysis.json',folder/'project.json',folder/'separation.json']+list(folder.glob('guide-*.wav'))
        for path in files:
            if path.exists():shutil.copy2(path,backup/path.name)
        try:
            for name in names:shutil.copy2(stage/(name+'.wav'),folder/(name+'.wav'))
            shutil.copy2(stage/'separation.json',folder/'separation.json')
        except Exception:
            for path in backup.iterdir():shutil.copy2(path,folder/path.name)
            raise
        return backup,meta


def refresh_analysis(job_id, separate_again=False):
    folder = DATA / job_id
    backup=None
    with lock:previous_job=copy.deepcopy(jobs[job_id])
    with processing_lock:
        try:
            old = json.loads((folder / 'analysis.json').read_text(encoding='utf-8'))
            if separate_again:backup,meta=replace_separation(folder)
            else:meta = analyze(read_wav(folder / 'lead.wav'), read_wav(folder / 'backing.wav'), read_wav(folder / 'vocals.wav'))
            if not meta['roles']:
                raise ValueError('Новых вокальных фрагментов не найдено; прежняя разметка сохранена')
            previous={event['id']:event.get('status','pending') for event in old.get('effect_proposals',[])}
            for event in meta.get('effect_proposals',[]):event['status']=previous.get(event['id'],'pending')
            recorded = {track['role'] for track in jobs[job_id]['tracks']}
            current = {role['id'] for role in meta['roles']}
            for role in old['roles']:
                if role['id'] in recorded and role['id'] not in current:
                    preserved = dict(role)
                    if role['id'] == 'artist2': preserved['name'] = 'Сохранённая отдельная партия'
                    meta['roles'].append(preserved)
                    meta['profiles'][role['reference']] = old['profiles'][role['reference']]
                else:
                    matching = next((r for r in meta['roles'] if r['id'] == role['id']), None)
                    if matching and role.get('excluded'):
                        matching['excluded'] = role['excluded']
            shutil.copy2(folder / 'analysis.json', folder / ('analysis-backup-' + uuid.uuid4().hex + '.json'))
            save_guides(folder, meta, force=True)
            with lock:
                save_meta(folder / 'analysis.json', meta)
                jobs[job_id].update(roles=public_roles(meta), markers=markers(meta), version=3, analysis_state='ready')
                save_job(job_id)
        except Exception as exc:
            if backup:
                for path in backup.iterdir():shutil.copy2(path,folder/path.name)
            with lock:
                if backup:jobs[job_id]=previous_job
                jobs[job_id]['analysis_state'] = 'error'
                jobs[job_id]['analysis_error'] = str(exc)[-1000:]
                save_job(job_id)


def synchronize_lyrics(job_id, request_file):
    folder = DATA / job_id
    try:
        with processing_lock:
            command(sys.executable, str(HERE / 'lyrics_worker.py'), str(folder), str(HERE / 'models'), str(request_file))
        result = json.loads((folder / 'lyrics.json').read_text(encoding='utf-8'))
        with lock:
            jobs[job_id].update(lyrics=result, lyrics_state='ready')
            save_job(job_id)
    except Exception as exc:
        with lock:
            jobs[job_id].update(lyrics_state='error', lyrics_error=str(exc)[-1000:])


class Handler(BaseHTTPRequestHandler):
    def local_request(self):
        host = self.headers.get("Host", "").lower()
        port = self.server.server_port
        origin = self.headers.get("Origin")
        if host not in {f"127.0.0.1:{port}", f"localhost:{port}"} or (origin and origin != "http://" + host):
            self.close_connection = True
            self.reply(403, {"error": "Откройте студию по её локальному адресу"})
            return False
        return True

    def log_message(self, format, *args):
        if not self.path.startswith("/api/job"):
            super().log_message(format, *args)

    def reply(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, content_type):
        size = path.stat().st_size
        start, end = 0, size - 1
        header = self.headers.get("Range", "")
        if header:
            if not header.startswith("bytes=") or "," in header:
                return self.reply(400, {"error": "Неверный диапазон файла"})
            bounds = header[6:].split("-", 1)
            try:
                if len(bounds) != 2 or not any(bounds):
                    raise ValueError("Missing range bounds")
                start = int(bounds[0]) if bounds[0] else max(0, size - int(bounds[1]))
                end = int(bounds[1]) if bounds[0] and bounds[1] else size - 1
            except ValueError:
                return self.reply(400, {"error": "Неверный диапазон файла"})
            if start < 0 or start >= size or end < start:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            end = min(end, size - 1)
        self.send_response(206 if header else 200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        if header:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with path.open("rb") as source:
            source.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                    return  # Audio seeking intentionally cancels the previous range request.
                remaining -= len(chunk)

    def request_body(self, limit=MAX_UPLOAD):
        try:
            size = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            size = -1
        if size < 0 or size > limit:
            raise ValueError("Слишком большой файл или неизвестный размер")
        body = self.rfile.read(size)
        if len(body) != size:
            raise ValueError("Загрузка прервалась")
        return body

    def project(self, query):
        job_id = query.get("id", [""])[0]
        if len(job_id) != 32 or not all(c in "0123456789abcdef" for c in job_id):
            raise ValueError("Неверный номер проекта")
        with lock:
            job = jobs.get(job_id)
        if not job:
            raise ValueError("Проект не найден")
        return job_id, job, DATA / job_id

    def do_GET(self):
        if not self.local_request():
            return
        parsed = urlparse(self.path)
        try:
            static = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8"),
                      **{path: (path[1:], "text/javascript; charset=utf-8") for path in
                         ("/app.js", "/session.js", "/editor.js", "/model-ui.js", "/voice-ui.js", "/tuning-ui.js", "/updates-ui.js", "/history-ui.js", "/effect-ui.js", "/visuals.js", "/headphones.js", "/vendor/three.module.min.js")}}
            if parsed.path in static:
                filename, content_type = static[parsed.path]
                return self.send_file(HERE / filename, content_type)
            query = parse_qs(parsed.query)
            if parsed.path == '/api/history':
                with lock:
                    songs=[dict(id=identity,filename=job.get('filename') or 'Без названия',duration=job.get('duration',0),updated_at=job.get('updated_at',0),takes=len(job.get('tracks',[])),render=job.get('renders',[])[-1] if job.get('renders') else None) for identity,job in jobs.items() if job.get('state')=='ready' and (job.get('tracks') or job.get('renders'))]
                trash=[]
                for saved in (DATA/'.trash').glob('*/project.json'):
                    identity=saved.parent.name
                    if len(identity)!=32 or any(c not in '0123456789abcdef' for c in identity):continue
                    try:
                        job=json.loads(saved.read_text(encoding='utf-8'))
                        trash.append(dict(id=identity,filename=job.get('filename') or 'Без названия'))
                    except (OSError,ValueError):continue
                return self.reply(200,dict(songs=sorted(songs,key=lambda song:song['updated_at'],reverse=True),trash=trash))
            if parsed.path == '/api/tune-presets':
                return self.reply(200,{'presets':TUNE_PRESETS})
            if parsed.path == '/api/update-status':
                return self.reply(200,updates.snapshot())
            if parsed.path == '/api/personal-profile':
                with lock:profile=personalization.summarize(personalization.load(DATA))
                return self.reply(200,profile)
            if parsed.path == '/api/personal-profile-export':
                job=self.project(query)[1] if query.get('id') else None
                with lock:
                    personal=personalization.load(DATA)
                    report={'schema':1,'app_version':BACKEND_VERSION,'personal_profile':personal,'audio_included':False}
                    if job is not None:
                        report['processing_log']={'renders':job.get('render_diagnostics',{}),'ratings':job.get('render_ratings',{})}
                return self.reply(200,report)
            if parsed.path == '/api/health':
                return self.reply(200, {'app':'sv-local-vocal-studio',
                    'version':BACKEND_VERSION, 'folder':hashlib.sha256(str(HERE.resolve()).casefold().encode()).hexdigest()})
            if parsed.path == '/api/voice-profile':
                with lock:
                    profile = voice_profile()
                return self.reply(200, {'profile': profile})
            if parsed.path == '/api/feedback-file':
                _, job, folder = self.project(query)
                identity = query.get('bundle', [''])[0]
                if identity not in job.get('feedback_exports', []) or len(identity) != 32 or any(c not in '0123456789abcdef' for c in identity):
                    raise ValueError('Архив не найден')
                return self.send_file(folder / ('feedback-' + identity + '.zip'), 'application/zip')
            if parsed.path == '/api/effects-model':
                with lock:
                    payload = dict(learning)
                if 'report' not in payload and REPORT.exists():
                    payload['report'] = json.loads(REPORT.read_text(encoding='utf-8'))
                payload['examples'] = len(effect_examples())
                return self.reply(200, payload)
            if parsed.path == '/api/effect-proposals':
                _,job,folder=self.project(query)
                if job['state']!='ready' or job.get('analysis_state')=='processing':raise ValueError('Дождись анализа')
                meta=json.loads((folder/'analysis.json').read_text(encoding='utf-8'))
                keys=('id','type','start','end','reference','status','confidence','uncertain_middle')
                return self.reply(200,{'proposals':[{key:event[key] for key in keys if key in event} for event in meta.get('effect_proposals',[])]})
            if parsed.path == "/api/job":
                _, job, _ = self.project(query)
                return self.reply(200, job)
            if parsed.path == '/api/waveform':
                _, job, folder = self.project(query)
                role = query.get('role', [''])[0]
                if job['state'] != 'ready' or role not in {item['id'] for item in job['roles']}:
                    raise ValueError('Партия пока недоступна')
                voice = read_wav(folder / ('guide-' + role + '.wav'))
                mono = np.max(np.abs(voice), axis=1) if voice.ndim == 2 else np.abs(voice)
                step = max(1, math.ceil(len(mono) / 2400))
                peaks = np.maximum.reduceat(mono, np.arange(0, len(mono), step))
                peaks /= max(float(np.max(peaks)), 1e-6)
                return self.reply(200, {'peaks': np.round(peaks, 4).tolist(), 'duration': job['duration']})
            if parsed.path == "/api/audio":
                _, job, folder = self.project(query)
                name = query.get("name", [""])[0]
                allowed = ({"song", "vocals", "instrumental", "lead", "backing"} | {"guide-" + role["id"] for role in job["roles"]} | {track["id"] for track in job["tracks"]} | set(job["renders"])) if job["state"] == "ready" else set()
                if name not in allowed:
                    raise ValueError("Аудио пока недоступно")
                path = folder / (name + ".wav")
                if not path.is_file():
                    raise ValueError("Файл не найден")
                return self.send_file(path, "audio/wav")
            self.reply(404, {"error": "Не найдено"})
        except ValueError as exc:
            self.reply(400, {"error": str(exc)})

    def do_POST(self):
        global active_posts
        is_shutdown = urlparse(self.path).path == '/api/shutdown'
        with lock:
            reject = stopping
            if not reject and not is_shutdown: active_posts += 1
        if reject: return self.reply(503, {'error': 'Студия завершает работу для обновления. Повтори запуск.'})
        try:
            return self.handle_post()
        finally:
            if not is_shutdown:
                with lock: active_posts -= 1

    def handle_post(self):
        global stopping
        if not self.local_request():
            return
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path in {'/api/history-delete','/api/history-restore'}:
                settings=json.loads(self.request_body(1000))
                identity=query.get('id',[''])[0]
                if not isinstance(settings,dict) or len(identity)!=32 or any(c not in '0123456789abcdef' for c in identity):raise ValueError('Неверный проект')
                trash=DATA/'.trash';trash.mkdir(exist_ok=True)
                if trash.is_symlink() or trash.resolve().parent!=DATA.resolve():raise ValueError('Некорректная папка корзины')
                live=DATA/identity;deleted=trash/identity
                with processing_lock,lock:
                    if active_posts>1:raise ValueError('Дождись завершения другого действия')
                    if parsed.path=='/api/history-delete':
                        job=jobs.get(identity)
                        if job is None:raise ValueError('Песня не найдена')
                        if job.get('state')!='ready' or job.get('analysis_state')=='processing' or job.get('lyrics_state')=='processing':raise ValueError('Дождись обработки песни')
                        if live.is_symlink() or live.resolve().parent!=DATA.resolve() or deleted.exists():raise ValueError('Папка проекта недоступна')
                        live.rename(deleted);jobs.pop(identity)
                    else:
                        if identity in jobs or live.exists() or deleted.is_symlink() or deleted.resolve().parent!=trash.resolve():raise ValueError('Папка проекта недоступна')
                        job=json.loads((deleted/'project.json').read_text(encoding='utf-8'))
                        if job.get('state')!='ready':raise ValueError('Нельзя восстановить этот проект')
                        deleted.rename(live);jobs[identity]=job
                return self.reply(200,{'ok':True})
            if parsed.path == '/api/shutdown':
                self.request_body(1000)
                with lock:
                    pending = active_posts > 0 or learning['state'] == 'processing' or any(job.get('state') not in {'ready','error'} or job.get('analysis_state') == 'processing' or job.get('lyrics_state') == 'processing' for job in jobs.values())
                    if not pending: stopping = True
                if pending: return self.reply(409, {'error': 'Дождись окончания обработки перед обновлением студии.'})
                self.reply(200, {'stopping': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if parsed.path in {'/api/update-check','/api/update-download'}:
                self.request_body(1000)
                updates.start('check' if parsed.path=='/api/update-check' else 'download')
                return self.reply(200,updates.snapshot())
            if parsed.path == '/api/personal-profile':
                settings=json.loads(self.request_body(1000))
                if not isinstance(settings,dict):raise ValueError('Неверные настройки профиля')
                with lock:
                    if settings.get('action')=='reset':
                        enabled=personalization.load(DATA)['enabled']
                        personal=dict(version=1,revision=0,enabled=enabled,observations=[],ratings=[],preferences=None)
                    elif settings.get('action')=='enabled' and isinstance(settings.get('enabled'),bool):
                        personal=personalization.load(DATA);personal['enabled']=settings['enabled']
                    else:raise ValueError('Неизвестное действие')
                    personalization.save(DATA,personal)
                return self.reply(200,personalization.summarize(personal))
            if parsed.path == '/api/render-rating':
                job_id,job,folder=self.project(query)
                settings=json.loads(self.request_body(1000))
                if not isinstance(settings,dict):raise ValueError('Неверная оценка')
                render_id=settings.get('render_id')
                with lock:
                    if render_id not in job.get('renders',[]) or render_id not in job.get('render_diagnostics',{}):raise ValueError('Сначала собери песню в новой версии')
                    personal=personalization.load(DATA)
                    personalization.rate(personal,job_id+':'+render_id,settings.get('rating'),settings.get('score'),settings.get('reasons'),job['render_diagnostics'][render_id].get('voices'))
                    personalization.save(DATA,personal)
                    job.setdefault('render_ratings',{})[render_id]=dict(personal['ratings'][-1]);save_job(job_id)
                return self.reply(200,personalization.summarize(personal))
            if parsed.path == '/api/voice-profile':
                settings = json.loads(self.request_body(1000))
                if not isinstance(settings, dict) or settings.get('action') != 'reset':
                    raise ValueError('Неизвестное действие')
                with lock:
                    (DATA / 'voice-profile.json').unlink(missing_ok=True)
                return self.reply(200, {'profile': None})
            if parsed.path == '/api/voice-check':
                body = self.request_body(4 * 1024 * 1024)
                if not body: raise ValueError('Пустая запись')
                with tempfile.TemporaryDirectory(prefix='voice-check-', dir=DATA) as temporary:
                    folder = Path(temporary)
                    source, decoded = folder / 'input.webm', folder / 'voice.wav'
                    source.write_bytes(body)
                    convert(source, decoded, 1, max_duration=25)
                    with processing_lock:
                        profile = calibrate(read_wav(decoded)[:, 0])
                profile['created'] = datetime.now(timezone.utc).isoformat()
                with lock:
                    pending = DATA / 'voice-profile.tmp'
                    pending.write_text(json.dumps(profile), encoding='utf-8')
                    pending.replace(DATA / 'voice-profile.json')
                return self.reply(200, {'profile': profile})
            if parsed.path == '/api/feedback':
                job_id, job, folder = self.project(query)
                if job['state'] != 'ready': raise ValueError('Дождись обработки песни')
                settings = json.loads(self.request_body(100000))
                with lock:
                    snapshot = json.loads(json.dumps(job))
                    profile = voice_profile()
                    personal=personalization.load(DATA)
                identity, target = make_bundle(folder, snapshot, settings, profile,personal)
                with lock:
                    jobs[job_id].setdefault('feedback_exports', []).append(identity)
                    save_job(job_id)
                return self.reply(200, {'url': f'/api/feedback-file?id={job_id}&bundle={identity}', 'bytes': target.stat().st_size})
            if parsed.path == '/api/effects-example':
                suffix = Path(query.get('filename', [''])[0]).suffix.lower()
                if suffix not in ALLOWED:
                    raise ValueError('Загрузи MP3, WAV, FLAC, M4A, OGG или AAC с вокалом')
                body = self.request_body()
                if not body:
                    raise ValueError('Пустой файл')
                with lock:
                    if learning['state'] == 'processing':
                        raise ValueError('Дождись завершения обучения')
                    learning.update(state='processing', message='Готовлю локальный пример')
                EXAMPLES.mkdir(exist_ok=True)
                example_id = uuid.uuid4().hex
                source = EXAMPLES / (example_id + suffix)
                destination = EXAMPLES / (example_id + '.wav')
                source.write_bytes(body)
                try:
                    # WAV uploads need a distinct source to avoid converting in place.
                    if source == destination:
                        source = source.with_suffix('.input.wav')
                        destination.rename(source)
                    convert(source, destination, 2)
                except Exception:
                    destination.unlink(missing_ok=True)
                    with lock:
                        learning.update(state='error', message='Не удалось прочитать пример')
                    raise
                finally:
                    source.unlink(missing_ok=True)
                threading.Thread(target=learn_effects, daemon=True).start()
                return self.reply(202, {'state':'processing'})
            if parsed.path == "/api/upload":
                filename = query.get("filename", [""])[0]
                suffix = Path(filename).suffix.lower()
                if suffix not in ALLOWED:
                    raise ValueError("Поддерживаются MP3, WAV, FLAC, M4A, OGG и AAC")
                body = self.request_body()
                if not body:
                    raise ValueError("Пустой файл")
                job_id = uuid.uuid4().hex
                folder = DATA / job_id
                folder.mkdir()
                source = folder / ("upload" + suffix)
                source.write_bytes(body)
                with lock:
                    jobs[job_id] = {"state": "В очереди"}
                threading.Thread(target=prepare, args=(job_id, source, filename), daemon=True).start()
                return self.reply(202, {"id": job_id})
            if parsed.path == "/api/track":
                job_id, job, folder = self.project(query)
                if job["state"] != "ready":
                    raise ValueError("Дождитесь обработки песни")
                if job.get('analysis_state') == 'processing':
                    raise ValueError('Дождись обновления разметки')
                body = self.request_body(80 * 1024 * 1024)
                role_id = query.get("role", [""])[0]
                role = next((role for role in job["roles"] if role["id"] == role_id), None)
                if role is None:
                    raise ValueError("Неизвестная партия")
                if not body:
                    raise ValueError("Пустая запись")
                start = float(query.get('start', ['0'])[0])
                end = float(query.get('end', [str(job['duration'])])[0])
                cue_start = float(query.get('cue_start', [str(start)])[0])
                cue_end = float(query.get('cue_end', [str(end)])[0])
                if not all(math.isfinite(x) for x in (start, end, cue_start, cue_end)) or not 0 <= start <= cue_start < cue_end <= end <= job['duration'] + 0.1:
                    raise ValueError('Неверные границы записи')
                track_id = uuid.uuid4().hex
                source = folder / (track_id + ".webm")
                source.write_bytes(body)
                convert(source, folder / (track_id + ".wav"), 1)
                source.unlink(missing_ok=True)
                with lock:
                    track = {"id": track_id, "role": role_id, 'start': start, 'end': end, 'region': [cue_start, cue_end]}
                    jobs[job_id]["tracks"].append(track)
                    save_job(job_id)
                return self.reply(200, track)
            if parsed.path == '/api/effect-decision':
                _,job,folder=self.project(query)
                if job['state']!='ready' or job.get('analysis_state')=='processing':raise ValueError('Дождись анализа')
                settings=json.loads(self.request_body(4096))
                if not isinstance(settings,dict) or settings.get('status') not in ('pending','approved','rejected'):raise ValueError('Некорректное решение')
                with processing_lock:
                    if job['state']!='ready' or job.get('analysis_state')=='processing':raise ValueError('Дождись анализа')
                    meta=json.loads((folder/'analysis.json').read_text(encoding='utf-8'))
                    event=next((item for item in meta.get('effect_proposals',[]) if item['id']==settings.get('id')),None)
                    if event is None:raise ValueError('Предложение не найдено')
                    event['status']=settings['status'];save_meta(folder/'analysis.json',meta)
                return self.reply(200,{'status':event['status']})
            if parsed.path in {'/api/reanalyze', '/api/segment', '/api/lyrics', '/api/lyrics-find'}:
                job_id, job, folder = self.project(query)
                if job['state'] != 'ready':
                    raise ValueError('Дождись обработки песни')
                settings = json.loads(self.request_body(100000))
                if not isinstance(settings, dict):
                    raise ValueError('Неверные параметры')
                if parsed.path == '/api/lyrics-find':
                    candidate = lookup(str(settings.get('artist', '')), str(settings.get('title', '')), job['duration'])
                    with lock:
                        jobs[job_id]['lyrics_candidate'] = candidate
                        save_job(job_id)
                    return self.reply(200, candidate)
                if parsed.path == '/api/lyrics':
                    if job.get('lyrics_state') == 'processing':
                        raise ValueError('Текст уже обрабатывается')
                    text = settings.get('text', '')
                    if not isinstance(text, str) or len(text) > 30000 or settings.get('method', 'audio') not in {'audio', 'lrc'}:
                        raise ValueError('Некорректный текст; максимум 30000 символов')
                    request_file = folder / ('lyrics-request-' + uuid.uuid4().hex + '.json')
                    request_file.write_text(json.dumps(settings, ensure_ascii=False), encoding='utf-8')
                    with lock:
                        jobs[job_id]['lyrics_state'] = 'processing'
                        jobs[job_id].pop('lyrics_error', None)
                    threading.Thread(target=synchronize_lyrics, args=(job_id, request_file), daemon=True).start()
                    return self.reply(202, {'state': 'processing'})
                if parsed.path == '/api/reanalyze':
                    separate_again=settings.get('separate',False)
                    if not isinstance(separate_again,bool):raise ValueError('Некорректная настройка разделения')
                    if separate_again and not (folder/'song.wav').is_file():raise ValueError('Исходник не найден; загрузи песню снова')
                    if job.get('analysis_state') == 'processing':
                        raise ValueError('Разметка уже пересчитывается')
                    with lock:
                        jobs[job_id]['analysis_state'] = 'processing'
                    threading.Thread(target=refresh_analysis, args=(job_id,separate_again), daemon=True).start()
                    return self.reply(202, {'state': 'processing'})
                with processing_lock:
                    meta = json.loads((folder / 'analysis.json').read_text(encoding='utf-8'))
                    role = next((r for r in meta['roles'] if r['id'] == settings.get('role')), None)
                    index = settings.get('index')
                    custom = settings.get('range')
                    if role is None:
                        raise ValueError('Фрагмент не найден')
                    if custom is not None:
                        if not isinstance(custom, list) or len(custom) != 2:
                            raise ValueError('Некорректный интервал')
                        segment = [float(x) for x in custom]
                        if not all(math.isfinite(x) for x in segment) or not 0 <= segment[0] < segment[1] <= job['duration']:
                            raise ValueError('Интервал должен находиться внутри песни')
                    else:
                        if not isinstance(index, int) or not 0 <= index < len(role['segments']):
                            raise ValueError('Фрагмент не найден')
                        segment = role['segments'][index]
                    action = settings.get('action')
                    if action == 'exclude':
                        excluded = role.setdefault('excluded', [])
                        if segment not in excluded:
                            excluded.append(segment)
                    elif action == 'restore':
                        role['excluded'] = [item for item in role.get('excluded', []) if item != segment]
                    elif action in {'artist2','lead'} and action != role['id'] and custom is None:
                        other = next((r for r in meta['roles'] if r['id'] == action), None)
                        if other is None:
                            other = {'id': action, 'name': 'Второй исполнитель' if action == 'artist2' else 'Основной вокал', 'reference': role['reference'], 'segments': [], 'mask': [False] * len(role['mask'])}
                            meta['roles'].append(other)
                        if other['reference'] != role['reference']:
                            raise ValueError('Эти партии используют разные исходные дорожки')
                        lo, hi = round(segment[0] / meta['hop']), round(segment[1] / meta['hop'])
                        for i in range(lo, min(hi, len(role['mask']))):
                            other['mask'][i], role['mask'][i] = role['mask'][i], False
                        other['segments'].append(segment)
                        other['segments'].sort()
                        role['segments'].pop(index)
                    else:
                        raise ValueError('Неизвестное действие')
                    save_guides(folder, meta, force=True)
                    with lock:
                        save_meta(folder / 'analysis.json', meta)
                        jobs[job_id]['roles'] = public_roles(meta)
                        save_job(job_id)
                return self.reply(200, jobs[job_id])
            if parsed.path == "/api/render":
                job_id, job, folder = self.project(query)
                if job["state"] != "ready":
                    raise ValueError("Дождитесь обработки песни")
                if job.get('analysis_state') == 'processing':
                    raise ValueError('Дождись обновления разметки')
                settings = json.loads(self.request_body(100000))
                if not isinstance(settings, dict):
                    raise ValueError('Неверные параметры сборки')
                tracks = []
                for saved, offset in selected_takes(job, settings.get('tracks')):
                    voice = read_wav(folder / (saved['id'] + '.wav'))[:, 0]
                    tracks.append({'voice': voice, 'offset': offset, 'role': saved['role'],
                                   'start': saved.get('start', 0), 'end': saved.get('end', job['duration']),
                                   'region': saved.get('region', [0, job['duration']])})
                autotune = settings.get('autotune', False)
                tune_mode = settings.get('tune_mode', 'gentle')
                pitch_falls = settings.get('pitch_falls',True)
                if not isinstance(pitch_falls,bool): raise ValueError('Некорректная настройка спада высоты')
                tune_settings = settings.get('tune_settings')
                tuning_options(tune_mode,tune_settings)
                with lock:
                    personal=personalization.load(DATA)
                    profile = personalization.processing_profile(voice_profile(),personal)
                vocal_db = float(settings.get('vocal_db', 0))
                space = settings.get('space', 'auto')
                if space not in SPACE_MODES:
                    raise ValueError('Неизвестный эффект')
                if not isinstance(autotune, bool) or not math.isfinite(vocal_db) or not -12 <= vocal_db <= 12:
                    raise ValueError('Некорректная настройка голоса')
                with processing_lock:
                    if job.get('analysis_state')=='processing':raise ValueError('Дождись обработки вокала')
                    instrumental = read_wav(folder / "instrumental.wav")
                    meta = json.loads((folder / "analysis.json").read_text(encoding="utf-8"))
                    references = {name: read_reference(folder, name) for name in meta["profiles"]}
                    if (folder / 'lead.wav').exists():
                        references.setdefault('lead', read_reference(folder, 'lead'))
                    diagnostics=[]
                    result = mix(instrumental, references, tracks, meta, autotune=autotune, vocal_db=vocal_db, space=space, voice_profile=profile, tune_mode=tune_mode, tune_settings=tune_settings, pitch_falls=pitch_falls,diagnostics=diagnostics)
                render_id = uuid.uuid4().hex
                write_wav(folder / (render_id + ".wav"), result)
                with lock:
                    jobs[job_id].setdefault('render_options', {})[render_id] = {'autotune':autotune,'tune_mode':tune_mode,'tune_settings':tune_settings,'pitch_falls':pitch_falls,'effect_decisions':{event['id']:event.get('status','pending') for event in meta.get('effect_proposals',[])},'voice_profile':profile,'vocal_db':vocal_db,'space':space,'tracks':settings['tracks']}
                    jobs[job_id]["renders"].append(render_id)
                    jobs[job_id].setdefault('render_diagnostics',{})[render_id]=dict(version=1,app_version=BACKEND_VERSION,voices=diagnostics)
                    personal=personalization.load(DATA)
                    example=hashlib.sha256((job_id+':'+','.join(sorted(t['id'] for t in settings['tracks']))).encode()).hexdigest()
                    personalization.observe(personal,example,diagnostics,dict(saved_at=int(datetime.now(timezone.utc).timestamp()*1000),mode=tune_mode,settings=tune_settings,autotune=autotune,space=space,vocal_db=vocal_db,pitch_falls=pitch_falls))
                    personalization.save(DATA,personal)
                    save_job(job_id)
                return self.reply(200, {"url": f"/api/audio?id={job_id}&name={render_id}",'render_id':render_id,'diagnostics':jobs[job_id]['render_diagnostics'][render_id]})
            self.reply(404, {"error": "Не найдено"})
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self.reply(400, {"error": str(exc)})
        except Exception as exc:
            self.reply(500, {"error": str(exc)[-1200:]})


class StudioServer(ThreadingHTTPServer):
    # Graceful update waits for existing uploads/renders to finish writing their files.
    daemon_threads = False


if __name__ == "__main__":
    # start.bat must retire the same stale backend as the desktop launcher.
    from desktop import retire_previous_server,ready
    if ready():
        if '--desktop' not in sys.argv:webbrowser.open('http://127.0.0.1:8765')
        sys.exit(0)
    retire_previous_server()
    ffmpeg_path()
    url = "http://127.0.0.1:8765"
    restore_jobs()
    if '--desktop' not in sys.argv:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    print("Локальная караоке-студия:", url)
    with StudioServer(("127.0.0.1", 8765), Handler) as server:
        server.serve_forever()
