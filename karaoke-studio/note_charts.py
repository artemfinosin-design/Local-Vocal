"""Read user-provided UltraStar TXT note maps; audio files named in TXT are ignored."""

import math
import re


def parse_ultrastar(text, duration):
    if not isinstance(text, str) or len(text) > 100_000:
        raise ValueError('Файл нот слишком большой')
    header = {}
    for line in text.lstrip('\ufeff').splitlines():
        if line.startswith('#') and ':' in line:
            name, value = line[1:].split(':', 1)
            header[name.strip().upper()] = value.strip()
    version = header.get('VERSION', '1.0.0')
    if not re.fullmatch(r'1\.\d+\.\d+', version):
        raise ValueError('Поддерживается формат UltraStar TXT версии 1 или без версии')
    try:
        bpm = float(header['BPM'].replace(',', '.'))
        gap = float(header.get('GAP', '0').replace(',', '.')) / 1000
    except (KeyError, ValueError):
        raise ValueError('В файле нот нужен корректный #BPM и #GAP') from None
    if not math.isfinite(bpm) or not 1 <= bpm <= 1000 or not math.isfinite(gap) or abs(gap) > duration:
        raise ValueError('Некорректный темп или сдвиг нот')
    relative = header.get('RELATIVE', 'no').lower() == 'yes'
    beat = 60 / (4 * bpm)
    offsets = {str(n): 0 for n in range(1, 10)}
    voices = {str(n): [] for n in range(1, 10)}
    current = '1'
    for line in text.splitlines():
        line = line.strip()
        if re.fullmatch(r'P[1-9]', line):
            current = line[1:]
        elif line.startswith('-') and relative:
            fields = line.split()
            if len(fields) != 3:
                raise ValueError('Некорректный относительный сдвиг UltraStar')
            try:
                offsets[current] += int(fields[2])
            except ValueError:
                raise ValueError('Некорректный относительный сдвиг UltraStar') from None
        elif line[:1] in {':', '*'}:
            fields = line.split(maxsplit=4)
            if len(fields) < 4:
                raise ValueError('Неполная нота UltraStar')
            try:
                start, length, pitch = map(int, fields[1:4])
            except ValueError:
                raise ValueError('Некорректная нота UltraStar') from None
            begin = gap + (offsets[current] + start) * beat
            end = begin + length * beat
            if length <= 0 or not -15 <= begin < end <= duration + 15 or not -48 <= pitch <= 48:
                raise ValueError('Ноты выходят за пределы песни')
            voices[current].append({'start': round(begin, 3), 'end': round(end, 3), 'note': 60 + pitch})
    voices = {key: sorted(bars, key=lambda bar: bar['start']) for key, bars in voices.items() if bars}
    if not voices:
        raise ValueError('В файле нет нот для пения')
    for bars in voices.values():
        if any(left['end'] > right['start'] for left, right in zip(bars, bars[1:])):
            raise ValueError('В одной партии карты ноты перекрываются; выбери исправленный TXT')
    return {'title': header.get('TITLE', ''), 'artist': header.get('ARTIST', ''),
            'voices': voices, 'voice_names': {key: header.get('P' + key, 'Голос ' + key) for key in voices}}
