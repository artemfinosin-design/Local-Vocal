import unittest
import json,threading
from urllib.request import urlopen,Request
import numpy as np
from audio_core import RATE,pitch_match
from voice import tuning_options,tuning_profile
import app

class TuningChecks(unittest.TestCase):
    def test_room_persists_past_eight_seconds_but_stops_on_dry_evidence(self):
        from unittest.mock import patch
        from effects import analyze_effects
        def block(room=0,dry=0,width=.3):
            return dict(room=room,decay=.5,decay_evidence=2 if room else 0,
                        delay_wet=0,delay=.28,width=width,confidence=0,dry_evidence=dry,active=True)
        with patch('effects.estimate',side_effect=[block(.1)]+[block() for _ in range(5)]+[block(dry=2),block()]):
            blocks=analyze_effects(np.zeros((RATE*32,2),np.float32))
        self.assertEqual(blocks[5]['room'],.1)
        self.assertEqual(blocks[6]['room'],0)
        self.assertEqual(blocks[7]['room'],0)
        with patch('effects.estimate',side_effect=[block(.1),block(width=.8)]):
            blocks=analyze_effects(np.zeros((RATE*8,2),np.float32))
        self.assertEqual(blocks[1]['room'],0)
    def test_backing_gain_is_not_calibrated_to_silent_microphone_noise(self):
        from audio_core import _stable_vocal_gain
        measured=np.full(100,.001);measured[40:55]=.08
        target=np.full(100,.15)
        gain=_stable_vocal_gain(measured,target)
        self.assertLess(float(np.median(gain[43:52])),3)
        self.assertGreater(float(np.median(gain[43:52])),1)

    def test_effect_gaps_require_measured_neighbours(self):
        from unittest.mock import patch
        from effects import analyze_effects
        def block(room=0,delay=0,dry=0):
            return dict(room=room,decay=.5,decay_evidence=int(room>0),delay_wet=delay,delay=.28,width=0,confidence=.95,dry_evidence=dry)
        with patch('effects.estimate',side_effect=[block(.1,.15),block(.1),block(0,.15),block(dry=2)]):
            blocks=analyze_effects(np.zeros((RATE*16,2),np.float32))
        self.assertEqual(blocks[2]['room'],.1)
        self.assertEqual(blocks[1]['delay_wet'],.15)
        self.assertEqual(blocks[3]['delay_wet'],0)
        with patch('effects.estimate',return_value=block()):
            self.assertFalse(any(b['room'] or b['delay_wet'] for b in analyze_effects(np.zeros((RATE*12,2)))))
    def test_coaching_uses_raw_notes_and_does_not_invent_score_for_silence(self):
        from audio_core import vocal_report
        v=self.tone(220);logs=[];pitch_match(v,self.tone(225),diagnostics=logs)
        p=logs[0]['performance'];self.assertGreater(p['melody_score'],90)
        self.assertTrue(p['advice']);self.assertTrue(p['range_hz'])
        times=np.arange(300)*.01;zero=np.zeros(300)
        unknown=vocal_report(np.zeros(RATE*3),np.zeros(RATE*3),zero,times,zero,zero.astype(bool),zero)
        self.assertNotIn('melody_score',unknown)
        self.assertIn('Недостаточно',unknown['summary'])
    def test_register_change_does_not_drag_high_voice_down_an_octave(self):
        from voice import track_pitch
        t=np.arange(RATE*4)/RATE;hz=np.where(t<2,220,440)
        user=(.1*np.sin(2*np.pi*np.cumsum(hz)/RATE)).astype(np.float32)
        ref=(.1*np.sin(2*np.pi*440*t)).astype(np.float32)
        result=pitch_match(user,ref,mode='melody',settings={'voice_type':'wide'})
        f,at,c=track_pitch(result);good=(at>2.5)&(at<3.5)&(f>0)
        self.assertGreater(float(np.median(f[good])),420)
    def test_report_is_raw_octave_equivalent_and_available_without_tuning(self):
        logs=[];v=self.tone(220);r=self.tone(440)
        np.testing.assert_array_equal(pitch_match(v,r,settings={'strength':0},diagnostics=logs),v)
        self.assertGreater(logs[0]['performance']['hit_percent'],95)
        self.assertEqual(len(logs[0]['timbre']),6)
        logs=[];pitch_match(v,self.tone(225),mode='hard',diagnostics=logs)
        self.assertAlmostEqual(logs[0]['performance']['median_cents'],38.9,delta=4)
        t=np.arange(RATE*3)/RATE;hz=220*2**(np.sin(2*np.pi*5*t)/12)
        changing=(.1*np.sin(2*np.pi*np.cumsum(hz)/RATE)).astype(np.float32)
        np.testing.assert_array_equal(pitch_match(changing,r,mode='hard',settings={'strength':0}),changing)
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
