"""Amplitude-independent pitch tracking and local microphone calibration."""
import math
import numpy as np
import parselmouth
from scipy.signal import resample_poly
from scipy.ndimage import uniform_filter1d

RATE = 44100

TUNE_PRESETS = {
    'studio': {'name':'Студийный', 'description':'Плавная коррекция до трёх полутонов с сохранением живой подачи. Скорость учитывает настройку голоса; спорные ноты оригинала пропускаются.', 'strength':90, 'speed_ms':140, 'tolerance_cents':18, 'max_semitones':3.01, 'quantize':False},
    'gentle': {'name':'Мягкий', 'description':'Небольшие промахи, плавная коррекция.', 'strength':90, 'speed_ms':180, 'tolerance_cents':30, 'max_semitones':1.25, 'quantize':False},
    'natural': {'name':'Естественный', 'description':'Умеренная коррекция по мелодии, сохраняет небольшие отклонения.', 'strength':75, 'speed_ms':120, 'tolerance_cents':20, 'max_semitones':6.01, 'quantize':False},
    'melody': {'name':'По оригиналу', 'description':'Уверенно найденные ноты подтягиваются к мелодии оригинала в твоём регистре.', 'strength':100, 'speed_ms':90, 'tolerance_cents':16, 'max_semitones':12.01, 'quantize':False},
    'hard': {'name':'Жёсткий', 'description':'Быстрый заметный эффект: целевые ноты оригинала округляются до полутонов.', 'strength':100, 'speed_ms':20, 'tolerance_cents':3, 'max_semitones':12.01, 'quantize':True},
}
VOICE_RANGES = {'low':(50,400), 'middle':(70,700), 'high':(120,1400), 'wide':(45,1400)}


def tuning_options(mode='gentle', settings=None):
    if not isinstance(mode,str) or mode not in TUNE_PRESETS:
        raise ValueError('Неизвестный пресет коррекции нот')
    settings = {} if settings is None else settings
    if not isinstance(settings,dict) or set(settings)-{'strength','speed_ms','tolerance_cents','voice_type'}:
        raise ValueError('Некорректные настройки автотюна')
    result = dict(TUNE_PRESETS[mode], voice_type='auto')
    for key,lo,hi in (('strength',0,100),('speed_ms',20,300),('tolerance_cents',0,50)):
        value = settings.get(key,result[key])
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lo<=value<=hi:
            raise ValueError('Некорректная настройка: '+key)
        result[key] = float(value)
    kind = settings.get('voice_type','auto')
    if not isinstance(kind,str) or kind not in {'auto',*VOICE_RANGES}:
        raise ValueError('Неизвестный диапазон голоса')
    result['voice_type'] = kind
    return result


def tuning_profile(profile, voice_type):
    result = dict(profile or {})
    if voice_type in VOICE_RANGES:
        result['pitch_bounds'] = VOICE_RANGES[voice_type]
    return result or None



def track_pitch(samples, profile=None):
    signal = np.asarray(samples, dtype=np.float64).reshape(-1)
    signal = signal - np.mean(signal) if len(signal) else signal
    reduced = np.ascontiguousarray(resample_poly(signal, 1, 2), dtype=np.float64)
    level = float(np.percentile(np.abs(reduced), 95)) if len(reduced) else 0
    if len(reduced) < 2205 or level < 1e-7:
        times = np.arange(0, len(signal) / RATE + .005, .01)
        return np.zeros(len(times)), times, np.zeros(len(times))
    normalized = np.ascontiguousarray(reduced * (.25 / level))
    floor, ceiling = 55., 1100.
    if profile:
        floor = max(45., min(80., profile.get('low_hz',100) * .55))
        # Three comfortable calibration notes are not the singer's full upper range.
        ceiling = min(1400., max(1100., profile.get('high_hz',440) * 2.5))
    if profile and profile.get('pitch_bounds'):
        floor, ceiling = profile['pitch_bounds']
    # Continuity and voicing costs suppress independent frame octave flips.
    # Padding keeps short syllables and calibration edges visible.
    padding=round(.08*(RATE//2))
    sound=parselmouth.Sound(np.pad(normalized,(padding,padding)),sampling_frequency=RATE//2)
    tracked=sound.to_pitch_ac(time_step=.01,pitch_floor=floor,pitch_ceiling=ceiling)
    times=tracked.xs()-.08
    active=(times>=-1e-6)&(times<=len(signal)/RATE+1e-6)
    times=np.clip(times[active],0,len(signal)/RATE);pitch=tracked.selected_array['frequency'][active].copy()
    strength=tracked.selected_array['strength'][active]
    rms = np.sqrt(np.maximum(uniform_filter1d(reduced ** 2, 441), 0) + 1e-16)
    frame_level = np.interp(times, np.arange(len(rms)) / (RATE // 2), rms)
    threshold = max(1e-7, float(np.percentile(frame_level, 80)) * .025)
    if profile:
        # Calibration noise is a bound, not a fixed gate for quieter future takes.
        threshold = max(threshold, min(profile.get('noise_rms',0) * 2.5,
                                        float(np.percentile(frame_level, 80)) * .12))
    confidence = np.zeros(len(pitch))
    for i in np.flatnonzero((pitch > 0) & (frame_level > threshold)):
        lag = round((RATE // 2) / pitch[i])
        center = round(times[i] * (RATE // 2))
        start, end = max(lag, center - 661), min(len(normalized), center + 661)
        a, b = normalized[start:end], normalized[start-lag:end-lag]
        confidence[i] = min(strength[i],max(0., float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))))
    pitch[confidence < .55] = 0
    if (profile or {}).get('reference'):
        # A separated ensemble can look periodic while following a different
        # singer. Independent agreement is required before using it as a target.
        import pyworld
        other,at=pyworld.dio(normalized,RATE//2,f0_floor=floor,f0_ceil=ceiling,frame_period=10)
        other=np.interp(times,at,other)
        agree=(pitch>0)&(other>0)
        distance=np.full(len(pitch),np.inf)
        distance[agree]=abs(12*np.log2(pitch[agree]/other[agree]))
        confidence[distance>.6]=0;pitch[distance>.6]=0
    return pitch, times, confidence


def calibrate(samples):
    samples = np.asarray(samples, dtype=np.float64).reshape(-1)
    if not 10 <= len(samples) / RATE <= 25:
        raise ValueError('Запиши настройку целиком: тишина, затем три протяжные ноты.')
    noise = float(np.sqrt(np.mean(samples[:round(1.5 * RATE)] ** 2)))
    clips = [samples[round(a * RATE):round(b * RATE)] for a, b in ((2.4, 5.7), (6.4, 9.7), (10.4, 13.7))]
    notes, confidences, levels, jitter = [], [], [], []
    for clip in clips:
        pitch, _, confidence = track_pitch(clip)
        good = pitch[(pitch > 0) & (confidence > .65)]
        if len(good) < 70:
            raise ValueError('Не удалось уверенно услышать все три ноты. Подойди ближе и тяни «а» ровно, без музыки.')
        notes.append(float(np.median(good)))
        confidences.append(float(np.median(confidence[pitch > 0])))
        levels.append(float(np.sqrt(np.mean(clip ** 2))))
        adjacent=(pitch[:-1]>0)&(pitch[1:]>0)&(confidence[:-1]>.75)&(confidence[1:]>.75)
        movement=abs(1200*np.log2(np.maximum(pitch[1:],1)/np.maximum(pitch[:-1],1)))
        if np.any(adjacent):jitter.append(float(np.median(movement[adjacent])))
    if min(levels) < noise * 3:
        raise ValueError('Голос слишком близок к фоновому шуму. Выбери более тихое место и повтори настройку.')
    clipping = float(np.mean(np.abs(samples) >= .985))
    if clipping > .005:
        raise ValueError('Микрофон перегружен: уменьши его уровень или отодвинься и повтори настройку.')
    if 12 * np.log2(max(notes) / min(notes)) < 2:
        raise ValueError('Три ноты почти одинаковые. Спой одну ниже, одну удобно и одну выше.')
    return {'version': 2, 'low_hz': min(notes), 'high_hz': max(notes),
            'pitch_jitter_cents':float(np.median(jitter)) if jitter else 0,
            'recommended_speed_ms':float(np.clip(100+4*np.median(jitter),100,200)) if jitter else 140,
            'notes_hz': notes, 'noise_rms': noise, 'voice_rms': float(np.median(levels)),
            'confidence': float(np.mean(confidences)), 'clipping': clipping,
            'suggested_input_db': float(np.clip(20 * np.log10(.1 / max(np.median(levels), 1e-8)), -12, 24))}
