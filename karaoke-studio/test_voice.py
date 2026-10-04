"""Quiet pitch, calibration, absent/present delay and opt-in export regression proof."""
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from zipfile import ZipFile
import numpy as np
import app
from audio_core import RATE, pitch_match, write_wav
from effects import estimate
from feedback import make_bundle
from voice import calibrate, track_pitch


def tone(hz, duration=2, gain=.1):
    t=np.arange(round(duration*RATE))/RATE
    return (gain*(np.sin(2*np.pi*hz*t)+.3*np.sin(4*np.pi*hz*t))).astype(np.float32)


def calibration():
    rng=np.random.default_rng(17)
    audio=rng.normal(0,.00001,RATE*14).astype(np.float32)
    for at,hz in ((2,330),(6,220),(10,440)):
        audio[at*RATE:(at+4)*RATE]+=tone(hz,4,.003)
    return audio


class VoiceChecks(unittest.TestCase):
    def test_shutdown_refuses_busy_work_and_stops_only_when_idle(self):
        identity='d'*32
        with patch('app.jobs',{identity:{'state':'processing'}}),patch('app.stopping',False),patch('app.active_posts',0):
            server=app.StudioServer(('127.0.0.1',0),app.Handler)
            thread=threading.Thread(target=server.serve_forever);thread.start()
            request=Request(f'http://127.0.0.1:{server.server_port}/api/shutdown',data=b'{}')
            try:
                with self.assertRaises(HTTPError) as busy:urlopen(request)
                self.assertEqual(busy.exception.code,409);self.assertFalse(app.stopping)
                app.jobs[identity]['state']='ready'
                with patch('app.active_posts',1):
                    with self.assertRaises(HTTPError) as rendering:urlopen(request)
                    self.assertEqual(rendering.exception.code,409)
                with urlopen(request) as response:self.assertEqual(response.status,200)
                thread.join(timeout=3);self.assertFalse(thread.is_alive());self.assertTrue(app.stopping)
            finally:server.shutdown();server.server_close();thread.join()

    def test_quiet_pitch_and_melody_mode(self):
        voice=tone(220,gain=.0002);source=tone(246.94)
        np.testing.assert_allclose(pitch_match(voice,source,mode='gentle'),voice,atol=1e-7)
        changed=pitch_match(voice,source,mode='melody')
        pitch,positions,_=track_pitch(changed)
        good=pitch[(positions>.4)&(positions<1.6)&(pitch>0)]
        self.assertAlmostEqual(float(np.median(good)),246.94,delta=3)
        np.testing.assert_allclose(pitch_match(voice,voice*500,mode='melody'),voice,atol=1e-6)

    def test_calibration_accepts_quiet_notes_and_rejects_noise(self):
        profile=calibrate(calibration())
        self.assertAlmostEqual(profile['low_hz'],220,delta=3)
        self.assertAlmostEqual(profile['high_hz'],440,delta=3)
        self.assertLess(profile['noise_rms'],.00002)
        with self.assertRaises(ValueError):calibrate(np.random.default_rng(1).normal(0,.1,RATE*14))

    def test_model_cannot_invent_delay_and_real_copies_are_detected(self):
        rate=11025;rng=np.random.default_rng(7);dry=np.zeros((rate*5,2),np.float32)
        for at in (.4,1.7,3.1):
            burst=rng.normal(size=round(rate*.12)).astype(np.float32)*.1
            dry[round(at*rate):round(at*rate)+len(burst)]=burst[:,None]
        with tempfile.TemporaryDirectory() as folder:
            model=Path(folder)/'model.npz';model.touch()
            with patch('effects.MODEL',model),patch('effects._load_model',return_value={'enabled':np.ones(4,dtype=bool)}),patch('effects._predict',return_value=np.array([.4,2,.3,.8])):
                absent=estimate(dry,rate)
                self.assertEqual(absent['delay_wet'],0);self.assertEqual(absent['room'],0)
                wet=dry.copy();lag=round(.28*rate);wet[lag:]+=dry[:-lag]*.32
                present=estimate(wet,rate)
                self.assertGreater(present['delay_wet'],.1);self.assertAlmostEqual(present['delay'],.28,delta=.002)

    def test_consent_bundle_contains_original_raw_voice_and_no_other_audio(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);identity='a'*32
            write_wav(folder/'upload.wav',np.column_stack([tone(220),tone(220)]))
            write_wav(folder/(identity+'.wav'),tone(230))
            (folder/'render.wav').write_bytes(b'private-mix')
            job={'filename':'test-song.wav','duration':2,'tracks':[{'id':identity,'role':'lead','start':0,'region':[0,2]}]}
            options={'tracks':[{'id':identity,'offset':-.04}],'autotune':True,'tune_mode':'melody','vocal_db':0,'space':'auto'}
            with self.assertRaises(ValueError):make_bundle(folder,job,options)
            self.assertEqual(list(folder.glob('feedback-*')),[])
            _,path=make_bundle(folder,job,{**options,'consent':True})
            with ZipFile(path) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(set(archive.namelist()),{'original/song.wav','voice/take-01.wav','manifest.json','README.txt','processing-log.json'})
                self.assertEqual(archive.read('voice/take-01.wav'),(folder/(identity+'.wav')).read_bytes())
                self.assertEqual(archive.read('original/song.wav'),(folder/'upload.wav').read_bytes())
                manifest=json.loads(archive.read('manifest.json'))
                self.assertEqual(manifest['takes'][0]['offset_seconds'],-.04)
                self.assertNotIn(str(folder),json.dumps(manifest))

    def test_api_calibration_removes_audio_and_requires_export_consent(self):
        with tempfile.TemporaryDirectory() as temporary,patch('app.DATA',Path(temporary)),patch('app.jobs',{}):
            root=Path(temporary);identity='b'*32;take='c'*32;folder=root/identity;folder.mkdir()
            write_wav(folder/'upload.wav',np.column_stack([tone(220),tone(220)]))
            write_wav(folder/(take+'.wav'),tone(230))
            app.jobs[identity]={'state':'ready','duration':2,'filename':'test.wav','tracks':[{'id':take,'role':'lead','region':[0,2]}]}
            server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            url=f'http://127.0.0.1:{server.server_port}'
            try:
                cal=root/'fixture.wav';write_wav(cal,calibration())
                with urlopen(Request(url+'/api/voice-check',data=cal.read_bytes(),headers={'Content-Type':'application/octet-stream'}),timeout=30) as response:
                    self.assertEqual(response.status,200)
                self.assertTrue((root/'voice-profile.json').exists());self.assertEqual(list(root.glob('voice-check-*')),[])
                options={'tracks':[{'id':take}],'autotune':True,'tune_mode':'melody','vocal_db':0,'space':'auto'}
                with self.assertRaises(HTTPError) as caught:
                    urlopen(Request(url+'/api/feedback?id='+identity,data=json.dumps(options).encode()))
                self.assertEqual(caught.exception.code,400)
                options['consent']=True
                with urlopen(Request(url+'/api/feedback?id='+identity,data=json.dumps(options).encode())) as response:result=json.load(response)
                with urlopen(url+result['url']) as response:
                    with ZipFile(io.BytesIO(response.read())) as archive:self.assertIsNone(archive.testzip())
            finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
