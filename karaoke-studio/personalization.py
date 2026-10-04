"""Local numeric voice observations, preferences and explicit quality feedback.

This learns bounded personal parameters, not new program code or a neural model.
No audio is copied here and no network calls are made.
"""
import json
from pathlib import Path


def load(data):
    path=Path(data)/'personal-profile.json'
    if not path.exists():return dict(version=1,revision=0,enabled=True,observations=[],ratings=[],preferences=None)
    result=json.loads(path.read_text(encoding='utf-8'))
    if result.get('version')!=1:raise ValueError('Неизвестная версия личного профиля')
    return result


def save(data,profile):
    path=Path(data)/'personal-profile.json';pending=path.with_suffix('.tmp')
    pending.write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8');pending.replace(path)


def summarize(profile):
    observations=profile['observations'];ratings=profile['ratings']
    return dict(enabled=profile['enabled'],revision=profile['revision'],examples=len(observations),
                range_hz=profile.get('range_hz'),speed_ms=profile.get('speed_ms',20),
                confidence=profile.get('confidence',.6),ratings=len(ratings),preferences=profile.get('preferences'))


def processing_profile(calibration,personal):
    result=dict(calibration or {})
    if personal['enabled']:
        result.update(adaptive_speed_ms=personal.get('speed_ms',20),
                      adaptive_confidence=personal.get('confidence',.6),adaptive_revision=personal['revision'])
        if personal.get('range_hz'):
            low,high=personal['range_hz']
            result['low_hz']=min(result.get('low_hz',low),low)
            result['high_hz']=max(result.get('high_hz',high),high)
    return result or None


def observe(profile,identity,diagnostics,preferences):
    # A repeated render of the same selected recordings is not another example.
    if profile['enabled'] and not any(item['id']==identity for item in profile['observations']):
        valid=[d for d in diagnostics if d.get('voiced_seconds',0)>=2 and len(d.get('voice_range_hz',[]))==3]
        if valid:
            profile['observations'].append(dict(id=identity,low=min(d['voice_range_hz'][0] for d in valid),
                high=max(d['voice_range_hz'][2] for d in valid),seconds=sum(d['voiced_seconds'] for d in valid),
                confidence=sum(d.get('median_confidence',.85) for d in valid)/len(valid)))
            profile['observations']=profile['observations'][-100:]
            items=profile['observations'];total=sum(min(d['seconds'],120) for d in items)
            profile['range_hz']=[sum(d[k]*min(d['seconds'],120) for d in items)/total for k in ('low','high')]
            average=sum(d.get('confidence',.85)*min(d['seconds'],120) for d in items)/total
            profile['base_confidence']=min(.7,max(.6,average-.25))
            profile['confidence']=min(.78,profile['base_confidence']+.025*sum(r['rating']=='wrong_notes' for r in profile['ratings'][-10:]))
    profile['preferences']=preferences
    profile['revision']+=1


def rate(profile,identity,rating):
    if rating not in {'good','robotic','wrong_notes'}:raise ValueError('Неизвестная оценка звучания')
    profile['ratings']=[r for r in profile['ratings'] if r['id']!=identity]
    profile['ratings'].append(dict(id=identity,rating=rating));profile['ratings']=profile['ratings'][-100:]
    # Recompute from the latest feedback, so changing a rating undoes its influence.
    recent=profile['ratings'][-10:]
    profile['speed_ms']=min(220,90+30*sum(r['rating']=='robotic' for r in recent)) if any(r['rating']=='robotic' for r in recent) else 20
    profile['confidence']=min(.78,profile.get('base_confidence',.6)+.025*sum(r['rating']=='wrong_notes' for r in recent))
    profile['revision']+=1
