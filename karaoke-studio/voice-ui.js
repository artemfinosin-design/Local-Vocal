/* Calibration recordings are temporary; sharing always requires a separate choice. */
(() => {
  const dialog=window.studioDialogs.voice, box=dialog.querySelector('.dialog-content');
  box.innerHTML=`<p>Надень наушники и оставь микрофон на том расстоянии, с которого будешь петь. Музыка во время настройки не играет.</p><ol class="voice-steps"><li>2 секунды тишины — измерим шум.</li><li>Тяни «а» 4 секунды на удобной ноте.</li><li>Ещё 4 секунды на комфортной низкой ноте.</li><li>Ещё 4 секунды на комфортной высокой ноте.</li></ol><div class="voice-monitor"><strong id="voicePrompt">Готов к настройке</strong><span id="voiceNote">Микрофон пока выключен</span><meter id="voiceMeter" min="0" max="1" value="0" aria-label="Уровень микрофона"></meter><progress id="voiceProgress" max="14" value="0" aria-label="Прогресс настройки"></progress></div><div class="voice-actions"><button id="startVoice" class="primary">Начать настройку</button><button id="cancelVoice" class="danger" hidden>Остановить</button><button id="resetVoice" class="preview-button">Сбросить настройку</button><button id="skipVoice" class="preview-button">Сейчас без настройки</button></div><p id="voiceStatus" class="status" role="status" aria-live="polite"></p><p class="subtle">Сохраняются только измерения диапазона и шума. Запись настройки удаляется после анализа. Повтори настройку при смене микрофона или условий. Это настройка распознавания нот, а не изменение твоего тембра.</p>`;
  let profile=null, session=null;
  const names=['До','До♯','Ре','Ре♯','Ми','Фа','Фа♯','Соль','Соль♯','Ля','Ля♯','Си'];
  function note(hz) {const midi=Math.round(69+12*Math.log2(hz/440));return names[((midi%12)+12)%12]+(Math.floor(midi/12)-1);}
  function showProfile() {
    $('resetVoice').disabled=!profile;
    $('voiceStatus').textContent=profile?`Настройка сохранена · ${note(profile.low_hz)} — ${note(profile.high_hz)}. Диапазон и шум будут учтены при следующей сборке.`:'Настройки пока нет. Можно петь и без неё, но сначала лучше проверить микрофон.';
  }
  async function loadProfile() {
    try { profile=(await request('/api/voice-profile')).profile;showProfile(); }
    catch(error) {$('voiceStatus').textContent='Не удалось прочитать настройку: '+error.message;}
  }
  $('openVoice').addEventListener('click',()=>{if(busy())return;dialog.showModal();loadProfile();});
  $('skipVoice').addEventListener('click',()=>{if(session)return;sessionStorage.setItem('voiceSetupSkipped','1');dialog.close();$('recordStatus').textContent='Настройка пропущена. Нажми запись, чтобы начать петь.';});
  window.voiceSetup={beforeRecording(){if(profile||sessionStorage.getItem('voiceSetupSkipped'))return true;$('openVoice').click();return false;}};
  loadProfile();
  $('resetVoice').addEventListener('click',async()=>{
    if(busy())return;
    try {await request('/api/voice-profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'reset'})});profile=null;sessionStorage.removeItem('voiceSetupSkipped');showProfile();}
    catch(error) {$('voiceStatus').textContent=error.message;}
  });
  function livePitch(values, rate) {
    const signal=new Float32Array(values.length/4);
    for(let i=0;i<signal.length;i++)signal[i]=values[i*4];
    rate/=4;
    let best=0, period=0;const scores=[];
    for(let lag=Math.floor(rate/1100);lag<=Math.ceil(rate/50);lag++) {
      let cross=0,a=0,b=0;
      for(let i=lag;i<signal.length;i++){cross+=signal[i]*signal[i-lag];a+=signal[i]**2;b+=signal[i-lag]**2;}
      const score=cross/Math.sqrt(a*b+1e-20);
      scores[lag]=score;if(score>best){best=score;period=lag;}
    }
    for(let lag=Math.floor(rate/1100)+1;lag<Math.ceil(rate/50);lag++)if(scores[lag]>Math.max(.7,best*.9)&&scores[lag]>scores[lag-1]&&scores[lag]>=scores[lag+1])return rate/lag;
    return best>.7?rate/period:0;
  }
  function cancel() {if(session){session.cancelled=true;session.controller.abort();if(session.recorder?.state==='recording')session.recorder.stop();}}
  $('cancelVoice').addEventListener('click',cancel);
  dialog.addEventListener('close',cancel);
  $('startVoice').addEventListener('click',async()=>{
    if(busy())return;
    stopPreview();pauseAll();calibrating=true;syncControls();
    $('startVoice').disabled=$('resetVoice').disabled=$('skipVoice').disabled=true;$('cancelVoice').hidden=false;
    $('voiceProgress').value=0;$('voiceStatus').textContent='Подключаю микрофон…';
    const current=session={cancelled:false,controller:new AbortController()};
    let stream,context,timer,source;
    try {
      if(!window.MediaRecorder||!navigator.mediaDevices)throw new Error('Для записи нужен доступ к микрофону.');
      stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:false,noiseSuppression:false,autoGainControl:false}});
      if(current.cancelled)throw new Error('Настройка отменена');
      context=new AudioContext();await context.resume();
      const analyser=context.createAnalyser();analyser.fftSize=4096;
      source=context.createMediaStreamSource(stream);source.connect(analyser);
      const values=new Float32Array(analyser.fftSize),chunks=[],noise=[];
      const mime=['audio/webm;codecs=opus','audio/webm','audio/ogg;codecs=opus'].find(type=>MediaRecorder.isTypeSupported(type));
      const take=current.recorder=new MediaRecorder(stream,mime?{mimeType:mime}:undefined);
      const stopped=new Promise((resolve,reject)=>{take.onstop=resolve;take.onerror=()=>reject(new Error('Микрофон перестал записывать.'));});
      take.ondataavailable=event=>{if(event.data.size)chunks.push(event.data);};
      if(current.cancelled)throw new Error('Настройка отменена');
      take.start();const start=performance.now();let previous=-1;
      timer=setInterval(()=>{
        const elapsed=(performance.now()-start)/1000;
        if(current.cancelled||elapsed>=14){if(take.state==='recording')take.stop();return;}
        analyser.getFloatTimeDomainData(values);
        const rms=Math.sqrt(values.reduce((sum,v)=>sum+v*v,0)/values.length),peak=values.reduce((max,v)=>Math.max(max,Math.abs(v)),0);
        $('voiceMeter').value=Math.min(1,rms*6);$('voiceProgress').value=elapsed;
        const phase=elapsed<2?0:elapsed<6?1:elapsed<10?2:3;
        if(phase!==previous){$('voicePrompt').textContent=['Помолчи — измеряем шум','Тяни «а» · удобная нота','Тяни «а» · ниже, но комфортно','Тяни «а» · выше, без напряжения'][phase];previous=phase;}
        if(!phase)noise.push(rms);
        const floor=noise.length?noise.reduce((a,b)=>a+b,0)/noise.length:0;
        const hz=phase&&rms>Math.max(.0001,floor*2)?livePitch(values,context.sampleRate):0;
        $('voiceNote').textContent=peak>.98?'Слишком громко — отодвинься':hz?`${note(hz)} · ${Math.round(hz)} Гц`:phase?'Тяни ровную ноту, не шепчи':'Слушаем тишину';
        $('voiceStatus').textContent=`${Math.floor(elapsed)} / 14 секунд · следуй подсказке выше`;
      },120);
      await stopped;clearInterval(timer);timer=null;stream.getTracks().forEach(track=>track.stop());
      if(current.cancelled)throw new Error('Настройка отменена. Прежние измерения сохранены.');
      $('voiceProgress').value=14;$('voicePrompt').textContent='Проверяю голос…';$('voiceStatus').textContent='Измеряю ноты и шум. Микрофон уже выключен.';
      profile=(await request('/api/voice-check',{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:new Blob(chunks,{type:take.mimeType}),signal:current.controller.signal})).profile;
      window.studioFlow.dirty();showProfile();$('voicePrompt').textContent='Голос настроен';
    } catch(error) {if(current.recorder?.state==='recording')current.recorder.stop();$('voiceStatus').textContent=current.cancelled?'Настройка отменена.':error.message;$('voicePrompt').textContent='Попробуй ещё раз';}
    finally {
      clearInterval(timer);stream?.getTracks().forEach(track=>track.stop());source?.disconnect();await context?.close();
      session=null;calibrating=false;syncControls();$('startVoice').disabled=$('skipVoice').disabled=false;$('resetVoice').disabled=!profile;$('cancelVoice').hidden=true;$('voiceMeter').value=0;
    }
  });
  const feedback=window.studioDialogs.feedback,contents=feedback.querySelector('.dialog-content');
  contents.innerHTML='<p>Сохрани пример, если хочешь помочь разобраться с обработкой. Передавать его разработчику или кому-либо ещё решаешь ты.</p><div id="feedbackContents" class="feedback-contents"></div><label class="check-option"><input id="feedbackConsent" type="checkbox"> Я хочу сохранить исходную песню и мои записи голоса для добровольной передачи разработчику.</label><p class="subtle">Архив не отправляется автоматически. В ZIP войдут числовой личный профиль и журнал обработки этой песни. Аудио других проектов и запись настройки голоса в него не попадут. Записи берутся до автотюна и сведения; используй наушники, чтобы музыка не попала в микрофон.</p><button id="makeFeedback" class="primary" disabled>Создать ZIP с примером</button><a id="saveFeedback" class="button primary" download="vocal-feedback.zip" hidden>↓ Сохранить ZIP</a><p id="feedbackStatus" class="status" role="status" aria-live="polite"></p>';
  let feedbackSelection=[],feedbackProject;
  $('openFeedback').addEventListener('click',()=>{
    if(busy()||!project)return;
    feedbackProject=projectId;feedbackSelection=roles.flatMap(role=>activeTakes(role).map(take=>({id:take.id,offset:Number($('offset-'+take.id)?.value||0)})));
    $('feedbackConsent').checked=false;$('makeFeedback').disabled=true;$('saveFeedback').hidden=true;
    $('feedbackStatus').textContent=feedbackSelection.length?'Проверь состав архива и отметь согласие.':'Сначала запиши хотя бы один фрагмент.';
    const list=element('ul');list.append(element('li','',`Исходная песня: ${project.filename||'загруженный файл'}`));
    for(const selected of feedbackSelection){const take=project.tracks.find(t=>t.id===selected.id);const region=take.region||[0,project.duration];list.append(element('li','',`${roles.find(r=>r.id===take.role)?.name||take.role} · ${seconds(region[0])} — ${seconds(region[1])} · запись микрофона`));}
    list.append(element('li','','Таймкоды, задержки, личный профиль и журнал обработки этой песни'));
    $('feedbackContents').replaceChildren(list);feedback.showModal();
  });
  $('feedbackConsent').addEventListener('change',()=>{$('makeFeedback').disabled=!$('feedbackConsent').checked||!feedbackSelection.length;});
  $('makeFeedback').addEventListener('click',async()=>{
    if(busy()||!$('feedbackConsent').checked||!feedbackSelection.length||feedbackProject!==projectId)return;
    mutating=true;syncControls();$('makeFeedback').disabled=true;$('feedbackConsent').disabled=true;$('feedbackStatus').textContent='Создаю архив из выбранной песни и записей…';
    try {
      const result=await post('feedback',{consent:true,tracks:feedbackSelection,autotune:$('autotune').checked,tune_mode:$('tuneMode').value,tune_settings:window.tuneSettings?.(),pitch_falls:$('pitchFalls').checked,vocal_db:Number($('vocalGain').value),space:$('space').value});
      $('saveFeedback').href=result.url;$('saveFeedback').hidden=false;$('feedbackStatus').textContent=`ZIP готов · ${(result.bytes/1048576).toFixed(1)} МБ. Сохрани его и передай по своему желанию.`;
    } catch(error) {$('feedbackStatus').textContent=error.message;}
    finally {mutating=false;syncControls();$('feedbackConsent').disabled=false;$('makeFeedback').disabled=!$('feedbackConsent').checked;}
  });
})();
