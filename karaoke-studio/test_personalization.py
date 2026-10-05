import json,threading,tempfile,unittest
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from unittest.mock import patch
import app,personalization


class PersonalChecks(unittest.TestCase):
    def test_numeric_rating_uses_only_liked_voice_and_is_reversible(self):
        with tempfile.TemporaryDirectory() as directory:
            p=personalization.load(directory);d=[dict(voiced_seconds=10,voice_range_hz=[100,150,250],timbre=[.1,.2,.3,.2,.1,.1])]
            personalization.rate(p,'one',score=2,reasons=['robotic','pitch_drop'],diagnostics=d)
            self.assertNotIn('range_hz',p)
            personalization.rate(p,'one',score=9,reasons=[],diagnostics=d)
            self.assertEqual(p['range_hz'],[100,250]);self.assertEqual(p['timbre'],d[0]['timbre'])
            self.assertEqual(p['ratings'][0]['mark'],'good')
            personalization.rate(p,'one',score=5,reasons=['repeats'],diagnostics=d)
            self.assertNotIn('timbre',p)
            for score in (0,11,True):
                with self.assertRaises(ValueError):personalization.rate(p,'one',score=score,reasons=[])
    def test_observations_deduplicate_ratings_are_reversible_and_disable_preserves_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            profile=personalization.load(directory)
            measured=[dict(voiced_seconds=10,voice_range_hz=[100,150,250])]
            personalization.observe(profile,'same',measured,dict(mode='melody'))
            personalization.observe(profile,'same',measured,dict(mode='natural'))
            self.assertEqual(len(profile['observations']),1)
            personalization.rate(profile,'r1','robotic');self.assertEqual(profile['speed_ms'],120)
            personalization.rate(profile,'r1','good');self.assertEqual(profile['speed_ms'],20)
            profile['enabled']=False;calibration={'noise_rms':.002,'low_hz':90,'high_hz':300}
            self.assertEqual(personalization.processing_profile(calibration,profile),calibration)
            personalization.save(directory,profile)
            self.assertEqual(personalization.load(directory),profile)
    def test_endpoints_persist_export_numbers_without_audio_and_reject_unknown_render(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(app,'DATA',Path(directory)),patch.object(app,'jobs',{}):
            identity='a'*32;render='b'*32;folder=Path(directory)/identity;folder.mkdir()
            app.jobs[identity]={'state':'ready','renders':[render],'render_diagnostics':{render:dict(voices=[])}}
            server=app.StudioServer(('127.0.0.1',0),app.Handler);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            base=f'http://127.0.0.1:{server.server_port}'
            def post(path,value):return urlopen(Request(base+path,json.dumps(value).encode(),{'Content-Type':'application/json'}),timeout=3)
            try:
                with post('/api/render-rating?id='+identity,dict(render_id=render,rating='wrong_notes')) as r:self.assertGreater(json.load(r)['confidence'],.6)
                with urlopen(base+'/api/personal-profile-export?id='+identity,timeout=3) as r:
                    report=json.load(r);self.assertFalse(report['audio_included']);self.assertIn('processing_log',report)
                with self.assertRaises(HTTPError):post('/api/render-rating?id='+identity,dict(render_id='not-found',rating='good'))
                with post('/api/personal-profile',dict(action='reset')) as r:self.assertEqual(json.load(r)['ratings'],0)
            finally:server.shutdown();server.server_close();worker.join()


if __name__=='__main__':unittest.main()
