import unittest
import json
import tempfile
import threading
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError
from unittest.mock import patch
import numpy as np
from voice import note_bars
import app
from audio_core import RATE,write_wav,mix,analyze


class NoteBarsChecks(unittest.TestCase):
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

    def test_reference_octave_glitch_does_not_create_random_target(self):
        pitch=np.full(100,220.);pitch[40:42]=440.
        with patch('voice.track_pitch',return_value=(pitch,np.arange(100)*.01,np.ones(100))):
            bars=note_bars(np.zeros(100))
        self.assertEqual(len(bars),1);self.assertEqual(bars[0]['note'],57)

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
                with self.assertRaises(HTTPError):urlopen(url+'../../other')
            finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
