"""Pitch-synchronous overlap/add of the recorded waveform, preserving duration.

Only confidently periodic regions are eligible. Consonants and uncertain audio
remain dry. No spectral vocoder or reconstructed excitation is used here.
"""
import numpy as np
from scipy.signal import butter, sosfilt
from scipy.ndimage import binary_closing

RATE=44100


def shift_waveform(voice, pitch, times, correction, reliable):
    voice=np.asarray(voice,np.float32)
    output=voice.copy()
    # Close at most a 20ms tracking hole within a voiced sound, never silence.
    usable=binary_closing(reliable,structure=np.ones(3))&(pitch>0)
    edges=np.diff(np.r_[False,usable,False].astype(int))
    filtered=sosfilt(butter(2,900,fs=RATE,output='sos'),voice)
    processed=0
    for first,last in zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1)):
        if last-first<8 or np.max(abs(correction[first:last]))<.02:continue
        lo=max(0,round(times[first]*RATE));hi=min(len(voice),round(times[last-1]*RATE))
        if hi-lo<2205:continue
        def frequency(sample):return float(np.interp(sample/RATE,times[first:last],pitch[first:last]))
        def desired(sample):return frequency(sample)*2**(float(np.interp(sample/RATE,times[first:last],correction[first:last]))/12)
        period=RATE/frequency(lo)
        # All grains use positive low-frequency peaks to keep pulse phase aligned.
        a=lo;b=min(hi,lo+round(period))
        if b<=a:continue
        position=float(a+np.argmax(filtered[a:b]));epochs=[position]
        while position<hi:
            expected=position+RATE/frequency(position)
            radius=round(.18*RATE/frequency(expected))
            a=max(round(position)+1,round(expected)-radius);b=min(hi,round(expected)+radius+1)
            if b<=a:break
            position=float(a+np.argmax(filtered[a:b]));epochs.append(position)
        epochs=np.asarray(epochs)
        if len(epochs)<5:continue
        changed=np.zeros(hi-lo,np.float64);weights=np.zeros(hi-lo,np.float64)
        position=epochs[0];index=0
        while position<epochs[-1]:
            while index+1<len(epochs) and abs(epochs[index+1]-position)<abs(epochs[index]-position):index+=1
            source=round(epochs[index]);destination=round(position)
            half=round(max(RATE/frequency(source),RATE/desired(position))*1.1)
            offsets=np.arange(-half,half+1)
            good=(source+offsets>=0)&(source+offsets<len(voice))&(destination+offsets>=lo)&(destination+offsets<hi)
            offsets=offsets[good];window=.5+.5*np.cos(np.pi*offsets/half)
            changed[destination+offsets-lo]+=voice[source+offsets]*window
            weights[destination+offsets-lo]+=window
            position+=RATE/desired(position)
        valid=weights>.2
        shifted=voice[lo:hi].astype(np.float64).copy();shifted[valid]=changed[valid]/weights[valid]
        # Blend only the boundaries of the voiced region, not each individual note.
        blend=valid.astype(float);edge=min(round(.025*RATE),len(blend)//3)
        blend[:edge]*=np.linspace(0,1,edge);blend[-edge:]*=np.linspace(1,0,edge)
        output[lo:hi]=voice[lo:hi]*(1-blend)+shifted*blend
        processed+=last-first
    return output,processed
