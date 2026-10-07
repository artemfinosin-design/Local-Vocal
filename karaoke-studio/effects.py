"""Local effect estimation and deterministic, stereo vocal DSP. No pitch shifting."""
from functools import lru_cache
from pathlib import Path
import json
import numpy as np
from scipy.signal import lfilter, butter, sosfilt, oaconvolve, resample_poly, correlate, find_peaks
from scipy.ndimage import uniform_filter1d, maximum_filter1d

RATE = 44100
MODEL = Path(__file__).resolve().parent / 'models' / 'vocal-effects.npz'
REPORT = MODEL.with_suffix('.json')
PARAMETERS = ['room', 'decay', 'delay_wet', 'width']
CHARACTER_MODES = {'chorus','doubler','flanger','phaser','tremolo','autopan','distortion','crush'}
SPACE_MODES = CHARACTER_MODES | {'auto','dry','room','hall','plate','distant','slap','pingpong','wide','telephone','radio'}


@lru_cache(maxsize=64)
def impulse(rate, decay, predelay=.025, damping=6500):
    """Decorrelated early reflections and dense, damped -60 dB late field."""
    decay = float(np.clip(decay, .2, 3))
    rng = np.random.default_rng(173)
    length = round(rate * decay)
    t = np.arange(length) / rate
    noise = rng.normal(size=(length, 2))
    noise = sosfilt(butter(2, min(damping, rate * .35), fs=rate, output='sos'), noise, axis=0)
    # Increasing density prevents a burst at the start of the late field.
    tail = noise * (np.exp(-6.91 * t / decay) * (1 - np.exp(-t / .035)))[:, None]
    tail /= np.sqrt(np.sum(tail ** 2, axis=0))[None, :] + 1e-9
    tail *= .65
    tail = np.pad(tail, ((round(predelay * rate), 0), (0, 0)))
    for channel in (0, 1):
        for seconds, amplitude in ((.011, .34), (.023, .27), (.039, .20), (.061, .14)):
            at = round((predelay + seconds + channel * .004) * rate)
            if at < len(tail):
                tail[at, channel] += amplitude
    return tail.astype(np.float32)


def spatial(voice, rate, room=0, decay=.8, delay_wet=0, delay=.28, width=0, damping=6500):
    """Wet sends only. All delayed repeats are fed from the original signal."""
    voice = np.asarray(voice, np.float32)
    tail = round(rate * max(decay + .12 if room else 0, delay * 6 if delay_wet else 0, .24 if width else .024))
    output = np.zeros((len(voice) + tail, 2), np.float32)
    if room > 0:
        ir = impulse(rate, round(float(decay), 2), damping=round(float(damping)/125)*125)
        for channel in (0, 1):
            reverberated = oaconvolve(voice, ir[:, channel])
            output[:min(len(output), len(reverberated)), channel] += reverberated[:len(output)] * room
    if delay_wet > 0:
        damped = sosfilt(butter(1, min(4800, rate * .35), fs=rate, output='sos'), voice)
        for repeat in range(1, 7):
            at = round(rate * delay * repeat)
            stop = min(len(output), at + len(voice))
            if stop > at:
                output[at:stop, repeat % 2] += damped[:stop-at] * delay_wet * .42 ** (repeat-1)
    if width > 0:
        # One opposite-polarity 19ms copy creates comb-filter coloration in each
        # ear. Use a short diffuse side field; mono sum still preserves dry voice.
        ir=impulse(rate,.18,predelay=.008)
        side_ir=(ir[:,0]-ir[:,1])*.5
        side=oaconvolve(voice,side_ir)*width*.18
        stop=min(len(output),len(side));output[:stop,0]+=side[:stop];output[:stop,1]-=side[:stop]
    return output


def features(samples, rate=11025):
    """Gain-invariant envelope, decay, spectral and stereo evidence."""
    samples = np.asarray(samples)
    if samples.ndim == 1:
        samples = np.column_stack((samples, samples))
    mono = np.mean(samples, axis=1)
    size = max(1, round(rate * .01))
    padded = np.pad(mono ** 2, (0, (-len(mono)) % size))
    env = np.sqrt(np.mean(padded.reshape(-1, size), axis=1) + 1e-12)
    env /= max(float(np.percentile(env, 90)), 1e-6)
    novelty = np.maximum(np.diff(env, prepend=env[0]), 0)
    corr = []
    for lag in range(8, 61, 2):
        a, b = novelty[lag:], novelty[:-lag]
        corr.append(float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)))
    drops = np.flatnonzero((env[:-1] > .45) & (env[1:] < env[:-1] * .82))
    tails = [np.median([env[i + k] / max(env[i], 1e-6) for i in drops if i+k < len(env)])
             if any(i+k < len(env) for i in drops) else 0 for k in (5, 10, 20, 40, 70)]
    frame = 1024
    if len(mono) < frame:
        mono = np.pad(mono, (0, frame - len(mono)))
    frames = np.lib.stride_tricks.sliding_window_view(mono, frame)[::512]
    spectrum = np.mean(abs(np.fft.rfft(frames * np.hanning(frame))), axis=0)
    frequencies = np.fft.rfftfreq(frame, 1/rate)
    bands = [np.sum(spectrum[(frequencies >= lo) & (frequencies < hi)]) for lo, hi in
             ((80, 250), (250, 600), (600, 1500), (1500, 3000), (3000, 5000))]
    bands = np.asarray(bands) / (sum(bands) + 1e-9)
    mid, side = np.mean(samples, axis=1), (samples[:, 0] - samples[:, 1]) / 2
    stereo = np.sqrt(np.mean(side ** 2) / (np.mean(mid ** 2) + 1e-9))
    stereo_features = []
    for signal in (mid, side):
        filtered = sosfilt(butter(2, 1800, btype='highpass', fs=rate, output='sos'), signal)
        stereo_features.append(float(np.sqrt(np.mean(filtered**2)/(np.mean(signal**2)+1e-9))))
    for milliseconds in (11, 19, 23, 39, 61, 110, 280):
        lag = round(rate*milliseconds/1000)
        a, b = side[lag:], mid[:-lag]
        stereo_features.append(float(np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b)+1e-9)))
    vector = np.r_[np.percentile(env, [10, 25, 50, 75, 95]), corr, tails, bands,
                   min(stereo, 3), np.mean(env < .08), stereo_features]
    best = int(np.argmax(corr))
    return np.nan_to_num(vector), (8 + best * 2) * .01, corr[best]


@lru_cache(maxsize=2)
def _load_model(stamp):
    with np.load(MODEL, allow_pickle=False) as saved:
        return {key: saved[key].copy() for key in saved.files}


def _predict(vector, model):
    predictions = []
    for root in model['roots']:
        node = int(root)
        while model['left'][node] >= 0:
            node = int(model['left'][node] if vector[model['feature'][node]] <= model['threshold'][node] else model['right'][node])
        predictions.append(model['value'][node])
    return np.mean(predictions, axis=0)


def delay_evidence(samples, rate):
    """Find attenuated copies of actual waveform endings, not rhythmic envelopes."""
    mono = np.mean(samples, axis=1) if samples.ndim == 2 else samples
    hop = max(1, round(rate * .01))
    if len(mono) < rate or np.max(np.abs(mono)) < 1e-6:
        return 0., 0., 0.
    padded = np.pad(mono ** 2, (0, (-len(mono)) % hop))
    env = np.sqrt(np.mean(padded.reshape(-1, hop), axis=1) + 1e-16)
    drops = np.flatnonzero((env[:-1] > np.percentile(env, 85) * .2) &
                           (env[1:] < env[:-1] * .55))
    signal = sosfilt(butter(2, [350, min(4800, rate * .4)], btype='bandpass', fs=rate, output='sos'), mono)
    matches = []
    for frame in drops[:80]:
        end = (frame + 1) * hop
        width = round(rate * .06)
        if end < width or end + round(rate * .7) >= len(signal):
            continue
        template = signal[end-width:end]
        spectrum = np.abs(np.fft.rfft(template * np.hanning(width))) ** 2
        frequencies = np.fft.rfftfreq(width, 1 / rate)
        center = np.sum(spectrum * frequencies) / (np.sum(spectrum) + 1e-12)
        bandwidth = np.sqrt(np.sum(spectrum * (frequencies-center)**2) / (np.sum(spectrum)+1e-12))
        if bandwidth < 300:
            continue  # Sustained periodic vowels alone cannot establish a copied transient.
        first = end - width + round(rate * .08)
        search = signal[first:end + round(rate * .6)]
        energy = np.convolve(search ** 2, np.ones(width), mode='valid')
        norm = np.dot(template, template)
        scores = correlate(search, template, mode='valid', method='fft') / np.sqrt(np.maximum(energy * norm, 1e-20))
        ratios = np.sqrt(energy / max(norm, 1e-20))
        peaks, _ = find_peaks(scores, height=.84, distance=round(rate * .015))
        for peak in peaks:
            ratio = ratios[peak]
            lag = (first + peak - (end-width)) / rate
            if .08 <= lag <= .6 and .025 <= ratio <= .65:
                matches.append((lag, float(ratio), float(scores[peak]), end))
    for lag, _, _, _ in sorted(matches, key=lambda item: item[2], reverse=True):
        same = [item for item in matches if abs(item[0] - lag) < .002]
        if len({item[3] for item in same}) >= 2:
            return lag, float(np.clip(np.median([item[1] for item in same]) * .5, 0, .3)), float(np.mean([item[2] for item in same]))
    return 0., 0., 0.


def estimate(samples, rate=RATE, learned=True):
    reduced = resample_poly(samples, 1, 4, axis=0) if rate == RATE else samples
    vector, delay, confidence = features(reduced, 11025 if rate == RATE else rate)
    # Natural pauses and repeated lyrics remain ambiguous: keep the fallback modest.
    room = float(np.clip(np.mean(vector[32:37]) * .10, 0, .15))
    # Estimate decay only from long, consistently falling envelopes, not single syllables.
    mono = np.mean(reduced,axis=1) if reduced.ndim==2 else reduced
    hop = 220 if rate==RATE else max(1,round(rate*.02))
    padded = np.pad(mono**2,(0,(-len(mono))%hop))
    envelope = np.sqrt(np.mean(padded.reshape(-1,hop),axis=1)+1e-12)
    # Repeated abrupt clean endings are negative evidence. Continuous singing
    # with no exposed tail is merely inconclusive, not evidence of dry sound.
    dry_endings=0
    ending_floor=max(.004,float(np.percentile(envelope,85))*.2)
    for at in range(1,len(envelope)-31):
        if envelope[at-1]>ending_floor and envelope[at]<envelope[at-1]*.01:
            if np.max(envelope[at:at+30])<envelope[at-1]*.01:dry_endings+=1
    decays=[]
    for at in range(0,len(envelope)-30,5):
        part=envelope[at:at+30]
        if part[0]<.004 or part[-1]>part[0]*.20 or np.min(part)<1e-5:
            continue
        log=np.log10(part)
        slope,intercept=np.polyfit(np.arange(30)*.02,log,1)
        fit=intercept+slope*np.arange(30)*.02
        quality=1-np.sum((log-fit)**2)/(np.sum((log-log.mean())**2)+1e-9)
        if quality>.92 and slope<-.5:
            decays.append(float(np.clip(-3/slope,.3,2.5)))
    decay=float(np.median(decays)) if decays else .8
    measured_delay, measured_wet, delay_confidence = delay_evidence(reduced, 11025 if rate == RATE else rate)
    # Remove static panning before estimating width: a dry voice in one ear
    # must not acquire an invented diffuse stereo effect.
    if reduced.ndim==2:
        side=(reduced[:,0]-reduced[:,1])/2
        side-=mono*float(np.dot(side,mono)/(np.dot(mono,mono)+1e-12))
        stereo_ratio=float(np.sqrt(np.mean(side**2)/(np.mean(mono**2)+1e-12)))
    else:side=np.zeros_like(mono);stereo_ratio=0
    # A model trained by adding effects to already processed vocals is not evidence
    # that an effect exists. Require waveform copies / diffuse measured tails first.
    diffuse_tail = False
    if decays and reduced.ndim == 2:
        quiet = np.repeat(envelope < np.percentile(envelope, 85) * .12, hop)[:len(mono)]
        if np.count_nonzero(quiet) > len(mono) * .05:
            ratio = np.sqrt(np.mean(side[quiet] ** 2) / (np.mean(mono[quiet] ** 2) + 1e-12))
            diffuse_tail = ratio > max(.25, stereo_ratio * 1.4)
    result = np.array([room if diffuse_tail else 0, decay, measured_wet, np.clip(stereo_ratio, 0, 1)])
    enabled = np.zeros(4, bool)
    if learned and MODEL.exists():
        model = _load_model(MODEL.stat().st_mtime_ns)
        predicted = _predict(vector, model)
        enabled = model['enabled'].astype(bool)
        result[enabled] = predicted[enabled]
    # Models may refine measured effects, but may never invent a wet send.
    result[0] = min(result[0], .18) if diffuse_tail else 0
    result[2] = measured_wet
    result[3] = float(np.clip(stereo_ratio, 0, 1)) if stereo_ratio > .12 else 0
    enabled[[0, 2, 3]] &= [diffuse_tail, False, False]
    delay = measured_delay if measured_wet else .28
    result = np.clip(result, [0, .2, 0, 0], [.4, 2.5, .35, 1])
    if np.sqrt(np.mean(reduced ** 2)) < .001:
        result[[0, 2, 3]] = 0
    damping=6500
    if diffuse_tail and np.count_nonzero(quiet)>1024:
        # Tail colour from the diffuse channel; dry sibilants do not set it.
        edges=np.diff(np.r_[False,quiet,False].astype(int))
        spans=list(zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1)))
        lo,hi=max(spans,key=lambda bounds:bounds[1]-bounds[0])
        if hi-lo>=1024:
            tail=side[lo:min(hi,lo+11025)]
            spectrum=abs(np.fft.rfft(tail*np.hanning(len(tail))))**2
            frequencies=np.fft.rfftfreq(len(tail),1/(11025 if rate==RATE else rate))
            centroid=float(np.sum(spectrum*frequencies)/(np.sum(spectrum)+1e-12))
            damping=float(np.clip(centroid*2.5,1800,8000))
    return dict(zip(PARAMETERS, map(float, result)), delay=delay,damping=damping,
                confidence=float(delay_confidence), decay_evidence=len(decays),
                dry_evidence=dry_endings, active=bool(np.sqrt(np.mean(reduced**2))>=.001), learned=enabled.tolist())


def analyze_effects(samples):
    """One independent estimate per four seconds, including neighbouring tails."""
    blocks = []
    for at in range(0, len(samples), RATE * 4):
        part = samples[max(0, at-RATE):min(len(samples), at+RATE*5)]
        blocks.append({'time': at/RATE, **estimate(part)})
    trusted=[b for b in blocks if b['room']>0 and (b['decay_evidence']>=2 or
        any(other is not b and other['room']>0 and other['decay_evidence']>=1
            and abs(other['time']-b['time'])<=4 and
            abs(other['decay']-b['decay'])<.25 for other in blocks))]
    # Keep a measured send through acoustically consistent singing until a dry
    # ending, silence or changed stereo scene contradicts it. No time cutoff.
    echoes=[b for b in blocks if b['delay_wet']>0 and b['confidence']>=.84]
    for field,parameters,support in (('room',('room','decay','damping'),trusted),
                                     ('delay_wet',('delay_wet','delay'),echoes)):
        anchor=None
        for block in blocks:
            if block in support:anchor=block
            if not block.get('active',True) or block.get('dry_evidence',0)>=2:
                anchor=None
                continue
            if anchor and abs(block['width']-anchor['width'])>max(.12,anchor['width']*.35):anchor=None
            if block[field] or not support:continue
            nearest=anchor or min(support,key=lambda b:abs(b['time']-block['time']))
            if anchor or (abs(nearest['time']-block['time'])<=4 and
                    abs(nearest['width']-block['width'])<=max(.12,nearest['width']*.35)):
                block.update({key:nearest[key] for key in parameters if key in nearest})
                block['room_inherited' if field=='room' else 'delay_inherited']=True
    return blocks


def vocal_dynamics(voice):
    """Gentle soft-knee compression and dynamic sibilance reduction, no register change."""
    voice = np.asarray(voice, np.float32)
    if not len(voice):
        return voice
    input_peak=float(np.max(abs(voice)))
    voice=sosfilt(butter(2,45,btype='highpass',fs=RATE,output='sos'),voice).astype(np.float32)
    detector = np.sqrt(uniform_filter1d(voice ** 2, round(RATE*.015), mode='nearest') + 1e-10)
    active=detector>max(1e-5,float(np.percentile(detector,90))*.1)
    if not np.any(active):return voice
    threshold=max(1e-5,float(np.percentile(detector[active],70))*.85)
    db = 20 * np.log10(detector / threshold + 1e-8)
    knee = 6
    reduction = np.where(db < -knee/2, 0, np.where(db > knee/2, db*.5, (db+knee/2)**2/(4*knee)))
    held = maximum_filter1d(reduction, round(RATE*.025)|1, mode='nearest')
    gain = 10 ** (-uniform_filter1d(held, round(RATE*.07), mode='nearest') / 20)
    high = sosfilt(butter(2, 5500, btype='highpass', fs=RATE, output='sos'), voice)
    high_rms = np.sqrt(uniform_filter1d(high**2, round(RATE*.025), mode='nearest') + 1e-10)
    deess = np.clip((high_rms/(detector+1e-6) - .42)*.7, 0, .35)
    output=((voice-high*deess)*gain).astype(np.float32)
    output*=min(1.,input_peak/(float(np.max(abs(output)))+1e-12))
    return output


def character_effect(voice,pan,kind):
    """Common studio effects with bounded wet mixes and sample-continuous modulation."""
    voice=np.asarray(voice,np.float32);times=np.arange(len(voice))/RATE
    if kind=='autopan':pan=.85*np.sin(2*np.pi*.5*times)
    if kind=='tremolo':voice=voice*(.7+.3*np.sin(2*np.pi*5*times))
    if kind=='distortion':voice=np.tanh(voice*5)/3
    if kind=='crush':
        held=np.repeat(voice[::6],6)[:len(voice)]
        voice=voice*.3+np.round(np.clip(held,-1,1)*32)/32*.7
    stereo=np.column_stack([voice*(1-pan)/2,voice*(1+pan)/2]).astype(np.float32)
    if kind in {'chorus','doubler','flanger'}:
        samples=np.arange(len(voice))
        for channel in (0,1):
            if kind=='chorus':delay=.020+.006*np.sin(2*np.pi*.7*times+channel*np.pi);wet=.22
            elif kind=='doubler':delay=.018+channel*.009;wet=.22
            else:delay=.0015+.0013*np.sin(2*np.pi*.22*times+channel*.4);wet=.3
            delayed=np.interp(samples-np.asarray(delay)*RATE,samples,voice,left=0)
            stereo[:,channel]=(stereo[:,channel]+delayed*wet)/(1+wet)
    if kind=='phaser':
        filtered=np.zeros_like(voice);states=np.zeros((4,1))
        for start in range(0,len(voice),441):
            frequency=250+1200*(.5+.5*np.sin(2*np.pi*.4*start/RATE))
            tangent=np.tan(np.pi*frequency/RATE);coefficient=(1-tangent)/(1+tangent)
            block=voice[start:start+441].astype(float)
            for stage in range(4):block,states[stage]=lfilter([-coefficient,1],[1,-coefficient],block,zi=states[stage])
            filtered[start:start+len(block)]=block
        shifted=np.column_stack([filtered*(1-pan)/2,filtered*(1+pan)/2])
        stereo=stereo*.6+shifted*.4
    return stereo.astype(np.float32)


def render_effects(voice, pan, blocks, space='auto'):
    if space in CHARACTER_MODES:return character_effect(voice,pan,space)
    stereo = np.column_stack((voice*(1-pan)/2, voice*(1+pan)/2)).astype(np.float32)
    if space in {'dry', 'telephone', 'radio'}:
        return stereo
    presets = {'room':(.20,.55,0,.28,0), 'hall':(.30,2.4,0,.28,.2),
               'plate':(.24,1.5,0,.28,.15), 'distant':(.38,2,0,.28,.15),
               'slap':(0,.3,.25,.11,0), 'pingpong':(.07,.5,.30,.28,0), 'wide':(0,.3,0,.28,1)}
    if space != 'auto':
        wet = spatial(voice, RATE, *presets[space])
        return stereo + wet[:len(voice)]
    # Overlap-add on the SEND keeps dry voice intact and preserves effect tails at boundaries.
    step = RATE*4
    for index, block in enumerate(blocks):
        start = max(0, index*step - RATE//2)
        end = min(len(voice), (index+1)*step + RATE//2)
        if end <= start:
            continue
        envelope = np.ones(end-start, np.float32)
        if index:
            envelope[:RATE] = np.linspace(0, 1, min(RATE, len(envelope)))
        if end < len(voice):
            envelope[-RATE:] = np.linspace(1, 0, min(RATE, len(envelope)))
        wet = spatial(voice[start:end]*envelope, RATE, block['room'], block['decay'],
                      block['delay_wet'], block['delay'], block['width'],block.get('damping',6500))
        stop = min(len(voice), start+len(wet))
        stereo[start:stop] += wet[:stop-start]
    return stereo


def train(paths, status=lambda message: None):
    """Supervised synthetic augmentation. Split source clips BEFORE augmentation."""
    from audio_core import read_wav
    rng = np.random.default_rng(729)
    sets = [[], [], []]
    source_names = []
    for path in paths:
        source = resample_poly(read_wav(path), 1, 4, axis=0)
        source_names.append(Path(path).name)
        candidates = [at for at in range(0, len(source)-11025*4, 11025*8)
                      if np.sqrt(np.mean(source[at:at+11025*4]**2)) > .006]
        rng.shuffle(candidates)
        for clip_index, at in enumerate(candidates[:16]):
            # Dry source identity never appears in both train and validation sets.
            dry = np.mean(source[at:at+11025*4], axis=1)
            for variant in range(8):
                params = [float(rng.uniform(0,.4)), float(rng.uniform(.3,2.5)),
                          float(rng.uniform(0,.35)), float(rng.uniform(0,1))]
                for index in (0, 2, 3):
                    if variant == 0 or rng.random() < .35: params[index] = 0.
                delay = float(rng.choice(np.arange(.10,.61,.02)))
                wet = spatial(dry, 11025, params[0], params[1], params[2], delay, params[3])
                wet[:len(dry)] += dry[:,None] * .5
                wet = np.pad(wet, ((0, max(0, 11025*7-len(wet))), (0,0)))[:11025*7]
                vector, _, _ = features(wet)
                partition = 2 if clip_index % 5 == 0 else 1 if clip_index % 5 == 1 else 0
                sets[partition].append((vector, params))
            status(f'Создаю примеры: {sum(map(len,sets))}')
    if min(map(len, sets)) < 16:
        raise ValueError('Нужно больше вокальных фрагментов: хотя бы 40 секунд активного голоса')
    x, y = map(np.asarray, zip(*sets[0]))
    vx, vy = map(np.asarray, zip(*sets[1]))
    tx, ty = map(np.asarray, zip(*sets[2]))
    from sklearn.ensemble import ExtraTreesRegressor
    best = None
    for depth in (4, 8, 12):
        estimator = ExtraTreesRegressor(n_estimators=80, max_depth=depth, min_samples_leaf=3, random_state=729)
        estimator.fit(x, y)
        prediction = estimator.predict(vx)
        error = np.mean(abs(prediction-vy), axis=0)
        if best is None or np.sum(error / [ .4,2.3,.35,1]) < best[0]:
            best = (np.sum(error / [.4,2.3,.35,1]), estimator, error)
    _, estimator, validation_error = best
    test_prediction = estimator.predict(tx)
    error = np.mean(abs(test_prediction-ty), axis=0)
    baseline = np.mean(abs(ty-y.mean(0)), axis=0)
    enabled = error < baseline * .9
    report = {'version':1, 'sources':source_names, 'train_examples':len(x), 'validation_examples':len(vx),
              'test_examples':len(tx), 'parameters':PARAMETERS, 'validation_mae':validation_error.tolist(),
              'test_mae':error.tolist(), 'baseline_mae':baseline.tolist(),
              'enabled':enabled.tolist(), 'scope':'Оценка синтетически добавленной обработки. Исходные эффекты образцов неизвестны.',
              'split':'Непересекающиеся исходные фрагменты; параметры подбираются на проверочной выборке.',
              'estimator':'ExtraTrees, 80 деревьев; безопасные числовые массивы без pickle'}
    MODEL.parent.mkdir(exist_ok=True)
    pending = MODEL.with_name('vocal-effects-pending.npz')
    exported = {key:[] for key in ('left','right','feature','threshold','value')}
    roots = []
    offset = 0
    for tree in estimator.estimators_:
        data = tree.tree_
        roots.append(offset)
        exported['left'].append(np.where(data.children_left < 0, -1, data.children_left+offset))
        exported['right'].append(np.where(data.children_right < 0, -1, data.children_right+offset))
        exported['feature'].append(data.feature)
        exported['threshold'].append(data.threshold)
        exported['value'].append(data.value[:,:,0])
        offset += data.node_count
    exported = {key:np.concatenate(value) for key,value in exported.items()}
    assert np.allclose(_predict(tx[0], {**exported, 'roots':roots}), test_prediction[0])
    np.savez_compressed(pending, **exported, roots=roots, enabled=enabled)
    pending.replace(MODEL)
    pending_report=REPORT.with_suffix('.pending.json')
    pending_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    pending_report.replace(REPORT)
    _load_model.cache_clear()
    return report
