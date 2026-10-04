"""Lyrics lookup sends title, artist and duration. Audio alignment runs locally."""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def guess_title(filename):
    name = re.sub(r'\.[^.]+$', '', filename).replace('_', ' ')
    name = re.sub(r'(?<=[A-Za-zА-Яа-я])\s+\d{6,}$', '', name)
    parts = re.split(r'\s+[-–—]\s+', name, maxsplit=1)
    return {'artist': parts[0].strip() if len(parts) == 2 else '',
            'title': parts[-1].strip()}


def lookup(artist, title, duration):
    if not artist or not title or len(artist) > 200 or len(title) > 200:
        raise ValueError('Укажи исполнителя и название песни')
    query = urlencode({'artist_name': artist, 'track_name': title, 'duration': round(duration)})
    def fetch(url):
        try:
            with urlopen(Request(url, headers={'User-Agent':'SvoyaVersiya/0.4 (local karaoke)'}), timeout=15) as response:
                return json.loads(response.read(1024 * 1024))
        except HTTPError as error:
            if error.code == 404:
                return None
            raise ValueError('LRCLIB сейчас недоступен (ошибка сервиса). Попробуй позже или вставь текст вручную.') from error
        except (URLError, TimeoutError, OSError) as error:
            raise ValueError('Не удалось связаться с LRCLIB. Проверь интернет или вставь текст вручную.') from error
    data = fetch('https://lrclib.net/api/get?' + query)
    if data is None or not (data.get('plainLyrics') or data.get('syncedLyrics')):
        candidates = fetch('https://lrclib.net/api/search?' + urlencode({'artist_name':artist,'track_name':title})) or []
        normalize = lambda value: re.sub(r'[^\w]', '', value.casefold())
        matches = [item for item in candidates if normalize(item.get('artistName','')) == normalize(artist) and normalize(item.get('trackName','')) == normalize(title) and (item.get('plainLyrics') or item.get('syncedLyrics'))]
        if not matches:
            return {'found':False}
        data = min(matches, key=lambda item:abs(float(item.get('duration') or 0)-duration))
    text = data.get('plainLyrics')
    synced = data.get('syncedLyrics')
    return {'found': bool(text or synced), 'text': text or synced or '',
            'synced': synced or '', 'artist': data.get('artistName', artist),
            'title': data.get('trackName', title), 'source': 'LRCLIB'}


def lrc_lines(text, duration):
    rows = []
    for line in text.splitlines():
        stamps = re.findall(r'\[(\d+):(\d+(?:\.\d+)?)\]', line)
        words = re.sub(r'\[[^]]*\]', '', line).strip().split()
        for minute, second in stamps:
            at = int(minute) * 60 + float(second)
            if words and 0 <= at < duration:
                rows.append((at, words))
    rows.sort(key=lambda item: item[0])
    lines = []
    for i, (start, tokens) in enumerate(rows):
        end = min(duration, rows[i + 1][0] if i + 1 < len(rows) else start + 6)
        if end <= start:
            continue
        step = (end - start) / len(tokens)
        lines.append({'start': start, 'end': end, 'words': [
            {'text': token, 'start': start + j * step, 'end': start + (j + 1) * step}
            for j, token in enumerate(tokens)]})
    return {'lines': lines, 'timing': 'line-estimate',
            'notice': 'Время строк из LRC; подсветка слов приблизительная. Для точной привязки выбери анализ аудио.'}


def result_lines(result, duration):
    lines = []
    for segment in result.segments:
        words = [{'text': word.word.strip(), 'start': max(0, float(word.start)),
                  'end': min(duration, float(word.end))}
                 for word in (segment.words or []) if word.word.strip() and word.end > word.start and word.start < duration]
        for i in range(0, len(words), 12):
            part = words[i:i + 12]
            if part:
                lines.append({'start': part[0]['start'], 'end': part[-1]['end'], 'words': part})
    if not lines:
        raise ValueError('Не удалось привязать слова. Проверь текст или загрузи LRC с таймкодами.')
    return {'lines': lines, 'timing': 'audio-aligned',
            'notice': 'Слова привязаны локальной моделью. В многоголосии и при искажениях возможны ошибки.'}
