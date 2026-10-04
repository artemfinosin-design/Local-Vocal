"""Explicitly requested local example bundles. No network or mixed output audio."""
from voice import tuning_options
from runtime import BACKEND_VERSION
import hashlib
import json
import math
import re
import uuid
import wave
from pathlib import Path, PureWindowsPath
from zipfile import ZipFile, ZIP_DEFLATED


def selected_takes(job, selection):
    if not isinstance(selection, list) or not selection:
        raise ValueError('Сначала запиши хотя бы один фрагмент.')
    available = {take['id']: take for take in job['tracks']}
    chosen = set()
    result = []
    for item in selection:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not re.fullmatch('[a-f0-9]{32}', item['id']):
            raise ValueError('Неверная запись')
        identity = item['id']
        if identity not in available or identity in chosen:
            raise ValueError('Неизвестная или повторная запись')
        offset = float(item.get('offset', 0))
        if not math.isfinite(offset) or not -5 <= offset <= 5:
            raise ValueError('Задержка должна быть от −5 до +5 секунд')
        chosen.add(identity)
        result.append((available[identity], offset))
    return result


def make_bundle(folder, job, options, profile=None, personal_profile=None):
    if not isinstance(options, dict) or options.get('consent') is not True:
        raise ValueError('Подтверди добровольное сохранение песни и записей голоса в архив.')
    takes = selected_takes(job, options.get('tracks'))
    source = next((p for p in Path(folder).glob('upload.*') if p.suffix.lower() in {'.mp3', '.wav', '.flac', '.m4a', '.ogg', '.aac'}), None)
    source = source or Path(folder) / 'song.wav'
    if not source.is_file():
        raise ValueError('Исходная песня не найдена.')
    mode = options.get('tune_mode', 'gentle')
    gain = float(options.get('vocal_db', 0))
    tuning_options(mode,options.get('tune_settings'))
    if not math.isfinite(gain) or not -12 <= gain <= 12 or not isinstance(options.get('autotune'), bool):
        raise ValueError('Некорректные настройки обработки')
    if not isinstance(options.get('pitch_falls',True),bool): raise ValueError('Некорректная настройка спада высоты')
    files = [(source, 'original/song' + source.suffix.lower())]
    manifest = {'schema': 2, 'app_version': BACKEND_VERSION, 'purpose': 'Добровольный пример для диагностики вокальной обработки',
                'original_filename': PureWindowsPath(job.get('filename') or source.name).name,
                'song': files[0][1], 'takes': [], 'voice_profile': profile,
                'settings': {key: options.get(key) for key in ('autotune', 'tune_mode', 'tune_settings', 'pitch_falls', 'vocal_db', 'space')},
                'note': 'Записи микрофона до эффектов, коррекции нот и сведения. Музыка из готового микса не добавлялась; утечки в микрофон возможны.',
                'files': []}
    analysis=Path(folder)/'analysis.json'
    if analysis.exists():
        meta=json.loads(analysis.read_text(encoding='utf-8'))
        manifest['effect_proposals']=meta.get('effect_proposals',[])
    for index, (take, offset) in enumerate(takes, 1):
        path = Path(folder) / (take['id'] + '.wav')
        if not path.is_file():
            raise ValueError('Одна из записей отсутствует. Архив не создан.')
        name = f'voice/take-{index:02d}.wav'
        with wave.open(str(path), 'rb') as wav:
            if wav.getnchannels() != 1:
                raise ValueError('Ожидалась отдельная монофоническая запись микрофона.')
            duration = wav.getnframes() / wav.getframerate()
        files.append((path, name))
        manifest['takes'].append({'file': name, 'role': take['role'], 'recording_start': take.get('start', 0),
                                  'region': take.get('region', [0, job['duration']]),
                                  'offset_seconds': offset, 'duration_seconds': duration})
    identity = uuid.uuid4().hex
    target = Path(folder) / ('feedback-' + identity + '.zip')
    pending = target.with_suffix('.partial')
    try:
        with ZipFile(pending, 'w', ZIP_DEFLATED, compresslevel=4) as bundle:
            if personal_profile is not None:
                bundle.writestr('personal-profile.json',json.dumps(personal_profile,ensure_ascii=False,indent=2))
            bundle.writestr('processing-log.json',json.dumps({'renders':job.get('render_diagnostics',{}),
                'ratings':job.get('render_ratings',{}),'options':job.get('render_options',{})},ensure_ascii=False,indent=2))
            for path, name in files:
                digest = hashlib.sha256()
                with path.open('rb') as audio:
                    for chunk in iter(lambda: audio.read(1024 * 1024), b''): digest.update(chunk)
                bundle.write(path, name)
                manifest['files'].append({'path': name, 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size})
            bundle.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            bundle.writestr('README.txt', 'Этот архив создан по явному выбору пользователя.\noriginal — загруженная песня.\nvoice — необработанные записи микрофона, не готовое караоке.\nmanifest.json — таймкоды, задержка и параметры обработки.\npersonal-profile.json — числовой личный профиль, настройки и оценки.\nprocessing-log.json — журнал обработки этой песни; текущие настройки могут отличаться от настроек готовой версии.\nАудио других проектов, калибровочные записи и системные пути не включены.\nАвтоматическая отправка не выполнялась.\n')
        pending.replace(target)
    finally:
        pending.unlink(missing_ok=True)
    return identity, target
