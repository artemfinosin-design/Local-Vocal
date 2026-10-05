const $ = id => document.getElementById(id);
let projectId, project, roles = [], recording = false, rendering = false, mutating = false, uploading = false, calibrating = false;
let pollTimer, recorder, recordSession, previewContext, previewGain, previewNodes = [], previewTimer, previewGeneration = 0;
let lyrics = null, lyricSource = null, lyricFrame, lyricLine = -2, suggestion, analysisPending = false;
async function request(url, options = {}) {
  const response = await fetch(url, options), body = await response.json();
  if (!response.ok) throw new Error(body.error || 'Не удалось выполнить действие');
  return body;
}
const post = (path, body) => request(`/api/${path}?id=${projectId}`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
const seconds = (value, precise=false) => {
  const ticks = precise ? Math.round(value * 10) : Math.floor(value) * 10;
  return `${Math.floor(ticks / 600)}:${String(Math.floor(ticks / 10) % 60).padStart(2,'0')}${precise ? ',' + ticks % 10 : ''}`;
};
const audioUrl = name => `/api/audio?id=${projectId}&name=${name}`;
const busy = () => recording || rendering || uploading || mutating || analysisPending || calibrating;
let monitorVolume = Number(localStorage.getItem('monitorVolume') ?? .35);
if (!Number.isFinite(monitorVolume)) monitorVolume=.35;
monitorVolume=Math.max(0,Math.min(1,monitorVolume));
function updateMonitorVolume() {
  $('monitorVolume').value=Math.round(monitorVolume*100);
  $('monitorVolumeValue').textContent=Math.round(monitorVolume*100)+'%';
  document.querySelectorAll('audio').forEach(audio=>audio.volume=monitorVolume);
  if(previewGain)previewGain.gain.setTargetAtTime(monitorVolume,previewContext.currentTime,.02);
}
$('monitorVolume').addEventListener('input',()=>{
  monitorVolume=Number($('monitorVolume').value)/100;
  localStorage.setItem('monitorVolume',monitorVolume);updateMonitorVolume();
});
updateMonitorVolume();

window.refreshVocalEditors=()=>roles.forEach(role=>role.editor?.draw());
function syncControls() {
  document.body.classList.toggle('busy', busy());
  $('file').disabled = busy(); $('render').disabled = busy()||window.engineCompatible===false; $('stop').hidden = !recording;
  for (const control of document.querySelectorAll('.track button,.track input,.track select,.clip input,.clip button,.effect-card button,.mix-options input,.mix-options select,#stageBack,#stageNext,#reanalyze,.studio-tools button,.stage-actions button,.mix-delay-take input,.mix-delay-take button')) control.disabled = busy();
  if(window.engineCompatible===false)document.querySelectorAll('.record-selection').forEach(node=>node.disabled=true);
  $('chooseFile').disabled=busy();$('resumeProject').disabled=busy();
  $('newSong').disabled=recording||rendering||uploading||mutating||calibrating;
  $('openHistory').disabled=$('newSong').disabled;
  if (!busy()) window.studioFlow.show();
  for(const audio of document.querySelectorAll('audio')) audio.controls = !recording;
}
function pauseAll() { for (const audio of document.querySelectorAll('audio')) audio.pause(); }
function element(tag, className, text) {
  const node = document.createElement(tag); if(tag==='audio')node.volume=monitorVolume; if (className) node.className = className; if (text !== undefined) node.textContent = text; return node;
}
function button(text, handler, className='preview-button') {
  const node = element('button',className,text); node.addEventListener('click',handler); return node;
}
async function upload(file) {
  if (!file || busy()) return;
  if (file.size > 150 * 1024 * 1024) { $('status').textContent='Файл больше 150 МБ'; return; }
  resetProject();
  uploading=true; syncControls(); window.studioFlow.uploading();
  $('uploadCard').classList.add('working'); $('status').textContent=`Загружаю ${file.name}…`;
  try {
    const job = await request('/api/upload?filename='+encodeURIComponent(file.name), {method:'POST', headers:{'Content-Type':'application/octet-stream'}, body:file});
    projectId=job.id; localStorage.setItem('karaokeProject',projectId); history.replaceState(null,'','?project='+projectId); pollProject();
  } catch(error) { $('status').textContent=error.message; $('uploadCard').classList.remove('working'); }
  finally { uploading=false; syncControls(); }
}
function resetProject() {
  stopPreview();pauseAll();roles.forEach(role=>role.editor?.dispose());clearTimeout(pollTimer);
  projectId=null;project=null;roles=[];analysisPending=false;lyrics=null;lyricLine=-2;suggestion=null;
  for(const id of ['roles','takeLibrary','mixDelays','markers','effectProposalList'])$(id).replaceChildren();
  document.querySelectorAll('audio').forEach(audio=>{audio.removeAttribute('src');audio.load();});
  document.querySelectorAll('dialog[open]').forEach(dialog=>dialog.close());
  $('file').value='';$('lyricsText').value='';$('songArtist').value='';$('songTitle').value='';
  $('lyricsSuggestion').hidden=true;$('resultBox').hidden=true;$('resumeProject').hidden=true;
  $('analysisStatus').textContent='';$('renderStatus').textContent='';
  $('uploadCard').classList.remove('working');$('status').textContent='Выбери песню или перетащи файл сюда.';
  history.replaceState(null,'',location.pathname+'#sessionStage');
  paintLyrics(0);window.studioFlow.uploading();syncControls();
  window.showRenderFeedback?.(null,false);
}
function pollProject() {
  const current=projectId; clearTimeout(pollTimer);
  const check = async () => {
    if (current !== projectId) return;
    try {
      const state=await request('/api/job?id='+current);
      if (current !== projectId) return;
      if (state.state === 'ready') {
        const changed=analysisPending&&state.analysis_state!=='processing';
        analysisPending=state.analysis_state==='processing';
        if (!project || changed) showProject(state);
        else project=state;
        syncControls();
        if (state.lyrics_state === 'processing') $('lyricsStatus').textContent='Привязываю текст локально. Первая загрузка модели и длинная песня могут занять несколько минут…';
        if (state.lyrics_state === 'error') $('lyricsStatus').textContent='Не удалось привязать текст: '+state.lyrics_error;
        if (state.lyrics && state.lyrics_state !== 'processing' && JSON.stringify(state.lyrics)!==JSON.stringify(lyrics)) {
          lyrics=state.lyrics; if (!$('lyricsText').value.trim()) $('lyricsText').value=lyrics.text; $('lyricsStatus').textContent=lyrics.notice; lyricLine=-2; paintLyrics(0);
        }
        $('analysisStatus').textContent=state.analysis_state==='processing' ? 'Обрабатываю вокал и партии. Это может занять несколько минут; записи сохраняются…' : state.analysis_state==='error' ? state.analysis_error : '';
        if (state.lyrics_state==='processing' || state.analysis_state==='processing') pollTimer=setTimeout(check,1800);
        return;
      }
      if (state.state==='error') { $('status').textContent='Не удалось обработать песню: '+state.error; $('uploadCard').classList.remove('working'); return; }
      $('status').textContent=state.state; pollTimer=setTimeout(check,1500);
    } catch(error) {
      if (current !== projectId) return;
      $('status').textContent=error.message; $('uploadCard').classList.remove('working'); localStorage.removeItem('karaokeProject');
    }
  };
  check();
}
function showProject(state) {
  project=state; $('uploadCard').classList.remove('working'); $('status').textContent=`Открыта песня «${state.filename||'Сохранённый проект'}» · ${seconds(state.duration)}. Нажми «Дальше».`;
  roles.forEach(role=>role.editor?.dispose()); $('roles').replaceChildren(); $('takeLibrary').replaceChildren(); $('mixDelays').replaceChildren(); roles=state.roles.map(role=>({...role}));
  $('instrumental').src=audioUrl('instrumental'); $('vocals').src=audioUrl('vocals');
  $('songArtist').value=state.song_info?.artist||''; $('songTitle').value=state.song_info?.title||'';
  if(state.lyrics_candidate) showSuggestion(state.lyrics_candidate);
  else if(state.song_info?.artist&&state.song_info?.title&&!localStorage.getItem('lyrics-looked-'+projectId)) {
    localStorage.setItem('lyrics-looked-'+projectId,'1'); findLyrics();
  }
  for (const role of roles) buildRole(role);
  const chips=element('div','chips');
  for (const marker of state.markers.slice(0,24)) chips.append(element('span','chip',`${seconds(marker.time)} · ${marker.tags.join(', ')}`));
  $('markers').replaceChildren(chips); $('resultBox').hidden=!state.renders?.length;
  if (state.renders?.length) { $('result').src=audioUrl(state.renders.at(-1)); $('download').href=$('result').src; }
  window.showRenderFeedback?.(state.renders?.at(-1),!!state.render_diagnostics?.[state.renders?.at(-1)],state.render_diagnostics?.[state.renders?.at(-1)],state.render_ratings?.[state.renders?.at(-1)]); window.studioFlow.ready(roles,!!state.renders?.length); window.loadEffectProposals?.(); syncControls();
}
function activeTakes(role) {
  const latest=new Map();
  for (const take of project.tracks.filter(track=>track.role===role.id)) latest.set(JSON.stringify(take.region||[0,project.duration]),take);
  return project.tracks.filter(take=>take.role===role.id && latest.get(JSON.stringify(take.region||[0,project.duration]))===take);
}
function buildRole(role) {
  const card=element('div','track'); card.dataset.role=role.id;
  card.append(element('h3','role-title',role.name));
  const guide=element('audio'); guide.hidden=true; guide.preload='metadata'; guide.src=audioUrl('guide-'+role.id); role.guide=guide;card.append(guide);
  role.editor=new VocalEditor(role);card.append(role.editor.node);$('roles').append(card);
  role.clipBox=element('div','clip-list');role.clipBox.dataset.role=role.id;
  const history=element('section','take-history');history.append(element('h3','',role.name),role.clipBox);$('takeLibrary').append(history);
  paintTakes(role);
}
function paintTakes(role) {
  document.querySelectorAll('#mixDelays [data-role]').forEach(node=>{if(node.dataset.role===role.id)node.remove();});
  const delays=element('section','mix-delay-role');delays.dataset.role=role.id;delays.append(element('strong','',role.name));$('mixDelays').append(delays);
  role.clipBox.replaceChildren(); role.takes=activeTakes(role);
  if(!role.takes.length)role.clipBox.append(element('p','subtle','Пока нет записей для этой партии.'));
  for (const take of role.takes) {
    const box=element('div','clip'), range=take.region||[0,project.duration];
    box.append(element('strong','',`Дубль · ${seconds(range[0],true)} — ${seconds(range[1],true)}`));
    const audio=element('audio'); audio.controls=true; audio.preload='metadata'; audio.src=audioUrl(take.id); audio.dataset.songStart=take.start||0; box.append(audio);
    const label=element('label','control','Сдвиг голоса: минус — раньше, плюс — позже');
    const saved=Number(localStorage.getItem('offset-'+projectId+'-'+take.id)||localStorage.getItem('offset-'+projectId+'-'+role.id)||0);
    const offset=element('input'); Object.assign(offset,{type:'range',min:Math.min(-1,saved),max:Math.max(1,saved),step:'0.01',value:saved});
    offset.id='offset-'+take.id;offset.setAttribute('aria-label','Задержка дубля');
    const value=element('output','offset-value');const current=projectId;
    const update=()=>{value.textContent=`${Number(offset.value)>0?'+':''}${Math.round(Number(offset.value)*1000)} мс`;localStorage.setItem('offset-'+current+'-'+take.id,offset.value);};update();offset.addEventListener('input',()=>{update();window.studioFlow.dirty();});
    take.offsetInput=offset;label.append(offset,value);const delay=element('div','mix-delay-take');delay.append(element('span','subtle',`${seconds(range[0],true)} — ${seconds(range[1],true)}`),label,button('▶ Проверить с музыкой',event=>previewTake(take,event.currentTarget)));
    const seekDetails=element('details','delay-seek'),seekLabel=element('label','control','Момент проверки'),seek=element('input');
    Object.assign(seek,{type:'range',min:range[0],max:Math.max(range[0],range[1]-.1),step:.1,value:Math.max(range[0],Math.min(range[1]-.1,role.segments.find(s=>s[1]>range[0]&&s[0]<range[1])?.[0]??range[0]))});
    seek.setAttribute('aria-label','Момент проверки задержки');const seekValue=element('output','subtle');seekValue.textContent=seconds(Number(seek.value),true);seek.addEventListener('input',()=>seekValue.textContent=seconds(Number(seek.value),true));take.previewSeek=seek;
    seekLabel.append(seek,seekValue);seekDetails.append(element('summary','','Выбрать момент проверки'),seekLabel);delay.append(seekDetails);delays.append(delay);role.clipBox.append(box);
  }
  role.editor?.refresh();
}
async function editSegment(role,index,action,range) {
  if (busy()) return; mutating=true; stopPreview(); pauseAll(); syncControls();
  const selected=role.editor.range.slice();
  try { showProject(await post('segment',{role:role.id,index,action,range}));roles.find(item=>item.id===role.id)?.editor.setRange(selected);window.studioFlow.dirty(); }
  catch(error) { $('recordStatus').textContent=error.message; }
  finally { mutating=false; syncControls(); }
}
function stopPreview() {
  previewGeneration++; clearTimeout(previewTimer);
  for (const node of previewNodes) { try { node.stop(); } catch{} node.disconnect(); }
  previewNodes=[];
  for (const control of document.querySelectorAll('.mix-delay-take .preview-button')) { control.textContent='▶ Проверить с музыкой'; control.disabled=busy(); }
}
async function previewTake(take, control) {
  if (busy()) return;
  if (previewNodes.length) { stopPreview(); return; }
  stopPreview(); pauseAll(); const generation=previewGeneration, current=projectId;
  control.disabled=true; control.textContent='Загружаю звук…';
  try {
    previewContext ||= new AudioContext(); await previewContext.resume();
    if(!previewGain){previewGain=previewContext.createGain();previewGain.connect(previewContext.destination);}
    previewGain.gain.value=monitorVolume;
    const decode=async name=> { const r=await fetch(`/api/audio?id=${current}&name=${name}`); if (!r.ok) throw new Error('Не удалось загрузить аудио'); return previewContext.decodeAudioData(await r.arrayBuffer()); };
    const buffers=await Promise.all([decode('instrumental'),decode(take.id)]);
    if (generation!==previewGeneration || current!==projectId || busy()) return;
    const offset=Number(take.offsetInput.value);
    if (!Number.isFinite(offset)||Math.abs(offset)>5) throw new Error('Задержка должна быть от −5 до +5 секунд');
    const range=take.region||[0,project.duration], seek=Math.max(0,Number(take.previewSeek?.value??range[0])-.5), voiceSeek=seek-(take.start||0)-offset;
    const length=Math.min(15,range[1]-seek+.5,buffers[0].duration-seek), at=previewContext.currentTime+.1;
    const music=previewContext.createBufferSource(), voice=previewContext.createBufferSource();
    music.buffer=buffers[0]; voice.buffer=buffers[1]; music.connect(previewGain); voice.connect(previewGain); music.start(at,seek,length);
    if (Math.max(0,voiceSeek)<voice.buffer.duration) voice.start(at+Math.max(0,-voiceSeek),Math.max(0,voiceSeek),length);
    previewNodes=[music,voice]; control.textContent='■ Остановить проверку'; previewTimer=setTimeout(stopPreview,(length+.3)*1000);
  } catch(error) { if (generation===previewGeneration) { stopPreview(); $(window.studioStage?.stage==='mix'?'renderStatus':'recordStatus').textContent=error.message; } }
  finally { if (generation===previewGeneration) { control.disabled=busy(); if (!previewNodes.length) control.textContent='▶ Проверить с музыкой'; } }
}
const pauseFor = ms => new Promise(resolve=>setTimeout(resolve,ms));
function waitAudio(audio,event,signal) {
  return new Promise((resolve,reject)=>{
    const timeout=setTimeout(()=>finish(new Error('Музыка не загрузилась. Попробуй запись ещё раз.')),15000);
    const ready=()=>finish(), failed=()=>finish(new Error('Не удалось открыть музыку')), cancelled=()=>finish(new Error('Запись отменена'));
    function finish(error) { clearTimeout(timeout); audio.removeEventListener(event,ready); audio.removeEventListener('error',failed); signal.removeEventListener('abort',cancelled); error?reject(error):resolve(); }
    audio.addEventListener(event,ready,{once:true}); audio.addEventListener('error',failed,{once:true}); signal.addEventListener('abort',cancelled,{once:true});
    if(signal.aborted) cancelled();
  });
}
async function prepareMusic(audio,start,signal) {
  if(audio.readyState===0) { audio.preload='auto'; audio.load(); await waitAudio(audio,'loadedmetadata',signal); }
  audio.currentTime=start;
  if(audio.seeking) await waitAudio(audio,'seeked',signal);
  if(audio.readyState<2) await waitAudio(audio,'canplay',signal);
}
async function startRecording(role, range=null) {
  if(window.engineCompatible===false){$('recordStatus').textContent='Версии экрана и обработки различаются. Перезапусти студию обновлённым ярлыком.';return;}
  if (busy()) return;
  if(window.voiceSetup&&!window.voiceSetup.beforeRecording())return;
  stopPreview(); pauseAll(); recording=true; syncControls();
  const session=recordSession={cancelled:false,controller:new AbortController()}; let microphone;
  const current=projectId, cue=range||[0,project.duration], start=Math.max(0,cue[0]-3), end=Math.min(project.duration,cue[1]+.6);
  $('recordStatus').textContent='Подключаю микрофон…';
  try {
    if (!window.MediaRecorder || !navigator.mediaDevices) throw new Error('Открой студию в современном браузере по локальному адресу');
    microphone=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:false,noiseSuppression:false,autoGainControl:false}});
    $('recordStatus').textContent='Подготавливаю музыку к выбранному моменту…';
    await prepareMusic($('instrumental'),start,session.controller.signal);
    for (let count=3;count>0;count--) {
      if (session.cancelled) throw new Error('Отсчёт отменён');
      $('countIn').hidden=false; $('countIn').textContent=count; $('recordStatus').textContent='Приготовься. Музыка начнётся перед выбранным фрагментом.'; await pauseFor(1000);
    }
    if (session.cancelled) throw new Error('Запись отменена');
    $('countIn').hidden=true;
    const mime=['audio/webm;codecs=opus','audio/webm','audio/ogg;codecs=opus'].find(type=>MediaRecorder.isTypeSupported(type));
    const take=recorder=new MediaRecorder(microphone,mime?{mimeType:mime}:undefined), chunks=[];
    take.ondataavailable=event=>{ if(event.data.size) chunks.push(event.data); };
    take.onstop=async()=>{
      $('instrumental').pause(); microphone.getTracks().forEach(track=>track.stop()); $('stop').hidden=true; $('recordStatus').textContent='Сохраняю фрагмент…';
      try {
        if (session.cancelled) { $('recordStatus').textContent='Запись отменена'; return; }
        const stopAt=Math.min(end,Math.max(cue[0],$('instrumental').currentTime));
        if (stopAt<=cue[0]) throw new Error('Ты остановил запись до начала фрагмента. Попробуй ещё раз.');
        const params=new URLSearchParams({id:current,role:role.id,start,end, cue_start:cue[0],cue_end:Math.min(cue[1],stopAt)});
        const track=await request('/api/track?'+params,{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:new Blob(chunks,{type:take.mimeType})});
        if(current===projectId) { project.tracks.push(track); paintTakes(role); window.studioFlow.dirty(); }
        $('recordStatus').textContent='Фрагмент сохранён. Можно записать следующий или продолжить.';
      } catch(error) { $('recordStatus').textContent=error.message; }
      finally { recording=false; recorder=null; recordSession=null; syncControls(); }
    };
    take.onerror=()=>{ session.cancelled=true; if(take.state==='recording') take.stop(); };
    take.start();
    try { await $('instrumental').play(); } catch(error) { take.onstop=null; take.stop(); throw error; }
    $('recordStatus').textContent=`Запись: ${role.name} · вступление с ${seconds(start)}, пой с ${seconds(cue[0])} до ${seconds(cue[1])}.`; session.end=end;
  } catch(error) {
    microphone?.getTracks().forEach(track=>track.stop()); recording=false; recorder=null; recordSession=null; $('countIn').hidden=true; syncControls(); $('recordStatus').textContent=error.message;
  }
}
$('stop').addEventListener('click',()=>{ if (recorder?.state==='recording') recorder.stop(); else if (recordSession) {recordSession.cancelled=true;recordSession.controller.abort();} });
$('instrumental').addEventListener('timeupdate',()=>{ if(recorder?.state==='recording' && recordSession?.end && $('instrumental').currentTime>=recordSession.end) recorder.stop(); });
$('instrumental').addEventListener('ended',()=>{ if(recorder?.state==='recording') recorder.stop(); });
async function render() {
  if(window.engineCompatible===false){$('renderStatus').textContent='Старая фоновая обработка ещё запущена. Перезапусти студию обновлённым ярлыком.';return;}
  if (busy()) return;
  const tracks=roles.flatMap(role=>activeTakes(role).map(take=>({id:take.id,offset:Number($('offset-'+take.id)?.value||0)})));
  if(!tracks.length) { $('renderStatus').textContent='Сначала запиши хотя бы один фрагмент.'; return; }
  if(tracks.some(t=>!Number.isFinite(t.offset)||Math.abs(t.offset)>5)) { $('renderStatus').textContent='Задержка должна быть от −5 до +5 секунд'; return; }
  stopPreview(); pauseAll(); rendering=true; syncControls(); $('renderStatus').textContent='Собираю фрагменты, выравниваю громкость и применяю обработку…';
  try {
    const result=await post('render',{tracks,autotune:$('autotune').checked,tune_mode:$('tuneMode').value,tune_settings:window.tuneSettings?.(),pitch_falls:$('pitchFalls').checked,vocal_db:Number($('vocalGain').value),space:$('space').value});
    window.showRenderFeedback?.(result.render_id,true,result.diagnostics); window.loadPersonalProfile?.(); $('result').src=result.url; $('download').href=result.url; $('resultBox').hidden=false; window.studioFlow.result(); $('renderStatus').textContent='Готово. Нажми «Перейти к прослушиванию».';
  } catch(error) { $('renderStatus').textContent=error.message; }
  finally { rendering=false; syncControls(); }
}
function paintLyrics(time) {
  const displays=[$('karaokeDisplay'),$('listenLyrics')];
  if(!lyrics?.lines?.length) { for(const display of displays) display.replaceChildren(element('span','subtle','Открой «Текст караоке», чтобы добавить слова песни.')); return; }
  let index=lyrics.lines.findIndex(line=>time>=line.start&&time<line.end);
  if(index<0) index=lyrics.lines.findIndex(line=>line.start>time);
  if(index<0) index=lyrics.lines.length-1;
  if(index!==lyricLine) {
    lyricLine=index;
    for(const display of displays) {
      const now=element('div','lyric-line');
      for(const word of lyrics.lines[index].words) {
        const node=button(word.text+' ',()=>{
          if(busy()) return;
          const role=document.querySelector('.track:not([hidden])')?.dataset.role;
          if(!role) return;
          roles.find(item=>item.id===role).editor.setRange([Math.max(0,word.start-.1),Math.min(project.duration,word.end+.2)]);
          $('recordStatus').textContent='Слово выделено на волне. Нажми кнопку записи.';
        },'lyric-word');
        now.append(node);
      }
      const following=lyrics.lines[index+1]; display.replaceChildren(now,element('div','lyric-next',following?following.words.map(word=>word.text).join(' '):''));
    }
  }
  displays.forEach(display=>[...display.querySelectorAll('.lyric-word')].forEach((node,i)=>{
    const word=lyrics.lines[index].words[i], progress=Math.max(0,Math.min(1,(time-word.start)/Math.max(.05,word.end-word.start)));
    node.style.setProperty('--word-progress',progress*100+'%'); node.classList.toggle('current',time>=word.start&&time<word.end);
  }));
}
document.addEventListener('play',event=>{
  if (!(event.target instanceof HTMLAudioElement)) return;
  event.target.volume=monitorVolume; lyricSource=event.target; cancelAnimationFrame(lyricFrame);
  const tick=()=>{ if(!lyricSource) return; paintLyrics(lyricSource.currentTime+Number(lyricSource.dataset.songStart||0)); if(!lyricSource.paused) lyricFrame=requestAnimationFrame(tick); }; tick();
},true);
document.addEventListener('seeked',event=>{ if(event.target instanceof HTMLAudioElement) paintLyrics(event.target.currentTime+Number(event.target.dataset.songStart||0)); },true);
async function synchronizeLyrics(method,automatic=false) {
  if(!projectId||busy()) return;
  try { await post('lyrics',{text:automatic?'':$('lyricsText').value,method,source:suggestion?.source||'Текст пользователя'}); pollProject(); }
  catch(error) { $('lyricsStatus').textContent=error.message; }
}
function showSuggestion(candidate) {
  suggestion=candidate; $('lyricsSuggestion').hidden=!suggestion.found;
  $('suggestionName').textContent=suggestion.found?`${suggestion.artist} — ${suggestion.title} · ${suggestion.source}`:'';
}
async function findLyrics() {
  if(!projectId) return; const current=projectId; $('findLyrics').disabled=true; $('lyricsStatus').textContent='Ищу текст по названию и исполнителю…';
  try {
    const candidate=await post('lyrics-find',{artist:$('songArtist').value,title:$('songTitle').value});
    if(current!==projectId) return;
    showSuggestion(candidate);
    $('lyricsStatus').textContent=suggestion.found?'Текст найден. Проверь название и нажми «Добавить найденный текст».':'Текст не найден. Его можно вставить или загрузить файлом.';
  } catch(error) { if(current===projectId) $('lyricsStatus').textContent=error.message; }
  finally { if(current===projectId) $('findLyrics').disabled=false; }
}
$('findLyrics').addEventListener('click',findLyrics);
$('useLyrics').addEventListener('click',()=>{ $('lyricsText').value=suggestion.text; $('lyricsSuggestion').hidden=true; $('lyricsStatus').textContent='Текст добавлен. Теперь привяжи слова к аудио.'; });
$('alignLyrics').addEventListener('click',()=>synchronizeLyrics('audio'));
$('transcribeLyrics').addEventListener('click',()=>synchronizeLyrics('audio',true));
$('loadLrc').addEventListener('click',()=>synchronizeLyrics('lrc'));
$('lyricsFile').addEventListener('change',async event=>{ const file=event.target.files[0]; if(!file) return; if(file.size>100000) { $('lyricsStatus').textContent='Текстовый файл слишком большой'; return; } $('lyricsText').value=await file.text(); });
$('reanalyze').addEventListener('click',async()=>{
  if(busy()) return; stopPreview(); pauseAll();
  try { await post('reanalyze',{separate:true}); analysisPending=true; syncControls(); pollProject(); } catch(error) { $('analysisStatus').textContent=error.message; }
});
$('vocalGain').addEventListener('input',()=>{ const value=Number($('vocalGain').value); $('vocalGainValue').textContent=value===0?'автоматически':`${value>0?'+':''}${value} дБ к автоматическому уровню`; });
for(const id of ['vocalGain','space','autotune','tuneMode','pitchFalls'])$(id).addEventListener('input',()=>window.studioFlow.dirty());
$('chooseFile').addEventListener('click',()=>{if(!busy())$('file').click();});
$('newSong').addEventListener('click',()=>{if(!recording&&!rendering&&!uploading&&!mutating&&!calibrating)resetProject();});
$('file').addEventListener('change',event=>{const file=event.target.files[0];event.target.value='';upload(file);});
$('drop').addEventListener('dragover',event=>{ event.preventDefault(); $('drop').classList.add('over'); });
$('drop').addEventListener('dragleave',()=> $('drop').classList.remove('over'));
$('drop').addEventListener('drop',event=>{ event.preventDefault(); $('drop').classList.remove('over'); upload(event.dataTransfer.files[0]); });
$('render').addEventListener('click',render);
projectId=new URLSearchParams(location.search).get('project');
if(projectId) pollProject();
else {
  const saved=localStorage.getItem('karaokeProject');
  if(saved&&/^[a-f0-9]{32}$/.test(saved))request('/api/job?id='+saved).then(state=>{
    if(projectId||uploading||state.state!=='ready')return;
    $('resumeProject').textContent='Продолжить прошлую песню: '+(state.filename||'сохранённый проект');$('resumeProject').hidden=false;
    $('resumeProject').onclick=()=>{if(busy())return;projectId=saved;$('resumeProject').hidden=true;history.replaceState(null,'','?project='+saved+'#sessionStage');pollProject();};
  }).catch(()=>{});
}
