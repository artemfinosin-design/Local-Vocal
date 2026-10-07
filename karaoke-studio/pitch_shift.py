"""Praat pitch-synchronous resynthesis, blended only into trusted voiced sounds."""
import numpy as np
import parselmouth
from parselmouth.praat import call
from scipy.ndimage import uniform_filter1d

RATE=44100


def shift_waveform(voice, pitch, times, correction, reliable):
    voice=np.asarray(voice,np.float32)
    eligible=np.asarray(reliable,bool)&(pitch>0)
    if not np.any(eligible & (abs(correction)>.02)):
        return voice.copy(),0
    sound=parselmouth.Sound(np.asarray(voice,dtype=float),sampling_frequency=RATE)
    voiced=pitch[eligible]
    floor=max(45.,float(np.percentile(voiced,2))*.7)
    ceiling=min(1400.,float(np.percentile(voiced,98))*1.5)
    manipulation=call(sound,'To Manipulation',.01,floor,ceiling)
    tier=call(manipulation,'Extract pitch tier')
    points=[(call(tier,'Get time from index',i),call(tier,'Get value at index',i))
            for i in range(1,call(tier,'Get number of points')+1)]
    if not points:return voice.copy(),0
    call(tier,'Remove points between',0,len(voice)/RATE)
    target=np.log2(pitch[eligible])+correction[eligible]/12
    for time,frequency in points:
        index=min(len(times)-1,int(np.searchsorted(times,time)))
        if index and abs(times[index-1]-time)<abs(times[index]-time):index-=1
        if eligible[index]:
            # Never interpolate a frequency against an unvoiced zero: that
            # invents a dive by an octave at consonant/voicing boundaries.
            destination=float(2**np.interp(time,times[eligible],target))
        else:destination=frequency
        call(tier,'Add point',time,destination)
    call([tier,manipulation],'Replace pitch tier')
    changed=call(manipulation,'Get resynthesis (overlap-add)').values[0]
    if len(changed)!=len(voice) or not np.isfinite(changed).all():
        raise ValueError('Коррекция нот вернула некорректный звук')
    # Keep consonants, breaths and uncertain/polyphonic regions dry.
    gate=np.interp(np.arange(len(voice))/RATE,times,eligible.astype(float),left=0,right=0)
    gate=uniform_filter1d(gate,round(.02*RATE),mode='constant')
    output=(voice*(1-gate)+changed*gate).astype(np.float32)
    return output,int(np.count_nonzero(eligible))
