"""Conservative estimated pitch/formant falls, independent of note correction."""
import numpy as np
import pyworld
from scipy.ndimage import median_filter,uniform_filter1d
from voice import track_pitch
RATE=44100


def _formant_shift(samples,pitch,times,start,end):
    lo=max(0,round((start-.08)*RATE));hi=min(len(samples),round((end+.04)*RATE))
    x=np.ascontiguousarray(samples[lo:hi],dtype=np.float64)
    local=(times>=lo/RATE)&(times<hi/RATE)&(pitch>0)
    t=times[local]-lo/RATE;f=pitch[local]
    if len(t)<6:return None
    sp=pyworld.cheaptrick(x,np.ascontiguousarray(f),np.ascontiguousarray(t),RATE)
    early=(t>=start-lo/RATE)&(t<start-lo/RATE+.07)
    late=(t>=end-lo/RATE-.07)&(t<=end-lo/RATE)
    if not np.any(early) or not np.any(late):return None
    a=np.median(sp[early],axis=0);b=np.median(sp[late],axis=0)
    bins=np.linspace(0,RATE/2,len(a));grid=np.geomspace(500,5000,100)
    def shape(v):
        v=np.log(np.maximum(v,np.max(v)*1e-4));v-=np.polyval(np.polyfit(np.arange(len(v)),v,1),np.arange(len(v)))
        return v/(np.linalg.norm(v)+1e-9)
    target=shape(np.interp(grid,bins,b))
    candidates=np.arange(-14,1,.5)
    scores=[float(np.dot(shape(np.interp(grid/(2**(shift/12)),bins,a)),target)) for shift in candidates]
    index=int(np.argmax(scores));best=float(candidates[index]);zero=scores[int(np.flatnonzero(candidates==0)[0])]
    return best,float(scores[index]),float(scores[index]-zero)


def analyze_pitch_falls(reference):
    x=np.mean(reference,axis=1) if reference.ndim==2 else reference
    pitch,times,confidence=track_pitch(x)
    voiced=(pitch>0)&(confidence>.6)
    notes=12*np.log2(np.maximum(pitch,1))
    candidates=[]
    for end in range(30,len(pitch),5):
        start=end-30;good=voiced[start:end]
        if np.mean(good)<.6:continue
        selected=notes[start:end][good];steps=np.diff(selected)
        if selected[-1]-selected[0]>-5 or np.mean(steps<.1)<.75 or np.max(abs(steps))>2.8:continue
        if candidates and start<=candidates[-1][1]+8:candidates[-1][1]=end
        else:candidates.append([start,end])
    events=[]
    for start,end in candidates:
        while start>0 and end-start<100 and voiced[start-1] and 0<notes[start-1]-notes[start]<1.5:start-=1
        while end<len(pitch)-1 and end-start<100 and voiced[end+1] and 0<notes[end]-notes[end+1]<1.5:end+=1
        good=voiced[start:end+1];indexes=np.arange(start,end+1)[good]
        if len(indexes)<12:continue
        trajectory=median_filter(notes[indexes],size=3,mode='nearest');trajectory-=trajectory[0]
        if not -18<trajectory[-1]<-5:continue
        # Two held notes joined by a short sung transition are not a tape dive.
        moving=np.diff(trajectory)<-.12
        if np.count_nonzero(moving)<6:continue
        shape=_formant_shift(x,pitch,times,float(times[indexes[0]]),float(times[indexes[-1]]))
        if shape is None:continue
        shift,similarity,improvement=shape
        if shift>-2 or similarity<.65 or improvement<.1:continue
        events.append({'start':float(times[indexes[0]]),'end':float(times[indexes[-1]]),
            'times':times[indexes][::2].tolist()+[float(times[indexes[-1]])],
            'semitones':trajectory[::2].tolist()+[float(trajectory[-1])],
            'formant_amount':float(np.clip(shift/trajectory[-1],0,1)),
            'confidence':round(similarity,3),'type':'estimated_pitch_fall'})
    # Fast processed dives can lose periodicity in the middle. Offer an estimate
    # only when both pitched endpoints and a downward spectral shift agree.
    indexes=np.flatnonzero(voiced)
    groups=np.split(indexes,np.flatnonzero(np.diff(indexes)>5)+1)
    for first,last in zip(groups,groups[1:]):
        if len(first)<3 or len(last)<3:continue
        a=first[-min(6,len(first)):];b=last[:min(7,len(last))]
        gap=float(times[b[0]]-times[a[-1]])
        if not .07<gap<.2:continue
        base=float(np.median(pitch[a]));ending=float(np.median(pitch[b]))
        drop=float(12*np.log2(ending/base))
        start=float(times[a[0]]);end=float(times[b[-1]])
        if not -24<drop<-8 or end-start>.45:continue
        shape=_formant_shift(x,pitch,times,start,end)
        if shape is None:continue
        shift,similarity,improvement=shape
        if shift>-2 or similarity<.25 or improvement<.1:continue
        if any(event['start']<=end and event['end']>=start for event in events):continue
        points=np.r_[a,b];curve=12*np.log2(pitch[points]/base);curve=np.minimum.accumulate(np.minimum(curve,0))
        events.append({'start':start,'end':end,'times':times[points].tolist(),'semitones':curve.tolist(),
            'formant_amount':float(np.clip(shift/drop,0,1)), 'confidence':round(similarity,3),
            'type':'estimated_pitch_fall','uncertain_middle':True})
    return sorted(events,key=lambda event:event['start'])


def render_pitch_falls(voice,events,profile=None):
    output=np.asarray(voice,np.float32).copy()
    for event in events:
        lo=max(0,round((event['start']-.18)*RATE));hi=min(len(output),round((event['end']+.06)*RATE))
        x=np.ascontiguousarray(output[lo:hi],dtype=np.float64)
        if len(x)<RATE//5 or np.max(abs(x))<1e-7:continue
        pitch,times,confidence=track_pitch(x,profile)
        absolute=times+lo/RATE
        before=(absolute>=event['start']-.1)&(absolute<=event['start']+.04)&(pitch>0)&(confidence>.6)
        if np.count_nonzero(before)<3:continue
        base=float(np.median(pitch[before]))
        active=(absolute>=event['start'])&(absolute<=event['end'])&(pitch>0)&(confidence>.6)
        fall=np.interp(absolute,event['times'],event['semitones'])
        corrected=pitch.copy();corrected[active]=base*2**(fall[active]/12)
        sp=pyworld.cheaptrick(x,pitch,times,RATE);ap=pyworld.d4c(x,pitch,times,RATE)
        bins=np.arange(sp.shape[1],dtype=float)
        for i in np.flatnonzero(active):
            ratio=2**(fall[i]*event['formant_amount']/12)
            sp[i]=np.interp(bins/ratio,bins,sp[i],right=sp[i,-1])
            ap[i]=np.interp(bins/ratio,bins,ap[i],right=ap[i,-1])
        synthesized=pyworld.synthesize(corrected,sp,ap,RATE,frame_period=10)
        synthesized=np.pad(synthesized[:len(x)],(0,max(0,len(x)-len(synthesized))))
        blend=uniform_filter1d(active.astype(float),size=3,mode='nearest')
        weight=np.interp(np.arange(len(x))/RATE,times,blend)
        output[lo:hi]=(x*(1-weight)+synthesized*weight).astype(np.float32)
    return output


def analyze_stutters(reference):
    """Suggest similar vocal attacks whose spacing becomes denser; approval is required."""
    from scipy.signal import find_peaks,butter,sosfilt,correlate
    x=np.mean(reference,axis=1) if reference.ndim==2 else reference
    size=441
    env=np.sqrt(np.mean(np.pad(x*x,(0,(-len(x))%size)).reshape(-1,size),axis=1)+1e-12)
    if len(env)<100 or np.max(env)<.005:return []
    peaks,_=find_peaks(env,prominence=max(.003,np.percentile(env,80)*.22),distance=6)
    filtered=sosfilt(butter(2,[180,6000],fs=RATE,btype='bandpass',output='sos'),x)
    def repeated_wave(points):
        length=round(min(.08,float(np.min(np.diff(points)))*.75)*RATE);padding=round(.015*RATE)
        start=round(points[0]*RATE);template=filtered[start:start+length];scores=[]
        if length<441 or len(template)!=length:return 0
        for point in points[1:]:
            start=round(point*RATE);part=filtered[max(0,start-padding):min(len(filtered),start+padding+length)]
            if len(part)<length:return 0
            dot=correlate(part,template,mode='valid',method='fft')
            energy=np.sqrt(np.maximum(np.convolve(part**2,np.ones(length),'valid'),0)*np.sum(template**2))
            scores.append(float(np.max(dot/(energy+1e-10))))
        return float(np.median(scores)) if sum(score>.8 for score in scores)>=5 else 0
    def signature(at):
        clip=x[max(0,round((at-.025)*RATE)):min(len(x),round((at+.07)*RATE))][::4]
        if len(clip)<128:return None
        spectrum=np.abs(np.fft.rfft(clip*np.hanning(len(clip))))
        freq=np.fft.rfftfreq(len(clip),4/RATE)
        bands=np.array([np.mean(spectrum[(freq>=a)&(freq<b)]) for a,b in zip(np.geomspace(100,5000,13)[:-1],np.geomspace(100,5000,13)[1:])])
        return bands/(np.linalg.norm(bands)+1e-9)
    events=[]
    for index in range(len(peaks)-7):
        points=peaks[index:index+8]*.01;gaps=np.diff(points)
        early=float(np.median(gaps[:2]));late=float(np.median(gaps[-3:]))
        if not .08<=late<=.2 or early<late*1.5 or points[-1]-points[0]>3:continue
        vectors=[signature(at) for at in points]
        if any(v is None for v in vectors):continue
        similarities=np.array([np.dot(vectors[0],v) for v in vectors[1:]])
        if np.count_nonzero(similarities>.82)<5:continue
        copied=repeated_wave(np.maximum(0,points-.04))
        if copied<.82:continue
        start=float(max(0,points[0]-.04));end=float(min(len(x)/RATE,points[-1]+late))
        if events and start<events[-1]['end']:continue
        events.append({'type':'estimated_stutter','start':start,'end':end,
            'onsets':np.maximum(0,points-.04).tolist(),'template_start':start,
            'template_end':start+min(early,.3), 'confidence':copied})
    return events


def render_stutters(voice,events):
    output=np.asarray(voice,np.float32).copy()
    for event in events:
        start=round(event['start']*RATE);end=min(len(output),round(event['end']*RATE))
        a=round(event['template_start']*RATE);b=min(len(output),round(event['template_end']*RATE))
        template=output[a:b].copy()
        if len(template)<RATE*.04 or np.max(abs(template))<1e-7 or end<=start:continue
        replacement=np.zeros(end-start,np.float32);points=event['onsets']+[event['end']]
        for at,stop in zip(points[:-1],points[1:]):
            lo=max(start,round(at*RATE));hi=min(end,round(stop*RATE),lo+len(template))
            if hi<=lo:continue
            copy=template[:hi-lo].copy();edge=min(round(.005*RATE),len(copy)//3)
            if edge:copy[:edge]*=np.linspace(0,1,edge);copy[-edge:]*=np.linspace(1,0,edge)
            replacement[lo-start:hi-start]=copy
        output[start:end]=replacement
    return output


def analyze_colours(reference):
    """Offer strongly band-limited phrases only in otherwise broadband vocals.

    This is a coloration estimate, not identification of the original plugin.
    Quiet separation residue is excluded before evaluating spectral ratios.
    """
    x=np.mean(reference,axis=1) if reference.ndim==2 else reference
    size=4410;count=len(x)//size
    if count<10:return []
    frames=x[:count*size].reshape(count,size)
    rms=np.sqrt(np.mean(frames**2,axis=1))
    active=rms>max(.005,float(np.percentile(rms,85))*.2)
    if np.count_nonzero(active)<8:return []
    power=abs(np.fft.rfft(frames*np.hanning(size),axis=1))**2
    freq=np.fft.rfftfreq(size,1/RATE);total=np.sum(power,axis=1)+1e-15
    low=np.sum(power[:,freq<200],axis=1)/total
    high=np.sum(power[:,freq>4500],axis=1)/total
    middle=np.sum(power[:,(freq>=300)&(freq<=3500)],axis=1)/total
    if np.percentile((low+high)[active],80)<.08:return []
    evidence=active&(low<.001)&(high<.002)&(middle>.985)
    # Require most of an audible phrase to be narrow, not a single dull vowel.
    from scipy.ndimage import binary_closing
    narrow=binary_closing(evidence,structure=np.ones(3))&active
    edges=np.diff(np.r_[False,narrow,False].astype(int));events=[]
    for lo,hi in zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1)):
        if hi-lo<8 or np.mean(evidence[lo:hi])<.7 or np.median(middle[lo:hi])<.99:continue
        events.append(dict(type='estimated_colour',start=max(0,lo*.1-.05),end=min(len(x)/RATE,hi*.1+.05),
                           confidence=round(float(np.median(middle[lo:hi])),3)))
    return events


def render_colours(voice,events):
    from scipy.signal import butter,sosfilt
    output=np.asarray(voice,np.float32).copy()
    for event in events:
        lo=max(0,round(event['start']*RATE));hi=min(len(output),round(event['end']*RATE))
        if hi-lo<441:continue
        # Warm the filter with preceding audio, then fade at both boundaries.
        begin=max(0,lo-4410)
        filtered=sosfilt(butter(4,[300,3500],fs=RATE,btype='bandpass',output='sos'),output[begin:hi])[lo-begin:]
        original=output[lo:hi].copy();before=float(np.sqrt(np.mean(original**2)));after=float(np.sqrt(np.mean(filtered**2)))
        if after<1e-7:continue
        filtered*=min(2,before/after)
        weight=np.ones(hi-lo);edge=min(1323,len(weight)//3)
        weight[:edge]=np.linspace(0,1,edge);weight[-edge:]=np.linspace(1,0,edge)
        output[lo:hi]=original*(1-weight)+filtered*weight
    return output
