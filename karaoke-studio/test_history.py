import unittest,tempfile,json,threading
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import app

class HistoryChecks(unittest.TestCase):
    def test_list_delete_restore_preserves_recordings_and_rejects_busy_or_invalid_projects(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(app,'DATA',Path(directory)),patch.object(app,'jobs',{}):
            identity='a'*32;folder=Path(directory)/identity;folder.mkdir()
            app.jobs[identity]=dict(state='ready',filename='Song.wav',tracks=[dict(id='take')],renders=['render'],duration=12)
            app.save_job(identity);timestamp=app.jobs[identity]['updated_at'];app.save_job(identity,touch=False)
            self.assertEqual(app.jobs[identity]['updated_at'],timestamp)
            (folder/'take.wav').write_bytes(b'original dry recording')
            server=app.StudioServer(('127.0.0.1',0),app.Handler);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            base=f'http://127.0.0.1:{server.server_port}'
            def post(action,project=identity):
                with urlopen(Request(base+'/api/history-'+action+'?id='+project,data=b'{}',headers={'Content-Type':'application/json'})) as r:return json.load(r)
            def history():
                with urlopen(base+'/api/history') as r:return json.load(r)
            try:
                self.assertEqual(history()['songs'][0]['filename'],'Song.wav')
                with self.assertRaises(HTTPError):post('delete','../bad')
                app.jobs[identity]['analysis_state']='processing'
                with self.assertRaises(HTTPError):post('delete')
                self.assertTrue(folder.exists());app.jobs[identity]['analysis_state']='ready';app.save_job(identity)
                post('delete');self.assertFalse(folder.exists());self.assertNotIn(identity,app.jobs)
                self.assertEqual(history()['songs'],[])
                self.assertEqual(history()['trash'][0]['id'],identity)
                self.assertEqual((Path(directory)/'.trash'/identity/'take.wav').read_bytes(),b'original dry recording')
                post('restore');self.assertEqual((folder/'take.wav').read_bytes(),b'original dry recording')
                self.assertEqual(app.jobs[identity]['tracks'],[dict(id='take')])
                self.assertEqual(history()['trash'],[])
            finally:server.shutdown();server.server_close();worker.join()

if __name__=='__main__':unittest.main()
