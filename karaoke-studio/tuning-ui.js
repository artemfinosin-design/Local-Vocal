/* Preset values come from the same backend definitions that render the audio. */
(() => {
  const keys={strength:'tuneStrength',speed_ms:'tuneSpeed',tolerance_cents:'tuneTolerance'};
  let presets={},modified=false;
  window.tuneSettings=()=>Object.fromEntries([...Object.entries(keys).map(([key,id])=>[key,Number($(id).value)]),['voice_type',$('tuneVoice').value]]);
  function refresh() {
    $('tuneStrengthValue').textContent=$('tuneStrength').value+'%';
    $('tuneSpeedValue').textContent=$('tuneSpeed').value+' мс';
    $('tuneToleranceValue').textContent=$('tuneTolerance').value+' центов';
    $('tuneDetails').disabled=!$('autotune').checked;
    $('tuneDescription').textContent=(modified?'Пресет с твоими изменениями. ':'')+(presets[$('tuneMode').value]?.description||'');
  }
  function save() {localStorage.setItem('tunePreferences',JSON.stringify({mode:$('tuneMode').value,settings:window.tuneSettings(),modified,saved_at:Date.now()}));refresh();window.studioFlow.dirty();}
  $('tuneMode').addEventListener('change',()=>{const preset=presets[$('tuneMode').value];if(!preset)return;for(const [key,id] of Object.entries(keys))$(id).value=preset[key];modified=false;save();});
  for(const id of [...Object.values(keys),'tuneVoice'])$(id).addEventListener('input',()=>{modified=true;save();});
  $('autotune').addEventListener('change',refresh);refresh();
  Promise.all([request('/api/tune-presets'),request('/api/personal-profile')]).then(([result,personal])=>{
    presets=result.presets;$('tuneMode').replaceChildren();
    for(const [key,preset] of Object.entries(presets)){const option=element('option','',preset.name);option.value=key;$('tuneMode').append(option);}
    let local;try{local=JSON.parse(localStorage.getItem('tunePreferences'));}catch{} const remote=personal.preferences;let saved=local&&(local.saved_at||0)>=(remote?.saved_at||0)?local:remote;
    $('tuneMode').value=presets[saved?.mode]?saved.mode:'melody';
    for(const [key,id] of Object.entries(keys)){
      const value=saved?.settings?.[key];$(id).value=typeof value==='number'&&Number.isFinite(value)?Math.max(Number($(id).min),Math.min(Number($(id).max),value)):presets[$('tuneMode').value][key];
    }
    if([...$('tuneVoice').options].some(option=>option.value===saved?.settings?.voice_type))$('tuneVoice').value=saved.settings.voice_type;
    if(saved){if(typeof saved.autotune==='boolean')$('autotune').checked=saved.autotune;if(typeof saved.pitch_falls==='boolean')$('pitchFalls').checked=saved.pitch_falls;if([...$('space').options].some(o=>o.value===saved.space))$('space').value=saved.space;if(Number.isFinite(saved.vocal_db)){$('vocalGain').value=saved.vocal_db;$('vocalGainValue').textContent=saved.vocal_db?saved.vocal_db+' дБ':'автоматически';}} modified=!!saved?.modified;refresh();
  }).catch(error=>{$('tuneDescription').textContent='Не удалось загрузить пресеты: '+error.message;});
})();

/* Local adaptation is visible, reversible, and separate from microphone calibration. */
(() => {
  let currentRender=null,currentProject=null;
  function paint(personal){
    $('personalEnabled').checked=personal.enabled;
    const range=personal.range_hz?` · рабочий диапазон ${Math.round(personal.range_hz[0])}–${Math.round(personal.range_hz[1])} Гц`:'';
    const speed=personal.speed_ms>20?` · подстройка не быстрее ${personal.speed_ms} мс`:'';
    $('personalStatus').textContent=`${personal.enabled?'Профиль включён':'Профиль выключен'} · изучено наборов записей: ${personal.examples} · оценок: ${personal.ratings}${range}${speed}. Настройки сохраняются после сборки.`;
    $('exportPersonal').href='/api/personal-profile-export'+(projectId?'?id='+projectId:'');
  }
  window.loadPersonalProfile=async()=>{try{paint(await request('/api/personal-profile'));}catch(e){$('personalStatus').textContent=e.message;}};
  async function change(body){if(busy())return;mutating=true;syncControls();try{paint(await request('/api/personal-profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}));window.studioFlow.dirty();}catch(e){$('personalStatus').textContent=e.message;}finally{mutating=false;syncControls();}}
  $('personalEnabled').addEventListener('change',()=>change({action:'enabled',enabled:$('personalEnabled').checked}));
  let confirming=false;
  $('resetPersonal').addEventListener('click',async()=>{if(busy())return;if(!confirming){confirming=true;$('resetPersonal').textContent='Подтвердить сброс профиля';return;}await change({action:'reset'});confirming=false;$('resetPersonal').textContent='Сбросить личный профиль';});
  window.showRenderFeedback=(render,available)=>{currentRender=render;currentProject=projectId;$('renderRating').hidden=!available||!render;$('ratingStatus').textContent='Оценка сохраняется локально и влияет на следующие сборки. Можно изменить её.';window.loadPersonalProfile();};
  for(const button of $('renderRating').querySelectorAll('[data-rating]'))button.addEventListener('click',async()=>{
    if(busy()||!currentRender||projectId!==currentProject)return;
    mutating=true;syncControls();$('renderRating').querySelectorAll('button').forEach(b=>b.disabled=true);
    try{paint(await post('render-rating',{render_id:currentRender,rating:button.dataset.rating}));$('ratingStatus').textContent='Оценка сохранена. Новые параметры применятся при следующей сборке.';}
    catch(e){$('ratingStatus').textContent=e.message;}finally{mutating=false;syncControls();$('renderRating').querySelectorAll('button').forEach(b=>b.disabled=false);}
  });
  window.loadPersonalProfile();if(project)window.showRenderFeedback(project.renders?.at(-1),!!project.render_diagnostics?.[project.renders?.at(-1)]);
})();
