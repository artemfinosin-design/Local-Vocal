"""Regression checks for pitch safety, quiet takes, clip editing and karaoke timing."""
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import numpy as np

from audio_core import RATE, analyze, mix, pitch_match, _stable_vocal_gain, _limit_mix
from lyrics import guess_title, lrc_lines, lookup


class UpgradeChecks(unittest.TestCase):
    def test_lyrics_service_failures_are_not_reported_as_missing_lyrics(self):
        for error in (HTTPError('https://lrclib.net',503,'Unavailable',{},None),URLError('offline')):
            with patch('lyrics.urlopen',side_effect=error):
                with self.assertRaisesRegex(ValueError,'LRCLIB'):
                    lookup('2hollis','light',165.5)

    def test_a_single_peak_does_not_turn_down_the_whole_song(self):
        audio=np.full((RATE*2,2),.2,dtype=np.float32)
        audio[RATE,0]=8
        limited=_limit_mix(audio)
        self.assertLessEqual(float(np.max(abs(limited))),.981)
        np.testing.assert_array_equal(limited[:RATE//2],audio[:RATE//2])
        np.testing.assert_array_equal(limited[RATE+RATE//2:],audio[RATE+RATE//2:])

    def test_gain_does_not_jump_on_quiet_or_loud_syllables(self):
        measured=np.full(40,.02);measured[10]=.0001;measured[20]=.2
        gains=_stable_vocal_gain(measured,np.full(40,.1))
        self.assertLess(float(np.max(abs(np.diff(20*np.log10(gains))))),1)
        self.assertLess(float(np.max(gains)),9)

    def test_register_changes_are_not_forced_into_another_octave(self):
        t = np.arange(RATE) / RATE
        voice = np.concatenate([0.12 * np.sin(2 * np.pi * note * t) for note in (220, 440, 110)]).astype(np.float32)
        reference = np.tile((0.12 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), 3)
        corrected = pitch_match(voice, reference)
        for start in (.25, 1.25, 2.25):
            portion = slice(round(start * RATE), round((start + .5) * RATE))
            self.assertLess(float(np.max(np.abs(corrected[portion] - voice[portion]))), 1e-4)

    def test_uncertain_large_pitch_error_leaves_the_voice_unchanged(self):
        t = np.arange(RATE * 2) / RATE
        voice = (0.12 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        reference = (0.12 * np.sin(2 * np.pi * 330 * t)).astype(np.float32)
        self.assertLess(float(np.max(np.abs(pitch_match(voice, reference) - voice))), 1e-4)

    def test_quiet_recording_is_not_classified_as_silence(self):
        t = np.arange(RATE * 3) / RATE
        reference = np.column_stack([0.2 * np.sin(2 * np.pi * 220 * t)] * 2).astype(np.float32)
        voice = (0.001 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        result = mix(np.zeros_like(reference), {'vocals': reference}, [(voice, 0, 'lead')], analyze(reference), autotune=False)
        self.assertGreater(float(np.sqrt(np.mean(result ** 2))), .01)

    def test_new_clip_overrides_only_its_region_and_exclusion_is_reversible(self):
        t = np.arange(RATE * 4) / RATE
        original = (0.15 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        source = np.column_stack([original] * 2)
        meta = analyze(source)
        new = (0.15 * np.sin(2 * np.pi * 440 * t[:RATE * 2])).astype(np.float32)
        tracks = [{'voice':original, 'role':'lead'}, {'voice':new, 'role':'lead','start':1,'region':[1.25,2.25]}]
        result = mix(np.zeros_like(source), {'vocals':source}, tracks, meta, autotune=False)
        def peak(start):
            part = result[round(start * RATE):round((start + .4) * RATE),0]
            return np.fft.rfftfreq(len(part), 1 / RATE)[np.argmax(abs(np.fft.rfft(part)))]
        self.assertAlmostEqual(peak(.4),220,delta=3)
        self.assertAlmostEqual(peak(1.4),440,delta=3)
        self.assertAlmostEqual(peak(2.7),220,delta=3)
        meta['roles'][0]['excluded']=[[1,2]]
        muted = mix(np.zeros_like(source), {'vocals':source}, tracks, meta, autotune=False)
        self.assertLess(float(np.max(abs(muted[round(1.35*RATE):round(1.7*RATE)]))),1e-5)

    def test_lrc_and_filename_metadata(self):
        self.assertEqual(guess_title('Artist - Song.mp3'), {'artist':'Artist','title':'Song'})
        result = lrc_lines('[00:10.00]Первое слово\n[00:12.00]Вторая строка', 20)
        self.assertEqual(result['lines'][0]['words'][1]['start'],11)
        self.assertEqual(result['timing'],'line-estimate')


if __name__ == '__main__':
    unittest.main()
