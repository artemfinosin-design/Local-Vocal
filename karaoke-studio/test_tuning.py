import unittest
import json,threading
from urllib.request import urlopen,Request
import numpy as np
from audio_core import RATE,pitch_match
from voice import tuning_options,tuning_profile
import app

class TuningChecks(unittest.TestCase):
    def test_waveform_shift_has_no_periodic_volume_dips_or_chunk_seams(self):
        t=np.arange(RATE*8)/RATE
        voice=(.1*np.sin(2*np.pi*220*t)+.04*np.sin(2*np.pi*440*t)).astype(np.float32)
        source=(.1*np.sin(2*np.pi*250*t)).astype(np.float32)
        logs=[];result=pitch_match(voice,source,mode='melody',diagnostics=logs)
        rms=[np.sqrt(np.mean(result[i:i+2205]**2)) for i in range(RATE,7*RATE,2205)]
        self.assertLess(float(np.std(rms)/np.mean(rms)),.08)
        self.assertGreater(logs[0]['processed_seconds'],6)
        self.assertEqual(logs[0]['engine'],'waveform-psola-v1')
    def test_reference_crossing_tritone_does_not_flip_target_octave(self):
        from voice import track_pitch
        t=np.arange(RATE*5)/RATE
        frequency=220*2**((2+5*t/5)/12)
        ref=(.1*np.sin(2*np.pi*np.cumsum(frequency)/RATE)).astype(np.float32)
        user=(.1*np.sin(2*np.pi*220*t)).astype(np.float32)
        result=pitch_match(user,ref,mode='melody')
        f,at,c=track_pitch(result);active=(at>3.8)&(at<4.8)&(f>0)&(c>.6)
        self.assertGreater(float(np.median(f[active])),290)
        self.assertLess(float(np.max(abs(np.diff(12*np.log2(f[active]))))),2)
    def test_vibrato_no_longer_disables_hard_tuning(self):
        t=np.arange(RATE*4)/RATE
        hz=220*2**(np.sin(2*np.pi*5*t)/12);phase=2*np.pi*np.cumsum(hz)/RATE
        user=(.1*np.sin(phase)+.04*np.sin(phase*2)).astype(np.float32)
        ref=(.1*np.sin(2*np.pi*247*t)).astype(np.float32)
        from voice import track_pitch
        f,at,c=track_pitch(pitch_match(user,ref,mode='hard'))
        active=(at>.5)&(at<3.5)&(f>0)
        self.assertGreater(np.mean(abs(1200*np.log2(f[active]/246.94))<35),.85)
    def test_correct_voice_and_uncertain_reference_remain_unchanged(self):
        v=self.tone(220)
        np.testing.assert_array_equal(pitch_match(v,v,mode='melody'),v)
        np.testing.assert_array_equal(pitch_match(v,np.zeros_like(v),mode='hard'),v)
    def test_comfortable_low_calibration_does_not_hide_high_register(self):
        from voice import track_pitch
        v=self.tone(660);f,_,_=track_pitch(v,{'low_hz':100,'high_hz':160,'noise_rms':.001})
        self.assertAlmostEqual(float(np.median(f[f>0])),660,delta=5)
    def tone(self,hz):return (.08*np.sin(2*np.pi*hz*np.arange(RATE*3)/RATE)).astype(np.float32)
    def frequency(self,a):
        p=a[2*RATE:int(2.8*RATE)];return np.fft.rfftfreq(len(p),1/RATE)[np.argmax(abs(np.fft.rfft(p*np.hanning(len(p)))))]
    def test_strength_zero_is_exact_and_partial_changes_less(self):
        voice=self.tone(220);source=self.tone(250)
        np.testing.assert_array_equal(pitch_match(voice,source,mode='melody',settings={'strength':0}),voice)
        weak=self.frequency(pitch_match(voice,source,mode='melody',settings={'strength':35}))
        full=self.frequency(pitch_match(voice,source,mode='melody'))
        self.assertLess(abs(full-250),2);self.assertGreater(full-weak,10)
    def test_hard_preset_snaps_reference_while_melody_follows_it(self):
        voice=self.tone(220);source=self.tone(240)
        hard=self.frequency(pitch_match(voice,source,mode='hard'))
        melody=self.frequency(pitch_match(voice,source,mode='melody'))
        self.assertAlmostEqual(hard,233.08,delta=2);self.assertAlmostEqual(melody,240,delta=2)
    def test_settings_validation_and_calibration_noise_preserved(self):
        for settings in ({'strength':float('nan')},{'strength':True},{'speed_ms':0},{'voice_type':'unknown'},{'surprise':1}):
            with self.assertRaises(ValueError):tuning_options('melody',settings)
        profile={'low_hz':100,'high_hz':300,'noise_rms':.001}
        adjusted=tuning_profile(profile,'wide')
        self.assertEqual(adjusted['noise_rms'],.001);self.assertEqual(adjusted['pitch_bounds'],(45,1400));self.assertNotIn('pitch_bounds',profile)
    def test_presets_endpoint_and_script_are_served(self):
        server=app.StudioServer(('127.0.0.1',0),app.Handler);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            base=f'http://127.0.0.1:{server.server_port}'
            with urlopen(base+'/api/tune-presets') as r:presets=json.load(r)['presets']
            self.assertEqual(set(presets),{'gentle','natural','melody','hard'})
            with urlopen(base+'/tuning-ui.js') as r:self.assertIn(b'tuneSettings',r.read())
        finally:server.shutdown();server.server_close();worker.join()

if __name__=='__main__':unittest.main()
