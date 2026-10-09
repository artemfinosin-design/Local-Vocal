import unittest
import json
import tempfile
import threading
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from unittest.mock import patch
import numpy as np
from voice import note_bars
import app
from audio_core import RATE,write_wav,mix,analyze,performance_report,pitch_match


class NoteBarsChecks(unittest.TestCase):
    def test_playback_score_tracks_compared_fragments(self):
        times=np.arange(200)*.01
        distance=np.r_[np.zeros(100),np.ones(100)]
        paired=np.ones(200,dtype=bool)
        paired[100:150]=False
        report=performance_report(distance,paired,times)
        self.assertEqual([item['hit_percent'] for item in report['live_segments']],[100,100,0])
        self.assertEqual([item['start'] for item in report['live_segments']],[0,.5,1.5])

    def test_imported_notes_score_the_dry_voice_without_retuning(self):
        time=np.arange(RATE*2)/RATE
        voice=(.1*np.sin(2*np.pi*220*time)).astype(np.float32)
        reference=(.1*np.sin(2*np.pi*440*time)).astype(np.float32)
        diagnostics=[]
        result=pitch_match(voice,reference,settings={'strength':0},diagnostics=diagnostics,
                           score_bars=[{'start':0,'end':2,'note':57}])
        np.testing.assert_allclose(result,voice,atol=1e-6)
        self.assertEqual(diagnostics[0]['performance']['source'],'ultrastar')
        self.assertGreater(diagnostics[0]['performance']['hit_percent'],95)

    def test_rerecord_replaces_only_its_region(self):
        t=np.arange(RATE*2)/RATE;original=.1*np.sin(2*np.pi*220*t)
        stereo=np.column_stack([original,original]);meta=analyze(stereo)
        old=np.full(RATE*2,.1,np.float32);new=np.full(RATE*2,.2,np.float32)
        captured=[]
        class Captured(Exception):pass
        def capture(voice,*args,**kwargs):captured.append(voice.copy());raise Captured()
        with patch('audio_core.pitch_match',side_effect=capture),self.assertRaises(Captured):
            mix(np.zeros_like(stereo),{'vocals':stereo},[
                dict(role='lead',voice=old,region=[0,2]),dict(role='lead',voice=new,region=[.7,1.2])],meta)
        voice=captured[0]
        self.assertAlmostEqual(float(voice[int(.4*RATE)]),.1,places=5)
        self.assertAlmostEqual(float(voice[int(.9*RATE)]),.2,places=5)
        self.assertAlmostEqual(float(voice[int(1.5*RATE)]),.1,places=5)

    def test_groups_trusted_notes_and_keeps_gaps(self):
        times=np.arange(40)*.01
        pitch=np.full(40,440.)
        trust=np.ones(40)
        trust[12:22]=.1
        with patch('voice.track_pitch',return_value=(pitch,times,trust)):
            bars=note_bars(np.zeros(100))
        self.assertEqual(len(bars),2)
        self.assertEqual([b['note'] for b in bars],[69,69])
        self.assertLess(bars[0]['end'],bars[1]['start'])

    def test_discards_silence_and_short_glitches(self):
        with patch('voice.track_pitch',return_value=(np.array([0,440,440]),np.arange(3)*.01,np.ones(3))):
            self.assertEqual(note_bars(np.zeros(100)),[])

    def test_isolated_instrument_note_does_not_become_singing_cue(self):
        pitch=np.zeros(200);pitch[90:105]=440
        confidence=np.ones(200)
        with patch('voice.track_pitch',return_value=(pitch,np.arange(200)*.01,confidence)):
            self.assertEqual(note_bars(np.zeros(100)),[])

    def test_reference_octave_glitch_does_not_create_random_target(self):
        pitch=np.full(100,220.);pitch[40:42]=440.
        with patch('voice.track_pitch',return_value=(pitch,np.arange(100)*.01,np.ones(100))):
            bars=note_bars(np.zeros(100))
        self.assertEqual(len(bars),1);self.assertEqual(bars[0]['note'],57)

    def test_fast_notes_within_a_phrase_remain_visible(self):
        pitch=np.repeat([220.,246.94,261.63,293.66]*3,8)
        with patch('voice.track_pitch',return_value=(pitch,np.arange(len(pitch))*.01,np.ones(len(pitch)))):
            bars=note_bars(np.zeros(100))
        self.assertEqual([bar['note'] for bar in bars],[57,59,60,62]*3)

    def test_api_caches_real_melody_and_rejects_unknown_role(self):
        with tempfile.TemporaryDirectory() as tmp,patch('app.DATA',Path(tmp)),patch('app.jobs',{}):
            identity='a'*32;folder=Path(tmp)/identity;folder.mkdir()
            t=np.arange(RATE)/RATE;wave=.1*np.sin(2*np.pi*220*t)
            write_wav(folder/'guide-lead.wav',np.column_stack([wave,wave]))
            app.jobs[identity]={'state':'ready','duration':1,'roles':[{'id':'lead'}]}
            server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            url=f'http://127.0.0.1:{server.server_port}/api/note-guide?id={identity}&role='
            try:
                with urlopen(url+'lead') as response:data=json.load(response)
                self.assertTrue(data['bars']);self.assertTrue(all(b['note']==57 for b in data['bars']))
                with patch('app.note_bars',side_effect=AssertionError('cache missed')):
                    with urlopen(url+'lead') as response:self.assertEqual(json.load(response),data)
                text='#BPM:240\n#TITLE:Test song\n: 0 4 -3 la\n: 4 4 0 la\n: 8 4 2 la\nE'
                body=json.dumps({'action':'apply','role':'lead','text':text,'offset':0}).encode()
                with urlopen(Request(f'http://127.0.0.1:{server.server_port}/api/note-chart?id={identity}',data=body,headers={'Content-Type':'application/json'})) as response:
                    self.assertEqual(json.load(response)['count'],3)
                with urlopen(url+'lead') as response:
                    selected=json.load(response)
                self.assertEqual(selected['source'],'ultrastar')
                self.assertEqual([bar['note'] for bar in selected['bars']],[57,60,62])
                body=json.dumps({'action':'preview','role':'lead','text':'#BPM:60\n#GAP:-500\n: 0 4 0 la\nE','offset':.25}).encode()
                with urlopen(Request(f'http://127.0.0.1:{server.server_port}/api/note-chart?id={identity}',data=body,headers={'Content-Type':'application/json'})) as response:
                    preview=json.load(response)
                self.assertEqual(preview['bars'],[{'start':0,'end':.75,'note':60}])
                with urlopen(url+'lead') as response:self.assertEqual(json.load(response),selected)
                body=json.dumps({'action':'clear','role':'lead'}).encode()
                with urlopen(Request(f'http://127.0.0.1:{server.server_port}/api/note-chart?id={identity}',data=body,headers={'Content-Type':'application/json'})) as response:
                    self.assertEqual(json.load(response)['source'],'automatic')
                with urlopen(url+'lead') as response:self.assertEqual(json.load(response),data)
                for invalid in ({'action':'preview','role':[],'text':text},
                                {'action':'preview','role':'lead','text':text,'voice':'9'}):
                    body=json.dumps(invalid).encode()
                    with self.assertRaises(HTTPError) as failed:
                        urlopen(Request(f'http://127.0.0.1:{server.server_port}/api/note-chart?id={identity}',data=body,headers={'Content-Type':'application/json'}))
                    self.assertEqual(failed.exception.code,400)
                with self.assertRaises(HTTPError):urlopen(url+'../../other')
            finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
