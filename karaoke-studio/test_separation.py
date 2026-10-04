import unittest
import numpy as np
import tempfile,json
from pathlib import Path
from unittest.mock import patch
import app
from audio_core import RATE,write_wav,read_wav,analyze,save_meta
from separate_audio import split_mdx

class SeparationChecks(unittest.TestCase):
    def test_repeat_separation_keeps_takes_and_rolls_back_failed_commit(self):
        for fail in (False,True):
            with self.subTest(fail=fail),tempfile.TemporaryDirectory() as directory,patch.object(app,'DATA',Path(directory)),patch.object(app,'jobs',{}):
                identity='e'*32;folder=Path(directory)/identity;folder.mkdir()
                t=np.arange(RATE*2)/RATE;v=(.1*np.sin(2*np.pi*220*t)).astype(np.float32);stereo=np.column_stack([v]*2)
                for name in ('song','vocals','lead','backing','instrumental'):write_wav(folder/(name+'.wav'),stereo)
                meta=analyze(stereo,stereo*.1,stereo*1.1);meta['roles'][0]['excluded']=[[.5,.8]]
                save_meta(folder/'analysis.json',meta)
                take='f'*32;write_wav(folder/(take+'.wav'),v)
                app.jobs[identity]=dict(state='ready',tracks=[dict(id=take,role='lead')],renders=['prior'],roles=app.public_roles(meta),analysis_state='processing')
                app.save_job(identity)
                before={p.name:p.read_bytes() for p in folder.iterdir() if p.is_file()}
                def fake_command(*args):
                    target=Path(args[3])
                    for name in ('vocals','lead','backing','instrumental'):write_wav(target/(name+'.wav'),stereo*.5)
                    (target/'separation.json').write_text('{"version":2}')
                with patch('app.command',side_effect=fake_command):
                    if fail:
                        with patch('app.save_guides',side_effect=OSError('simulated export failure')):app.refresh_analysis(identity,True)
                    else:app.refresh_analysis(identity,True)
                self.assertEqual((folder/(take+'.wav')).read_bytes(),before[take+'.wav'])
                self.assertEqual(app.jobs[identity]['renders'],['prior'])
                if fail:
                    self.assertEqual(app.jobs[identity]['analysis_state'],'error')
                    for name in ('lead.wav','instrumental.wav','analysis.json'):self.assertEqual((folder/name).read_bytes(),before[name])
                else:
                    self.assertEqual(app.jobs[identity]['analysis_state'],'ready')
                    self.assertNotEqual((folder/'instrumental.wav').read_bytes(),before['instrumental.wav'])
                    self.assertEqual(json.loads((folder/'analysis.json').read_text())['roles'][0]['excluded'],[[.5,.8]])
                self.assertTrue(list(folder.glob('separation-backup-*')))
    def test_quiet_and_loud_songs_preserve_vocal_subtraction(self):
        class Model:
            compensate=1.035
            primary_stem_name='Vocals'
            def demix(self,signal):return signal*.4/self.compensate
            def clear_gpu_cache(self):pass
        for level in (.02,.71,.99):
            t=np.arange(44100)/44100
            song=np.column_stack([level*np.sin(2*np.pi*220*t)]*2).astype(np.float32)
            vocal,music=split_mdx(song,Model())
            np.testing.assert_allclose(vocal,song*.4,atol=1e-7)
            np.testing.assert_allclose(vocal+music,song,atol=1e-7)
            model=Model();model.primary_stem_name='Instrumental'
            vocal,music=split_mdx(song,model)
            np.testing.assert_allclose(music,song*.4,atol=1e-7)
            np.testing.assert_allclose(vocal,song*.6,atol=1e-7)
    def test_silence_does_not_run_model_and_invalid_output_fails(self):
        class Model:
            compensate=1
            primary_stem_name='Vocals'
            def demix(self,signal):return np.full_like(signal,np.nan)
            def clear_gpu_cache(self):pass
        zero=np.zeros((44100,2),np.float32)
        vocal,music=split_mdx(zero,Model())
        self.assertFalse(np.any(vocal));self.assertFalse(np.any(music))
        with self.assertRaises(RuntimeError):split_mdx(zero+1,Model())

if __name__=='__main__':unittest.main()
