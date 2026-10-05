"""Small audio operations shared by the local server and its self-check."""

import hashlib
import json
import math
import wave
from pathlib import Path

import numpy as np
from effects import analyze_effects, render_effects, vocal_dynamics
from voice import track_pitch, tuning_options, tuning_profile
from pitch_effects import analyze_pitch_falls, render_pitch_falls, analyze_stutters, render_stutters, analyze_colours, render_colours

RATE = 44100
HOP = RATE // 4


def read_wav(path):
    with wave.open(str(path), "rb") as wav:
        if wav.getframerate() != RATE or wav.getsampwidth() != 2:
            raise ValueError("Expected 44.1 kHz, 16-bit WAV")
        channels = wav.getnchannels()
        if channels not in (1, 2):
            raise ValueError("Expected mono or stereo WAV")
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
        return samples.reshape(-1, channels).astype(np.float32) / 32768


def write_wav(path, samples):
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim == 1:
        samples = samples[:, None]
    samples = np.clip(samples, -1, 1)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(samples.shape[1])
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes((samples * 32767).astype("<i2").tobytes())


def _segments(mask, hop, minimum=0.25):
    """Turn active frames into recording cues, bridging pauses shorter than 0.5 s."""
    active = np.asarray(mask, dtype=bool).copy()
    bridge = max(1, round(0.5 / hop))
    for i in range(1, len(active) - bridge):
        if active[i - 1] and not active[i]:
            following = np.flatnonzero(active[i:i + bridge + 1])
            if len(following):
                active[i:i + following[0]] = True
    edges = np.diff(np.r_[False, active, False].astype(int))
    return [[round(start * hop, 2), round(end * hop, 2)]
            for start, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1))
            if (end - start) * hop >= minimum]


def _timbre(part):
    """Voiced spectral envelope: compare vocal tract shape, not note or loudness."""
    import pyworld
    from scipy.signal import resample_poly
    signal = np.ascontiguousarray(resample_poly(np.mean(part, axis=1), 1, 3), dtype=np.float64)
    if len(signal) < RATE // 3 // 2 or np.max(np.abs(signal)) < 1e-6:
        return None
    signal /= max(np.percentile(abs(signal), 95), 1e-6)
    pitch, times = pyworld.dio(signal, RATE // 3, f0_floor=65, f0_ceil=1000, frame_period=20)
    voiced = pitch > 0
    if np.mean(voiced) < .35:
        return None
    envelope = pyworld.cheaptrick(signal, pitch, times, RATE // 3)
    frequencies = np.linspace(0, RATE / 6, envelope.shape[1])
    # Above the fundamental: formant shape is more stable across chest/head registers.
    edges = np.geomspace(500, 5000, 13)
    values = np.asarray([np.median(np.log(np.mean(envelope[voiced][:, (frequencies >= lo) & (frequencies < hi)], axis=1)+1e-10))
                         for lo, hi in zip(edges[:-1], edges[1:])])
    # Floor very weak bands: harmonic gaps are not a different vocal tract.
    values = np.maximum(values, np.max(values)-9.2)
    # Remove microphone/EQ spectral tilt as well as overall level.
    tilt = np.polyval(np.polyfit(np.arange(len(values)), values, 1), np.arange(len(values)))
    return values - tilt


def suggest_roles(vocals, active, width):
    """Conservative timbre/stereo grouping; singing speaker diarization remains uncertain."""
    count = len(active)
    masks = {"lead": np.asarray(active, dtype=bool).copy()}
    block_frames = max(1, round(2 / (HOP / RATE)))
    features, blocks = [], []
    for start in range(0, count, block_frames):
        end = min(count, start + block_frames)
        if np.mean(active[start:end]) < 0.45:
            continue
        feature = _timbre(vocals[start * HOP:min(end * HOP, len(vocals))])
        if feature is not None:
            features.append(feature)
            blocks.append((start, end))
    if len(features) >= 6:
        vectors = np.asarray(features)
        centers = vectors[[0, int(np.argmax(np.linalg.norm(vectors - vectors[0], axis=1)))]]
        for _ in range(12):
            labels = np.argmin(np.linalg.norm(vectors[:, None] - centers[None], axis=2), axis=1)
            if not np.any(labels == 0) or not np.any(labels == 1):
                break
            new_centers = np.asarray([np.mean(vectors[labels == k], axis=0) for k in (0, 1)])
            if np.allclose(new_centers, centers):
                break
            centers = new_centers
        sizes = np.bincount(labels, minlength=2)
        separation = float(np.linalg.norm(centers[0] - centers[1]))
        within = float(np.mean(np.linalg.norm(vectors - centers[labels], axis=1)))
        # Never force two groups by normalizing tiny fluctuations to unit variance.
        distances = np.linalg.norm(vectors[:, None] - vectors[None], axis=2)
        silhouettes = []
        for i, label in enumerate(labels):
            same = (labels == label) & (np.arange(len(labels)) != i)
            a = float(np.mean(distances[i, same])) if np.any(same) else 0
            b = float(np.mean(distances[i, labels != label])) if np.any(labels != label) else 0
            silhouettes.append((b-a)/max(a,b,1e-9))
        if min(sizes) >= 3 and separation > max(6, within * 3) and np.median(silhouettes) > .65:
            second = int(np.argmin(sizes))
            alternative = np.zeros(count, dtype=bool)
            for (start, end), label in zip(blocks, labels):
                if label == second:
                    alternative[start:end] = active[start:end]
            sustained = _segments(alternative, HOP / RATE, minimum=3)
            if sum(end - start for start, end in sustained) >= 6:
                alternative[:] = False
                for start, end in sustained:
                    alternative[round(start*RATE/HOP):round(end*RATE/HOP)] = True
                masks["lead"] &= ~alternative
                masks["artist2"] = alternative
    roles = []
    names = {"lead": "Основной вокал", "artist2": "Возможно, второй исполнитель"}
    for role_id, mask in masks.items():
        segments = _segments(mask, HOP / RATE)
        if segments:
            roles.append({"id": role_id, "name": names[role_id],
                          "segments": segments, "mask": mask.tolist()})
    return roles


def _profile(vocals):
    """Estimate time-varying level/pan and flag possible echo repeats."""
    if vocals.shape[1] == 1:
        vocals = np.repeat(vocals, 2, axis=1)
    count = math.ceil(len(vocals) / HOP)
    levels, pans, widths = [], [], []
    for i in range(count):
        part = vocals[i * HOP:(i + 1) * HOP]
        rms = np.sqrt(np.mean(part * part, axis=0) + 1e-10)
        levels.append(float(np.mean(rms)))
        pans.append(float((rms[1] - rms[0]) / (rms[0] + rms[1] + 1e-8)))
        left, right = part[:, 0], part[:, 1]
        norms = np.linalg.norm(left) * np.linalg.norm(right)
        coherence = float(np.dot(left, right) / norms) if norms > 1e-8 else 1
        widths.append(float(np.sqrt(max(0, 1 - min(1, coherence ** 2)))))
    floor = max(float(np.percentile(levels, 85)) if levels else 0, 0.005)
    level = np.clip(np.asarray(levels) / floor, 0, 1).tolist()
    active = np.asarray(levels) > max(0.008, floor * 0.16)

    effects = analyze_effects(vocals)
    echo = [bool(effects[min(int(i * HOP / RATE / 4), len(effects)-1)]['delay_wet'] > 0)
            for i in range(count)]
    echo_delay = next((block['delay'] for block in effects if block['delay_wet'] > 0), 0)
    room = float(np.median([block['room'] for block in effects])) if effects else 0
    return {"hop": HOP / RATE, "level": level, "rms": levels, "pan": pans,
            "echo": echo, "echo_delay": echo_delay,
            "room": room, "active": active.tolist(), "width": widths, "effects": effects, "pitch_falls": analyze_pitch_falls(vocals)}


def recover_primary(lead, full_vocals):
    """Recover dominant vocal phrases assigned to the residual by the karaoke model."""
    if full_vocals is None:
        return lead
    full = np.asarray(full_vocals[:len(lead)], dtype=np.float32)
    full = np.pad(full, ((0,max(0,len(lead)-len(full))), (0,0)))
    count = math.ceil(len(lead)/HOP)
    level = np.asarray([np.sqrt(np.mean(full[i*HOP:(i+1)*HOP]**2)) for i in range(count)])
    primary = np.asarray([np.sqrt(np.mean(lead[i*HOP:(i+1)*HOP]**2)) for i in range(count)])
    threshold = max(.004, float(np.percentile(level,85))*.12) if count else .004
    missing = (level > threshold) & (primary < level*.45)
    # Require a phrase, not a transient or a breath; smooth both sides of the join.
    mask = np.zeros(count, np.float32)
    for start,end in _segments(missing,HOP/RATE,minimum=.75):
        mask[round(start*RATE/HOP):round(end*RATE/HOP)] = 1
    weight = np.interp(np.arange(len(lead))/HOP, np.arange(count)+.5, mask) if count else np.zeros(len(lead))
    return (lead*(1-weight[:,None])+full*weight[:,None]).astype(np.float32)


def read_reference(folder, name):
    audio = read_wav(Path(folder)/(name+'.wav'))
    if name == 'lead' and (Path(folder)/'vocals.wav').exists():
        return recover_primary(audio, read_wav(Path(folder)/'vocals.wav'))
    return audio


def analyze(vocals, backing=None, full_vocals=None):
    """Create automatic recording cues and independent reference profiles for each stem."""
    name = "vocals" if backing is None else "lead"
    main_source = recover_primary(vocals, full_vocals)
    main = _profile(main_source)
    roles = suggest_roles(main_source, main["active"], main["width"])
    for role in roles:
        role["reference"] = name
    profiles = {name: main}
    if backing is not None:
        background = _profile(backing)
        back_level = np.asarray(background["rms"])
        main_level = np.asarray(main["rms"])
        threshold = max(0.008, float(np.percentile(main_level, 85)) * 0.12)
        mask = (back_level > threshold) & (back_level > main_level * 0.12)
        segments = _segments(mask,HOP/RATE,minimum=.35)
        if full_vocals is not None:
            # Judge entire phrases: consonants and one overlapped frame are not grounds
            # to discard a short spoken response or a single backing word.
            from voice import track_pitch
            pitch, positions, confidence = track_pitch(np.mean(backing,axis=1))
            accepted=[]
            for start,end in segments:
                portion=(positions>=start)&(positions<end)
                a=backing[round(start*RATE):round(end*RATE)].reshape(-1)
                b=main_source[round(start*RATE):round(end*RATE)].reshape(-1)
                shared=abs(float(np.dot(a,b)))/(float(np.linalg.norm(a)*np.linalg.norm(b))+1e-9)
                voiced=np.mean((pitch[portion]>0)&(confidence[portion]>.55)) if np.any(portion) else 0
                # Spoken/filtered responses need not have a stable fundamental.
                # Accept clear short vocal-band phrases independent of the lead,
                # while retaining the leakage guard for recovered main vocals.
                mono=np.mean(backing[round(start*RATE):round(end*RATE)],axis=1)
                spectrum=abs(np.fft.rfft(mono))**2
                frequencies=np.fft.rfftfreq(len(mono),1/RATE)
                vocal_band=float(np.sum(spectrum[(frequencies>250)&(frequencies<4500)])/(np.sum(spectrum)+1e-12))
                spoken=(end-start<=5 and shared<.35 and vocal_band>.65 and
                        np.sqrt(np.mean(a*a))>threshold*1.5)
                if (voiced>=.3 or spoken) and shared<.65 and np.sqrt(np.mean(b*b))>threshold:
                    accepted.append([start,end])
            segments=accepted
        # Leave one analysis frame around short responses so quiet consonants
        # don't fall outside the selected recording region.
        segments=[[max(0,start-HOP/RATE),min(len(backing)/RATE,end+HOP/RATE)] for start,end in segments]
        mask[:] = False
        for start,end in segments:
            mask[round(start*RATE/HOP):round(end*RATE/HOP)] = True
        if sum(end-start for start,end in segments)>=.5:
            profiles["backing"] = background
            roles.append({"id": "backing", "name": "Дополнительный вокал и реплики",
                          "reference": "backing", "segments": segments, "mask": mask.tolist()})
    proposals=[]
    for reference,profile in profiles.items():
        detected=profile.pop('pitch_falls',[])
        original=full_vocals if reference==name and full_vocals is not None else (main_source if reference==name else backing)
        detected+=analyze_stutters(original)
        detected+=analyze_colours(original)
        for event in detected:
            identity=f"{reference}:{event['type']}:{event['start']:.2f}:{event['end']:.2f}"
            event.update(id=hashlib.sha256(identity.encode()).hexdigest()[:24],reference=reference,status='pending')
            proposals.append(event)
    return {"effect_proposals":proposals, "version": 13, "effect_version": 4, "hop": HOP / RATE, "profiles": profiles, "roles": roles}


def markers(meta):
    found = []
    for name, profile in meta["profiles"].items():
        for i, (pan, echo) in enumerate(zip(profile["pan"], profile["echo"])):
            tags = []
            if pan < -0.3:
                tags.append("слева")
            elif pan > 0.3:
                tags.append("справа")
            if echo:
                tags.append("возможно эхо")
            if tags and (not found or found[-1]["tags"] != tags):
                found.append({"time": round(i * profile["hop"], 2), "tags": tags, "reference": name})
    found.sort(key=lambda marker: marker["time"])
    for name, profile in meta['profiles'].items():
        previous = None
        for block in profile.get('effects', []):
            tags=[]
            if block['room']>.18:tags.append('оценка: объёмное пространство')
            if block['delay_wet']>.08:tags.append('оценка: повторное эхо')
            if block['width']>.6:tags.append('оценка: широкий вокал')
            if tags and tags!=previous:found.append({'time':block['time'],'tags':tags,'reference':name})
            previous=tags
    for event in meta.get('effect_proposals',[]):
        titles={'estimated_pitch_fall':'спад высоты','estimated_stutter':'частые повторы','estimated_colour':'телефонный тембр'}
        found.append({'time':round(event['start'],2),'tags':['предложение: '+titles.get(event['type'],'эффект')],'reference':event['reference']})
    found.sort(key=lambda marker: marker['time'])
    return found[:80]


def pitch_match(voice, reference, profile=None, mode="gentle", settings=None, diagnostics=None, excluded=None):
    """Correct trusted voiced regions while keeping the recorded waveform."""
    from scipy.ndimage import median_filter
    from pitch_shift import shift_waveform
    options=tuning_options(mode,settings)
    profile=tuning_profile(profile,options['voice_type'])
    if len(voice)<RATE//5 or np.max(abs(voice))<1e-7:return voice
    user,times,confidence=track_pitch(voice,profile)
    source,source_times,source_confidence=track_pitch(reference)
    source=np.interp(times,source_times,source)
    source_confidence=np.interp(times,source_times,source_confidence)
    threshold=float((profile or {}).get('adaptive_confidence',.6))
    paired=(user>0)&(source>0)&(confidence>threshold)&(source_confidence>.65)
    for start,end in excluded or []:paired[(times>=start)&(times<=end)]=False
    raw_distance=np.zeros_like(user)
    raw_distance[paired]=12*np.log2(source[paired]/user[paired])
    octave=round(float(np.median(np.log2(source[paired]/user[paired])))) if np.any(paired) else 0
    if options['quantize']:
        active=source>0
        source[active]=440*2**((np.round(69+12*np.log2(source[active]/440))-69)/12)
    distance=np.zeros_like(user)
    distance[paired]=12*np.log2(source[paired]/user[paired])-12*octave
    # Sustained octave discrepancies are register changes or tracking errors,
    # never permission to drag the singer down twelve semitones. A tritone
    # crossing remains a melody correction, with no nearest-octave flips.
    far=paired&(abs(distance)>9)
    edges=np.diff(np.r_[False,far,False].astype(int))
    for lo,hi in zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1)):
        if hi-lo>=15:distance[lo:hi]-=12*round(float(np.median(distance[lo:hi]))/12)
    stable=median_filter(distance,size=3,mode='nearest')
    source_notes=12*np.log2(np.maximum(source,1))
    reference_stable=abs(source_notes-median_filter(source_notes,size=5,mode='nearest'))<.45
    reliable=paired&reference_stable&(abs(distance-stable)<1.5)&(abs(distance)<=9)&(abs(stable)<options['max_semitones'])
    edges=np.diff(np.r_[False,reliable,False].astype(int))
    for lo,hi in zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1)):
        if hi-lo<4:reliable[lo:hi]=False
    desired=stable*(options['strength']/100)
    desired[abs(stable)<options['tolerance_cents']/100]=0
    correction=np.zeros_like(user);current=None
    speed=max(options['speed_ms'],float((profile or {}).get('adaptive_speed_ms',20)))
    response=1-np.exp(-10/speed);user_notes=12*np.log2(np.maximum(user,1))
    for i in range(len(correction)):
        if not reliable[i]:current=None;continue
        if current is None:current=0 if not options['quantize'] else user_notes[i]
        if options['quantize']:
            current+=(user_notes[i]+desired[i]-current)*response
            correction[i]=current-user_notes[i]
        else:
            current+=(desired[i]-current)*response
            correction[i]=current
    if options['strength']==0:correction.fill(0)
    correction[abs(correction)<.02]=0
    result,processed=shift_waveform(voice,user,times,correction,reliable)
    if diagnostics is not None:
        good=(user>0)&(confidence>.7)
        diagnostics.append({'engine':'waveform-psola-v1','mode':mode,'settings':options,
            'effective_speed_ms':speed,'confidence_threshold':threshold,'octave_offset':int(octave),
            'voiced_seconds':round(float(np.count_nonzero(good))*.01,2),
            'trusted_seconds':round(float(np.count_nonzero(reliable))*.01,2),
            'processed_seconds':round(float(processed)*.01,2),
            'voice_range_hz':np.percentile(user[good],[10,50,90]).tolist() if np.any(good) else [],
            'median_confidence':float(np.median(confidence[good])) if np.any(good) else 0,
            'correction_cents':np.percentile(abs(correction[reliable])*100,[50,90]).tolist() if np.any(reliable) else [],
            'input_rms':float(np.sqrt(np.mean(np.asarray(voice,dtype=float)**2))),
            'profile_revision':int((profile or {}).get('adaptive_revision',0))})
        diagnostics[-1]['performance']=performance_report(raw_distance,paired,times)
        diagnostics[-1]['performance'].update(vocal_report(voice,reference,user,times,confidence,paired,raw_distance))
        diagnostics[-1]['timbre']=voice_timbre(voice)
    return result


def performance_report(distance,paired,times):
    """Raw aligned singing, before correction; octave-equivalent notes allowed."""
    error=abs((distance+6)%12-6)*100
    count=int(np.count_nonzero(paired))
    report=dict(compared_seconds=round(count*.01,2),tolerance_cents=50,
                coverage_percent=round(100*count/max(1,len(times)),1),segments=[])
    if count<100:return report
    report.update(hit_percent=round(float(np.mean(error[paired]<=50))*100,1),
                  median_cents=round(float(np.median(error[paired])),1))
    for start in np.arange(0,times[-1],5):
        mask=paired&(times>=start)&(times<start+5)
        if np.count_nonzero(mask)>=50:report['segments'].append(dict(start=float(start),end=float(min(start+5,times[-1])),hit_percent=round(float(np.mean(error[mask]<=50))*100,1)))
    return report


def voice_timbre(voice):
    # Bounded spectral proportions, not a biometric identity or plugin model.
    frames=np.asarray(voice[:len(voice)//2048*2048]).reshape(-1,2048)[::4]
    if not len(frames):return []
    rms=np.sqrt(np.mean(frames**2,axis=1));frames=frames[rms>max(.005,float(np.percentile(rms,85))*.25)]
    if not len(frames):return []
    power=abs(np.fft.rfft(frames*np.hanning(2048),axis=1))**2
    hz=np.fft.rfftfreq(2048,1/RATE);bands=[np.sum(power[:,(hz>=a)&(hz<b)],axis=1) for a,b in zip([80,250,500,1000,2000,4000],[250,500,1000,2000,4000,8000])]
    mean=np.mean(bands,axis=1);return (mean/(np.sum(mean)+1e-12)).tolist()


def vocal_report(voice,reference,pitch,times,confidence,paired,distance):
    """Evidence-based local coaching; never infer health, talent or emotion."""
    from scipy.ndimage import median_filter
    selected=(pitch>0)&(confidence>.7)
    report=dict(analysis='local-measurements',advice=[],strengths=[])
    if np.count_nonzero(selected)<100:
        report['summary']='Недостаточно уверенных нот: итоговая оценка не выставлена.'
        report['advice']=['Запиши короткий фрагмент в тихом месте, удерживая микрофон на постоянном расстоянии.'];return report
    report['range_hz']=np.percentile(pitch[selected],[10,90]).round(1).tolist()
    def envelope(samples):
        size=441;samples=np.asarray(samples,dtype=float)
        return np.sqrt(np.mean(np.pad(samples**2,(0,(-len(samples))%size)).reshape(-1,size),axis=1)+1e-12)
    levels=envelope(voice);active=levels>max(.005,np.percentile(levels,85)*.2)
    report['clipping_percent']=round(float(np.mean(abs(voice)>=.98))*100,3)
    report['level_spread_db']=round(float(20*np.log10(np.percentile(levels[active],90)/max(1e-8,np.percentile(levels[active],10)))),1) if np.any(active) else None
    count=np.count_nonzero(paired)
    if count>=300:
        error=(distance+6)%12-6
        hits=float(np.mean(abs(error[paired])<=.5))*100
        report.update(melody_score=round(hits),summary='Мелодия: '+str(round(hits))+' из 100 по уверенно сравнимым нотам.')
        if hits>=75:report['strengths'].append('Большинство сравнимых нот попали в мелодию.')
        if hits<75:report['advice'].append('Повтори фрагменты с низким попаданием медленнее: сначала пропой мелодию на «м», затем добавь слова.')
        residual=error-median_filter(error,size=21,mode='nearest')
        fluctuation=float(np.percentile(abs(residual[paired])*100,75));report['pitch_fluctuation_cents']=round(fluctuation,1)
        if fluctuation>45:report['advice'].append('На удобной ноте попробуй ровное «у» в течение 3–5 секунд. Сравни начало и конец; вибрато само по себе не считается ошибкой.')
        elif hits>=60:report['strengths'].append('В сравнимых местах высота голоса достаточно устойчива.')
        target=envelope(reference);n=min(len(levels),len(target));a=np.maximum(np.diff(levels[:n],prepend=levels[0]),0);b=np.maximum(np.diff(target[:n],prepend=target[0]),0)
        scores=[]
        for lag in range(-30,31):
            aa=a[max(lag,0):n+min(lag,0)];bb=b[max(-lag,0):n-min(max(lag,0),n)]
            scores.append(float(np.dot(aa,bb)/(np.linalg.norm(aa)*np.linalg.norm(bb)+1e-12)))
        best=int(np.argmax(scores));lag=(best-30)*10
        if scores[best]>.5 and scores[best]>scores[30]*1.15 and abs(lag)>=60:
            report['possible_timing_ms']=lag
            report['advice'].append('Атаки слов могут быть сдвинуты примерно на '+str(abs(lag))+' мс. Проверь задержку под музыку, прежде чем оценивать ритм своего пения.')
    else:report['summary']='Диапазон измерен, но для оценки мелодии слишком мало совпавших уверенных участков.'
    if report['clipping_percent']>.1:report['advice'].insert(0,'Запись перегружается: уменьши усиление микрофона и перезапиши громкие места.')
    elif report['level_spread_db'] is not None and report['level_spread_db']>18:report['advice'].append('Громкость сильно меняется. Проверь расстояние до микрофона и сравни тихую фразу с громкой; часть перепадов может быть задумкой песни.')
    if not report['advice']:report['advice']=['Продолжай с короткими фрагментами: прослушай сухую запись и повтори самый сложный переход между нотами.']
    report['advice']=report['advice'][:3]
    report['limits']='Оценка касается высоты и записи, а не красоты тембра или артистизма. Разделение, шум, гармонии и задержка могут влиять на результат.'
    return report


def _tone_match(voice, reference, mask, personal=None):
    """Match broad brightness, with tight limits to avoid extreme EQ."""
    def lowpass(samples):
        width = 25
        summed = np.cumsum(np.pad(samples, (width, 0)), dtype=np.float64)
        return ((summed[width:] - summed[:-width]) / width).astype(np.float32)
    voice_low = lowpass(voice)
    reference_low = lowpass(reference)
    selected = mask > 0.5
    if np.count_nonzero(selected) < RATE:
        return voice
    def balance(full, low):
        return np.sqrt(np.mean((full[selected] - low[selected]) ** 2)) / (np.sqrt(np.mean(low[selected] ** 2)) + 1e-5)
    # Liked examples identify a voice to preserve. Bound the reference EQ more
    # tightly instead of colouring a familiar timbre aggressively.
    limits=(.85,1.18) if (personal or {}).get('adaptive_timbre') else (.65,1.6)
    tilt = np.clip(balance(reference, reference_low) / (balance(voice, voice_low) + 1e-5), *limits)
    return voice_low + (voice - voice_low) * tilt


def _smooth(values):
    return np.convolve(np.pad(values, (1, 1), mode="edge"), [0.2, 0.6, 0.2], mode="valid")


def _stable_vocal_gain(measured, target):
    """Set a phrase-level gain, with slow and limited changes instead of chasing every syllable."""
    from scipy.ndimage import uniform_filter1d
    nonzero = measured[measured > 1e-6]
    if not len(nonzero):
        return np.ones_like(measured)
    # Count sung phrases, not the microphone's noise during a mostly silent
    # backing take. Otherwise its noise defines the gain (often the 40x cap).
    floor = max(1e-6, float(np.percentile(nonzero, 90)) * .10)
    active = (measured > floor) & (target > 1e-6)
    if not np.any(active):
        return np.ones_like(measured)
    base = np.clip(np.percentile(target[active], 60) / np.percentile(measured[active], 70), .1, 40)
    desired = np.clip(target / np.maximum(measured, floor), base * .65, base * 1.55)
    desired[~active] = base
    return np.exp(uniform_filter1d(np.log(desired), size=9, mode='nearest'))


def _limit_mix(samples):
    """Limit only the neighbourhood of a peak; keep the rest of the song at its intended level."""
    from scipy.ndimage import maximum_filter1d, uniform_filter1d
    peak = np.max(np.abs(samples), axis=1)
    held = maximum_filter1d(peak, size=round(.08 * RATE) | 1, mode='nearest')
    gain = np.minimum(1, .98 / np.maximum(held, 1e-6))
    gain = uniform_filter1d(gain, size=round(.003 * RATE) | 1, mode='nearest')
    return np.clip(samples * gain[:, None], -.98, .98)


def role_guide(reference, role, hop):
    return reference * role_envelope(role, hop, len(reference))[:, None]


def role_envelope(role, hop, total):
    times = np.arange(total) / RATE
    mask = _smooth(effective_mask(role, hop))
    envelope = np.interp(times / hop, np.arange(len(mask)), mask).astype(np.float32)
    return envelope * exclusion_envelope(role, total)


def exclusion_envelope(role, total):
    times = np.arange(total) / RATE
    envelope = np.ones(total, np.float32)
    for start, end in role.get('excluded', []):
        envelope[(times >= start) & (times < end)] = 0
        before = (times >= start - .012) & (times < start)
        after = (times >= end) & (times < end + .012)
        envelope[before] *= (start - times[before]) / .012
        envelope[after] *= (times[after] - end) / .012
    return envelope


def mix(instrumental, references, tracks, meta, autotune=True, vocal_db=0, space='auto', voice_profile=None, tune_mode='gentle', tune_settings=None, pitch_falls=True, diagnostics=None):
    """Combine clips by role (latest overlap wins), then process each assembled voice once."""
    if instrumental.shape[1] == 1:
        instrumental = np.repeat(instrumental, 2, axis=1)
    result = instrumental.copy()
    total = len(result)
    times = np.arange(total) / RATE
    roles = {role["id"]: role for role in meta["roles"]}
    assembled = {}
    for item in tracks:
        if isinstance(item, dict):
            voice, offset, role_id = item["voice"], item.get("offset", 0), item["role"]
            start, end = item.get("start", 0), item.get("end", total / RATE)
            region = item.get("region", [start, end])
        else:
            voice, offset, role_id = item
            start, region = 0, [0, total / RATE]
        aligned = assembled.setdefault(role_id, np.zeros(total, np.float32))
        at = round((start + offset) * RATE)
        lo = max(0, at, round(region[0] * RATE))
        hi = min(total, at + len(voice), round(region[1] * RATE))
        if hi > lo:
            window = np.ones(hi - lo, np.float32)
            edge = min(round(.012 * RATE), len(window) // 3)
            if edge:
                window[:edge] = np.linspace(0, 1, edge)
                window[-edge:] = np.linspace(1, 0, edge)
            fresh = np.asarray(voice, np.float32).reshape(-1)[lo - at:hi - at]
            aligned[lo:hi] = aligned[lo:hi] * (1 - window) + fresh * window
    tracks = [(voice, 0, role) for role, voice in assembled.items()]
    overlap = {name: np.zeros(len(profile["rms"]), np.float32) for name, profile in meta["profiles"].items()}
    effects_by_reference = {}
    for _, _, role_id in tracks:
        role = roles[role_id]
        overlap[role["reference"]] += effective_mask(role, meta["hop"])
    for voice, offset, role_id in tracks:
        role = roles[role_id]
        profile = meta["profiles"][role["reference"]]
        source = np.mean(references[role["reference"]], axis=1)
        source = np.pad(source[:total], (0, max(0, total - len(source))))
        frame = np.minimum((times / profile["hop"]).astype(int), len(profile["rms"]) - 1)
        pan = np.interp(times / profile['hop'], np.arange(len(profile['pan'])), _smooth(profile['pan']))
        voice = np.asarray(voice, dtype=np.float32).reshape(-1)
        aligned = np.zeros(total, np.float32)
        at = round(offset * RATE)
        dst_begin, src_begin = max(0, at), max(0, -at)
        available = min(total - dst_begin, len(voice) - src_begin)
        if available <= 0:
            continue
        aligned[dst_begin:dst_begin + available] = voice[src_begin:src_begin + available]
        sample_mask = role_envelope(role, meta['hop'], total)
        # A detector is a recording guide, not permission to delete a sung phrase.
        # Explicit user exclusions and selected clip regions still apply.
        aligned *= exclusion_envelope(role, total)
        pitch_source = references.get('lead') if role_id != 'backing' else None
        if pitch_source is not None:
            pitch_source = np.mean(pitch_source, axis=1)
            pitch_source = np.pad(pitch_source[:total], (0, max(0, total-len(pitch_source))))
        excluded=[(event['start'],event['end']) for event in meta.get('effect_proposals',[]) if 'start' in event and 'end' in event and event['reference']==role['reference'] and event['type'] in {'estimated_stutter','estimated_pitch_fall'} and event.get('status')=='approved']
        before=len(diagnostics) if diagnostics is not None else 0
        options=dict(tune_settings or {})
        if not autotune:options['strength']=0
        aligned = pitch_match(aligned,pitch_source if pitch_source is not None else source,voice_profile,tune_mode,options,diagnostics,excluded)
        if diagnostics is not None and len(diagnostics)>before:diagnostics[-1]['role']=role_id
        aligned = vocal_dynamics(_tone_match(aligned, source, sample_mask, voice_profile))
        if pitch_falls:
            approved=[event for event in meta.get('effect_proposals',[]) if event.get('status')=='approved' and event['reference']==role['reference']]
            aligned = render_pitch_falls(aligned,[event for event in approved if event['type']=='estimated_pitch_fall'],voice_profile)
            aligned = render_stutters(aligned,[event for event in approved if event['type']=='estimated_stutter'])
            aligned = render_colours(aligned,[event for event in approved if event['type']=='estimated_colour'])
        measured = np.asarray([np.sqrt(np.mean(aligned[i:i + HOP] ** 2))
                               for i in range(0, total, HOP)])
        original_rms = np.asarray(profile["rms"])
        original_rms = np.pad(original_rms, (0, max(0, len(measured) - len(original_rms))))[:len(measured)]
        simultaneous = overlap[role["reference"]]
        simultaneous = np.pad(simultaneous, (0, max(0, len(measured) - len(simultaneous))))[:len(measured)]
        # render_effects splits mono between two channels. Match the original
        # per-channel level; music must not impose a minimum on backing vocals.
        target = 2 * original_rms / np.maximum(simultaneous, 1)
        dynamic_gain = _stable_vocal_gain(measured, target)
        dry = aligned * np.interp(times / meta["hop"], np.arange(len(dynamic_gain)), dynamic_gain) * 10 ** (vocal_db / 20)
        if space in {'distant', 'telephone', 'radio'}:
            from scipy.signal import butter, sosfilt
            if space == 'distant':
                dry = sosfilt(butter(2, 3800, fs=RATE, output='sos'), dry) * 0.8
            else:
                dry = sosfilt(butter(2, [350, 3300], btype='bandpass', fs=RATE, output='sos'), dry)
                if space == 'radio':
                    dry = np.tanh(dry * 3) / 2
        blocks = []
        if space=='auto':
            name=role['reference']
            if name not in effects_by_reference:
                effects_by_reference[name]=analyze_effects(references[name])
                if name=='lead' and 'vocals' in references:
                    # Separation may put the main singer's ambience in the
                    # residual stem. Recover evidenced room, never copy its F0.
                    ambient=analyze_effects(references['vocals'])
                    for block,original in zip(effects_by_reference[name],ambient):
                        if not block['room'] and original['room']>0:
                            block.update(room=original['room'],decay=original['decay'],room_from_full_vocal=True)
            blocks=effects_by_reference[name]
        if diagnostics is not None:
            diagnostics.append({'stage':'mix','role':role_id,'reference':role['reference'],'space':space,
                'automatic_gain_db':(20*np.log10(np.maximum(np.percentile(dynamic_gain,[10,50,90]),1e-8))).tolist(),
                'vocal_db':vocal_db,'pan_range':np.percentile(pan,[10,90]).tolist(),'effects':blocks,
                'approved_effect_ids':[e['id'] for e in meta.get('effect_proposals',[]) if pitch_falls and e.get('status')=='approved' and e['reference']==role['reference']]})
        result += render_effects(dry, pan, blocks, space) * exclusion_envelope(role, total)[:,None]
    return _limit_mix(result) if len(result) else result


def save_meta(path, meta):
    target=Path(path);pending=target.with_suffix('.tmp')
    pending.write_text(json.dumps(meta),encoding='utf-8');pending.replace(target)


def effective_mask(role, hop):
    mask = np.asarray(role["mask"], dtype=np.float32).copy()
    for start, end in role.get("excluded", []):
        mask[max(0, math.floor(start / hop)):math.ceil(end / hop)] = 0
    return mask
