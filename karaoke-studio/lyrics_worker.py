import json
import re
import sys
import wave
from pathlib import Path

from lyrics import lrc_lines, result_lines
from runtime import configure_decoder


def synchronize(folder, models, request_file):
    request = json.loads(request_file.read_text(encoding='utf-8'))
    text = request.get('text', '').strip()
    if request.get('method')!='lrc':text=re.sub(r'^\s*\[[^]]+\]\s*$','',text,flags=re.M).strip()
    with wave.open(str(folder / 'vocals.wav')) as audio:
        duration = audio.getnframes() / audio.getframerate()
    if request.get('method') == 'lrc':
        result = lrc_lines(text, duration)
        if not result['lines']:
            raise ValueError('В этом тексте нет подходящих таймкодов LRC')
    else:
        configure_decoder()
        import torch
        import whisper
        import stable_whisper
        torch.set_num_threads(min(4, torch.get_num_threads()))
        model = stable_whisper.load_model('base', device='cpu', download_root=str(models / 'whisper'))
        samples = whisper.load_audio(str(folder / 'vocals.wav'))
        if text:
            if re.search('[А-Яа-яЁё]', text):
                language = 'ru'
            else:
                mel = whisper.log_mel_spectrogram(whisper.pad_or_trim(samples)).to(model.device)
                _, probabilities = model.detect_language(mel)
                language = max(probabilities, key=probabilities.get)
            aligned = model.align(samples, text, language=language, original_split=True,
                                  verbose=False, vad=False)
        else:
            aligned = model.transcribe(samples, word_timestamps=True, fp16=False, verbose=False, vad=False,
                                       beam_size=5, condition_on_previous_text=False)
        if aligned is None:
            raise ValueError('Модель не смогла привязать этот текст')
        result = result_lines(aligned, duration, text)
    result['text'] = text or '\n'.join(' '.join(word['text'] for word in line['words']) for line in result['lines'])
    result['source'] = request.get('source', 'Локальный анализ')
    request_file.with_suffix('.result.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    synchronize(*(Path(argument).resolve() for argument in sys.argv[1:4]))
