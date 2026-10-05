import unittest
import numpy as np
from audio_core import RATE,analyze,mix
from pitch_effects import analyze_pitch_falls,render_pitch_falls,render_stutters,analyze_stutters,analyze_colours,render_colours
from unittest.mock import patch
import json,threading,tempfile
from pathlib import Path
from urllib.request import urlopen,Request
from urllib.error import HTTPError
import app
from audio_core import save_meta
from voice import track_pitch

def slide(tape=True):
    t=np.arange(RATE*3)/RATE
    semitones=-12*np.clip((t-1)/.6,0,1)
    ratio=2**(semitones/12);f=220*ratio;phase=np.cumsum(f)/RATE*2*np.pi
    x=np.zeros(len(t))
    for h in range(1,30):
        frequency=220*h if tape else f*h
        amp=sum(np.exp(-.5*((frequency-fm)/140)**2) for fm in (650,1500,2800))/h
        x+=amp*np.sin(phase*h)
    x*=.15/max(abs(x));return x.astype(np.float32)

class FallChecks(unittest.TestCase):
    def test_legacy_uncertain_drop_is_not_rendered(self):
        v=slide(False)
        np.testing.assert_array_equal(render_pitch_falls(v,[dict(uncertain_middle=True)]),v)
    def test_complete_regular_repeat_chain_and_user_repeats_are_replaced(self):
        rng=np.random.default_rng(35);template=rng.normal(0,.05,round(.09*RATE)).astype(np.float32)*np.hanning(round(.09*RATE))
        reference=np.zeros(RATE*5,np.float32);points=np.arange(.5,3.6,.25)
        for at in points:
            lo=round(at*RATE);reference[lo:lo+len(template)]=template
        events=analyze_stutters(reference)
        self.assertEqual(len(events),1);self.assertEqual(events[0]['repeat_count'],len(points))
        user=reference.copy();user[round(1.8*RATE):round(1.95*RATE)]=.3
        result=render_stutters(user,events)
        self.assertLess(float(np.max(abs(result[round(1.85*RATE):round(1.9*RATE)]))),.2)
        np.testing.assert_array_equal(result[round(events[0]['end']*RATE):],user[round(events[0]['end']*RATE):])
    def test_copied_syllables_detected_but_independent_syllables_are_not(self):
        rng=np.random.default_rng(17)
        count=round(.095*RATE);t=np.arange(count)/RATE
        template=rng.normal(size=count)*np.sin(np.pi*t/(count/RATE))**2*.08
        points=[.5,1,1.45,1.78,2.02,2.18,2.31,2.42]
        def example(copies):
            voice=np.zeros(RATE*4,np.float32)
            for at in points:
                part=template if copies else rng.normal(size=count)*np.sin(np.pi*t/(count/RATE))**2*.08
                start=round(at*RATE);voice[start:start+count]=part
            return voice
        self.assertTrue(analyze_stutters(example(True)))
        self.assertFalse(analyze_stutters(example(False)))
    def test_colour_requires_bandwidth_evidence_and_changes_only_region(self):
        from scipy.signal import butter,sosfilt
        rng=np.random.default_rng(19);raw=rng.normal(0,.04,RATE*4).astype(np.float32)
        limited=sosfilt(butter(8,[600,2000],fs=RATE,btype='bandpass',output='sos'),raw)
        reference=raw.copy();reference[RATE:2*RATE]=limited[RATE:2*RATE]
        events=analyze_colours(reference)
        self.assertTrue(any(e['start']<=1.2 and e['end']>=1.8 for e in events))
        self.assertFalse(analyze_colours(raw))
        result=render_colours(raw,[dict(start=1,end=2)])
        np.testing.assert_array_equal(result[:RATE],raw[:RATE])
        np.testing.assert_array_equal(result[2*RATE:],raw[2*RATE:])
        self.assertLess(float(np.std(result[RATE:2*RATE])),float(np.std(raw[RATE:2*RATE])))
    def test_decisions_persist_and_invalid_or_busy_requests_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(app,'DATA',Path(directory)),patch.object(app,'jobs',{}):
            identity='d'*32;folder=Path(directory)/identity;folder.mkdir()
            app.jobs[identity]={'state':'ready'}
            save_meta(folder/'analysis.json',{'effect_proposals':[dict(id='fall',type='estimated_pitch_fall',reference='vocals',start=1,end=2,status='pending')]})
            server=app.StudioServer(('127.0.0.1',0),app.Handler)
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            base=f'http://127.0.0.1:{server.server_port}'
            def decision(data):return urlopen(Request(base+'/api/effect-decision?id='+identity,json.dumps(data).encode(),{'Content-Type':'application/json'}))
            try:
                with urlopen(base+'/api/effect-proposals?id='+identity) as response:self.assertEqual(json.load(response)['proposals'][0]['status'],'pending')
                for status in ('approved','rejected','pending'):
                    with decision(dict(id='fall',status=status)) as response:self.assertEqual(json.load(response)['status'],status)
                    self.assertEqual(json.loads((folder/'analysis.json').read_text())['effect_proposals'][0]['status'],status)
                for data in (dict(id='missing',status='approved'),dict(id='fall',status='anything')):
                    with self.assertRaises(HTTPError) as error:decision(data)
                    self.assertEqual(error.exception.code,400)
                app.jobs[identity]['analysis_state']='processing'
                with self.assertRaises(HTTPError):decision(dict(id='fall',status='approved'))
                self.assertEqual(json.loads((folder/'analysis.json').read_text())['effect_proposals'][0]['status'],'pending')
            finally:server.shutdown();server.server_close();worker.join()
    def test_only_approved_events_are_applied_and_master_switch_disables_them(self):
        t=np.arange(RATE*2)/RATE;v=(.1*np.sin(2*np.pi*220*t)).astype(np.float32)
        stereo=np.column_stack([v]*2);meta=analyze(stereo)
        events=[dict(type='estimated_pitch_fall',reference='vocals',status=status,id=status) for status in ('pending','rejected','approved')]
        meta['effect_proposals']=events
        with patch('audio_core.render_pitch_falls',side_effect=lambda voice,events,profile:voice) as render:
            mix(np.zeros_like(stereo),{'vocals':stereo},[(v,0,'lead')],meta,autotune=False,space='dry')
            self.assertEqual(render.call_args.args[1],[events[-1]])
            render.reset_mock()
            mix(np.zeros_like(stereo),{'vocals':stereo},[(v,0,'lead')],meta,autotune=False,space='dry',pitch_falls=False)
            render.assert_not_called()
    def test_stutter_repeats_template_only_inside_selected_region(self):
        t=np.arange(RATE*3)/RATE;v=(.1*np.sin(2*np.pi*(220*t+40*t*t))).astype(np.float32)
        event=dict(start=1,end=2,onsets=[1,1.4,1.7,1.85],template_start=1,template_end=1.3)
        result=render_stutters(v,[event])
        np.testing.assert_array_equal(result[:RATE],v[:RATE])
        np.testing.assert_array_equal(result[RATE*2:],v[RATE*2:])
        self.assertFalse(np.array_equal(result[RATE:RATE*2],v[RATE:RATE*2]))
        np.testing.assert_allclose(result[round(1.4*RATE)+300:round(1.4*RATE)+400],v[RATE+300:RATE+400],atol=1e-7)
    def test_tape_fall_detected_but_natural_glissando_and_octave_step_are_not(self):
        self.assertTrue(analyze_pitch_falls(slide(True)))
        self.assertFalse(analyze_pitch_falls(slide(False)))
        t=np.arange(RATE*3)/RATE;voice=(.1*np.sin(2*np.pi*np.where(t<1.5,220,110)*t)).astype(np.float32)
        self.assertFalse(analyze_pitch_falls(voice))
    def test_transfer_moves_pitch_down_and_does_not_touch_other_regions(self):
        events=analyze_pitch_falls(slide(True))
        t=np.arange(RATE*3)/RATE;voice=(.1*np.sin(2*np.pi*220*t)+.03*np.sin(2*np.pi*440*t)).astype(np.float32)
        changed=render_pitch_falls(voice,events)
        np.testing.assert_array_equal(changed[:RATE//2],voice[:RATE//2])
        f,positions,c=track_pitch(changed);late=(positions>1.35)&(positions<1.5)&(f>0)
        self.assertLess(float(np.median(f[late])),180)
        self.assertTrue(np.all(np.isfinite(changed)))
    def test_short_independent_spoken_response_is_offered(self):
        t=np.arange(RATE*3)/RATE;lead=(.1*np.sin(2*np.pi*330*t)).astype(np.float32)
        backing=np.zeros_like(lead);at=(t>1)&(t<1.6);backing[at]=.1*np.sin(2*np.pi*140*t[at])
        a=np.column_stack([lead]*2);b=np.column_stack([backing]*2)
        meta=analyze(a,b,a+b)
        role=next(r for r in meta['roles'] if r['id']=='backing')
        self.assertTrue(any(start<=1.25 and end>=1.5 for start,end in role['segments']))

if __name__=='__main__':unittest.main()
