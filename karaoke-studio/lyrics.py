"""Lyrics lookup sends title, artist and duration. Audio alignment runs locally."""
import json
import re
import unicodedata
from difflib import SequenceMatcher
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def guess_title(filename):
    name = re.sub(r'\.[^.]+$', '', filename).replace('_', ' ')
    name = re.sub(r'^\d+[\s.-]+', '', name)
    name = re.sub(r'(?<=[A-Za-zА-Яа-я])\s+\d{6,}$', '', name)
    name = clean_query(name)
    parts = re.split(r'\s+[-–—]\s+', name, maxsplit=1)
    return {'artist': parts[0].strip() if len(parts) == 2 else '',
            'title': parts[-1].strip()}


def clean_query(value):
    value=re.sub(r'[\(\[]\s*(?:official(?:\s+[^)\]]*)?|(?:music\s+)?video|lyrics?(?:\s+video)?|audio|vocals?(?:\s+only)?|remaster(?:ed)?(?:\s+\d{4})?|клип|текст)\s*[\)\]]',' ',value,flags=re.I)
    value=unicodedata.normalize('NFKC',value).replace('’',"'").replace('“','').replace('”','').replace('—','-').replace('–','-')
    return re.sub(r'\s+',' ',re.sub(r'[^\w\s\-\'&]',' ',value)).strip()


def _similarity(query, candidate):
    normalize=lambda s:clean_query(s).casefold().replace("'",'')
    a,b=normalize(query),normalize(candidate)
    score=SequenceMatcher(None,a,b).ratio()
    # A correct multiword title with a short extra phrase remains searchable.
    if len(b.split())>=2 and (' '+b+' ') in (' '+a+' ') and len(a.split())-len(b.split())<=5:
        score=max(score,.94)
    if len(b.split())==1 and len(b)>=4 and a.startswith(b+' ') and len(a.split())<=4:
        score=max(score,.88)
    return score


def lookup(artist, title, duration):
    if not title.strip() or len(artist) > 200 or len(title) > 200:
        raise ValueError('Укажи название песни; исполнитель необязателен')
    artist,title=clean_query(artist),clean_query(title)
    if not title:raise ValueError('Укажи название песни')
    query = urlencode({'artist_name': artist, 'track_name': title, 'duration': round(duration)})
    def fetch(url):
        try:
            with urlopen(Request(url, headers={'User-Agent':'LocalVocal/0.16 (local karaoke)'}), timeout=8) as response:
                return json.loads(response.read(1024 * 1024))
        except HTTPError as error:
            if error.code == 404:
                return None
            raise ValueError('LRCLIB сейчас недоступен (ошибка сервиса). Попробуй позже или вставь текст вручную.') from error
        except (URLError, TimeoutError, OSError) as error:
            raise ValueError('Не удалось связаться с LRCLIB. Проверь интернет или вставь текст вручную.') from error
    data = fetch('https://lrclib.net/api/get?' + query) if artist else None
    if data is None or not (data.get('plainLyrics') or data.get('syncedLyrics')):
        candidates = fetch('https://lrclib.net/api/search?' + urlencode({'track_name':title})) or []
        if not candidates:
            candidates=fetch('https://lrclib.net/api/search?'+urlencode({'q':' '.join(title.split()[:2])})) or []
        if not candidates and len(title.split())>1 and len(title.split()[0])>=4:
            candidates=fetch('https://lrclib.net/api/search?'+urlencode({'q':title.split()[0]})) or []
        ranked=[]
        for item in candidates[:100]:
            if not isinstance(item,dict) or not (item.get('plainLyrics') or item.get('syncedLyrics')):continue
            similarity=_similarity(title,item.get('trackName',''))
            distance=abs(float(item.get('duration') or 0)-duration)
            if similarity<.78 or distance>max(25,duration*.15):continue
            rank=similarity*.8+.12*max(0,1-distance/25)+.08*_similarity(artist,item.get('artistName',''))
            ranked.append((rank,item))
        if not ranked:return {'found':False}
        by_artist={}
        for rank,item in ranked:
            key=clean_query(item.get('artistName','')).casefold()
            if key not in by_artist or rank>by_artist[key][0]:by_artist[key]=(rank,item)
        ranked=sorted(by_artist.values(),key=lambda pair:pair[0],reverse=True)
        if len(ranked)>1 and ranked[0][0]-ranked[1][0]<.025 and clean_query(ranked[0][1].get('artistName','')).casefold()!=clean_query(ranked[1][1].get('artistName','')).casefold():
            return {'found':False,'ambiguous':True}
        data=ranked[0][1]
    text = data.get('plainLyrics')
    synced = data.get('syncedLyrics')
    if not text and synced:text='\n'.join(re.sub(r'\[[^]]*\]','',line).strip() for line in synced.splitlines())
    if len(text or '')>30000:raise ValueError('Найденный текст слишком большой для этой песни')
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
        lines.extend(_display_lines([
            {'text': token, 'start': start + j * step, 'end': start + (j + 1) * step}
            for j, token in enumerate(tokens)]))
    return {'lines': lines, 'timing': 'line-estimate',
            'notice': 'Время строк из LRC; подсветка слов приблизительная. Для точной привязки выбери анализ аудио.'}


def _display_lines(words):
    lines=[];part=[];characters=0
    for word in words:
        if part and (len(part)>=8 or characters+len(word['text'])>54):
            lines.append({'start':part[0]['start'],'end':max(w['end'] for w in part),'words':part});part=[];characters=0
        part.append(word);characters+=len(word['text'])+1
    if part:lines.append({'start':part[0]['start'],'end':max(w['end'] for w in part),'words':part})
    return lines


def result_lines(result, duration, text=''):
    lines = [];recognized=[]
    for segment in result.segments:
        words=[]
        for word in segment.words or []:
            tokens=word.word.strip().split()
            if not tokens or word.start>=duration:continue
            start=max(0,float(word.start));end=min(duration,max(start+.04,float(word.end)))
            for index,token in enumerate(tokens):
                words.append({'text':token,'start':start+(end-start)*index/len(tokens),
                              'end':start+(end-start)*(index+1)/len(tokens)})
                if word.end<=word.start:words[-1]['estimated']=True
        recognized.extend(words);lines.extend(_display_lines(words))
    if text and recognized:
        rows=[line.split() for line in text.splitlines() if line.strip() and not re.fullmatch(r'\s*\[[^]]+\]\s*',line)]
        tokens=[token for row in rows for token in row]
        normalize=lambda s:re.sub(r'[^\w]','',s.casefold())
        aligned=[None]*len(tokens)
        matcher=SequenceMatcher(None,[normalize(w) for w in tokens],[normalize(w['text']) for w in recognized],autojunk=False)
        for match in matcher.get_matching_blocks():
            for offset in range(match.size):
                word=recognized[match.b+offset]
                if not word.get('estimated'):aligned[match.a+offset]=dict(word,text=tokens[match.a+offset])
        if not any(aligned):raise ValueError('Модель не смогла сопоставить текст с вокалом; прежние таймкоды сохранены')
        index=0
        while index<len(aligned):
            if aligned[index] is not None:index+=1;continue
            stop=index
            while stop<len(aligned) and aligned[stop] is None:stop+=1
            previous=aligned[index-1]['end'] if index else 0
            following=aligned[stop]['start'] if stop<len(aligned) else min(duration,previous+.25*(stop-index))
            begin=max(aligned[index-1]['start'] if index else 0,min(previous,following-.06*(stop-index)))
            if not index:begin=max(0,following-.25*(stop-index))
            step=max(.01,(following-begin)/(stop-index))
            for at in range(index,stop):
                start=min(duration-.01,begin+(at-index)*step)
                aligned[at]={'text':tokens[at],'start':start,'end':min(duration,start+step),'estimated':True}
            index=stop
        lines=[];at=0
        for row in rows:
            lines.extend(_display_lines(aligned[at:at+len(row)]));at+=len(row)
    if not lines:
        raise ValueError('Не удалось привязать слова. Проверь текст или загрузи LRC с таймкодами.')
    return {'lines': lines, 'timing': 'audio-aligned',
            'notice': 'Слова привязаны локальной моделью. В многоголосии и при искажениях возможны ошибки.'}
