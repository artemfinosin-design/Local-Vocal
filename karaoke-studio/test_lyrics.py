import io,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as Obj
from unittest.mock import patch
import app
from lyrics import lookup,result_lines


class LyricsChecks(unittest.TestCase):
    def test_upload_searches_before_separation_and_keeps_lyrics_at_ready(self):
        import numpy as np
        from audio_core import RATE,write_wav
        with tempfile.TemporaryDirectory() as temporary,patch('app.DATA',Path(temporary)),patch('app.jobs',{}),patch('app.learning',{'state':'idle'}):
            identity='a'*32;folder=Path(temporary)/identity;folder.mkdir()
            for name in ('song','lead','backing','vocals','instrumental'):write_wav(folder/(name+'.wav'),np.zeros((RATE,2)))
            app.jobs[identity]={'state':'queued'}
            candidate=dict(found=True,text='I wanna dance',synced='[00:00]I wanna dance',artist='Artist',title='Song',source='LRCLIB')
            meta=dict(roles=[dict(id='lead',reference='lead',mask=[],segments=[])],profiles={},version=13)
            def thread(*,target,args=(),**kwargs):return Obj(start=lambda:target(*args))
            def separate(*args):self.assertEqual(app.jobs[identity]['lyrics_state'],'waiting')
            def start(*args):app.jobs[identity]['lyrics_state']='processing'
            with patch('app.threading.Thread',side_effect=thread),patch('app.lookup',return_value=candidate),patch('app.start_lyrics',side_effect=start),patch('app.command',side_effect=separate),patch('app.convert'),patch('app.song_info',return_value=dict(artist='Artist',title='Song')),patch('app.analyze',return_value=meta),patch('app.markers',return_value=[]),patch('app.save_guides'),patch('app.learn_effects'):
                app.prepare(identity,folder/'upload.wav','Artist - Song.wav')
            self.assertEqual(app.jobs[identity]['state'],'ready')
            self.assertEqual(app.jobs[identity]['lyrics_state'],'processing')
            self.assertEqual(app.jobs[identity]['lyrics']['text'],'I wanna dance')

    def test_title_match_survives_wrong_artist_and_extra_phrase(self):
        item=dict(artistName='Olivia Rodrigo',trackName='drivers license',duration=242,plainLyrics='test')
        with patch('lyrics.urlopen',side_effect=[io.BytesIO(b'null'),io.BytesIO(json.dumps([item]).encode())]):
            result=lookup('Wrong artist','drivers license!!! please',242)
        self.assertTrue(result['found']);self.assertEqual(result['artist'],'Olivia Rodrigo')
        with patch('lyrics.urlopen',return_value=io.BytesIO(json.dumps([item]).encode())):
            self.assertTrue(lookup('','drivers licens',242)['found'])
        with patch('lyrics.urlopen',return_value=io.BytesIO(json.dumps([dict(item,artistName='olivia rodrigo'),item]).encode())):
            self.assertTrue(lookup('','drivers license',242)['found'])

    def test_wrong_song_and_ambiguous_cover_are_not_applied(self):
        a=dict(artistName='One',trackName='Same Song',duration=180,plainLyrics='one')
        b=dict(a,artistName='Two',plainLyrics='two')
        with patch('lyrics.urlopen',return_value=io.BytesIO(json.dumps([a,a,b]).encode())):
            self.assertTrue(lookup('','Same Song',180)['ambiguous'])
        with patch('lyrics.urlopen',return_value=io.BytesIO(json.dumps([a]).encode())):
            self.assertFalse(lookup('','Completely unrelated',180)['found'])

    def test_short_zero_length_words_and_missing_supplied_words_survive(self):
        result=Obj(segments=[Obj(words=[Obj(word='I',start=1,end=1),Obj(word='wanna',start=1.1,end=1.5),Obj(word='dance',start=1.6,end=2)])])
        lines=result_lines(result,5,'I wanna dance\nI wanna dance')
        self.assertEqual([w['text'] for l in lines['lines'] for w in l['words']],['I','wanna','dance']*2)
        self.assertTrue(all(w['end']>w['start'] for l in lines['lines'] for w in l['words']))
        self.assertEqual(result_lines(result,5)['lines'][0]['words'][0]['text'],'I')

    def test_found_lrc_is_usable_before_audio_and_alignment_starts_once(self):
        with tempfile.TemporaryDirectory() as temporary,patch('app.DATA',Path(temporary)),patch('app.jobs',{}):
            identity='a'*32;folder=Path(temporary)/identity;folder.mkdir()
            app.jobs[identity]=dict(state='splitting',duration=10)
            candidate=dict(found=True,text='I wanna dance',synced='[00:01]I wanna dance',artist='Artist',title='Song',source='LRCLIB')
            with patch('app.lookup',return_value=candidate),patch('app.start_lyrics') as start:
                app.find_project_lyrics(identity,'Artist','Song')
                self.assertEqual(app.jobs[identity]['lyrics_state'],'waiting')
                self.assertEqual(app.jobs[identity]['lyrics']['lines'][0]['words'][0]['text'],'I')
                start.assert_not_called()
                app.jobs[identity]['lyrics_audio_ready']=True
                def dispatch(*args):app.jobs[identity]['lyrics_state']='processing'
                start.side_effect=dispatch
                app.queue_found_lyrics(identity);app.queue_found_lyrics(identity)
                self.assertEqual(start.call_count,1)

    def test_stale_alignment_cannot_replace_a_new_text(self):
        with tempfile.TemporaryDirectory() as temporary,patch('app.DATA',Path(temporary)),patch('app.jobs',{}),patch('app.command'):
            identity='a'*32;folder=Path(temporary)/identity;folder.mkdir()
            request=folder/'old.json';request.write_text('{}');request.with_suffix('.result.json').write_text('{"text":"old"}')
            app.jobs[identity]=dict(lyrics_request='new.json',lyrics={'text':'new'},lyrics_state='processing')
            app.synchronize_lyrics(identity,request)
            self.assertEqual(app.jobs[identity]['lyrics']['text'],'new')
            self.assertFalse((folder/'lyrics.json').exists())


if __name__=='__main__':unittest.main()
