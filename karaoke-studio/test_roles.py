import unittest
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
import app
import numpy as np
from audio_core import RATE,HOP,analyze,recover_primary,mix,suggest_roles,write_wav,save_meta


def singer(pitch,formants,seconds=2):
    t=np.arange(round(RATE*seconds))/RATE
    mono=np.zeros(len(t))
    for h in range(1,int(5000/pitch)+1):
        frequency=h*pitch
        amplitude=sum(np.exp(-.5*((frequency-f)/120)**2) for f in formants)/h
        mono+=amplitude*np.sin(2*np.pi*frequency*t)
    mono*=.15/max(np.max(abs(mono)),1e-9)
    return np.column_stack([mono,mono]).astype(np.float32)


class RoleChecks(unittest.TestCase):
    def test_saved_project_refresh_preserves_recordings_and_exclusions(self):
        with tempfile.TemporaryDirectory() as temporary, patch('app.DATA',Path(temporary)), patch('app.jobs',{}):
            identity='a'*32;folder=Path(temporary)/identity;folder.mkdir()
            full=singer(180,(600,1400,2600),4);lead=full.copy();lead[RATE:3*RATE]*=.001
            for name,audio in [('vocals',full),('lead',lead),('backing',full-lead),('instrumental',full*.2)]:
                write_wav(folder/(name+'.wav'),audio)
            meta=analyze(lead,full-lead,full);meta['version']=5;meta['roles'][0]['excluded']=[[0,.5]]
            save_meta(folder/'analysis.json',meta)
            take='b'*32;render='c'*32
            write_wav(folder/(take+'.wav'),full[:,:1]);write_wav(folder/(render+'.wav'),full)
            original={key:(folder/(key+'.wav')).read_bytes() for key in (take,render)}
            app.jobs[identity]={'state':'ready','version':3,'tracks':[{'id':take,'role':'lead'}],
                'renders':[render],'roles':app.public_roles(meta),'markers':[],'song_info':{'title':'test'}}
            app.save_job(identity);app.jobs.clear();app.restore_jobs()
            deadline=time.monotonic()+10
            while app.jobs[identity].get('analysis_state')=='processing' and time.monotonic()<deadline:
                time.sleep(.02)
            self.assertEqual(app.jobs[identity]['analysis_state'],'ready')
            refreshed=json.loads((folder/'analysis.json').read_text(encoding='utf-8'))
            self.assertEqual(refreshed['version'],12)
            self.assertEqual(refreshed['roles'][0]['excluded'],[[0,.5]])
            self.assertEqual(len(app.jobs[identity]['tracks']),1)
            self.assertEqual(app.jobs[identity]['renders'],[render])
            self.assertTrue(list(folder.glob('analysis-backup-*.json')))
            for key,data in original.items():self.assertEqual((folder/(key+'.wav')).read_bytes(),data)

    def test_register_is_not_another_singer_but_formants_can_be(self):
        male=(600,1400,2600);female=(950,2200,3400)
        single=np.concatenate([singer(p,male,6) for p in (110,220,165,330)])
        active=np.ones(int(len(single)/HOP),bool)
        self.assertEqual([r['id'] for r in suggest_roles(single,active,np.zeros(len(active)))],['lead'])
        duet=np.concatenate([singer(140,male,12),singer(280,female,12)])
        roles=suggest_roles(duet,active,np.zeros(len(active)))
        self.assertEqual({r['id'] for r in roles},{'lead','artist2'})
        np.testing.assert_array_equal(np.sum([r['mask'] for r in roles],axis=0),active)

    def test_missing_chorus_is_recovered_and_not_offered_as_backing(self):
        full=singer(180,(600,1400,2600),6)
        lead=full.copy();lead[2*RATE:4*RATE]*=.001
        backing=full-lead
        recovered=recover_primary(lead,full)
        np.testing.assert_allclose(recovered[int(2.4*RATE):int(3.6*RATE)],full[int(2.4*RATE):int(3.6*RATE)],atol=1e-6)
        meta=analyze(lead,backing,full)
        primary=next(r for r in meta['roles'] if r['id']=='lead')
        self.assertTrue(all(primary['mask'][8:16]))
        self.assertFalse(any(r['id']=='backing' for r in meta['roles']))

    def test_recorded_phrase_survives_detection_gap_but_explicit_exclusion_mutes(self):
        full=singer(180,(600,1400,2600),4)
        meta=analyze(full)
        role=meta['roles'][0];role['mask'][4:12]=[False]*8
        result=mix(np.zeros_like(full),{'vocals':full},[(full[:,0],0,'lead')],meta,autotune=False,space='dry')
        self.assertGreater(float(np.sqrt(np.mean(result[int(1.4*RATE):int(2.6*RATE)]**2))),.02)
        role['excluded']=[[1,3]]
        result=mix(np.zeros_like(full),{'vocals':full},[(full[:,0],0,'lead')],meta,autotune=False,space='dry')
        self.assertEqual(float(np.max(abs(result[int(1.4*RATE):int(2.6*RATE)]))),0)

if __name__=='__main__': unittest.main()
