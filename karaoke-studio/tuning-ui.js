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
    $('tuneMode').value=presets[saved?.mode]?saved.mode:'studio';
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
  window.showRenderFeedback=(render,available,diagnostics,saved)=>{
    currentRender=render;currentProject=projectId;
    $('renderRating').dataset.available=available&&render?'yes':'';
    $('renderRating').hidden=!available||!render;
    $('ratingStatus').textContent=saved?.score?`Сохранено: ${saved.score}/10 · ${saved.mark==='good'?'хорошо':'есть замечания'}`:'Оценка сохраняется локально. Её можно изменить.';
    $('renderRating').querySelectorAll('[name="renderScore"]').forEach(input=>input.checked=Number(input.value)===saved?.score);
    $('ratingReasons').querySelectorAll('input').forEach(input=>input.checked=!!saved?.reasons?.includes(input.value));
    const report=$('performanceReport');report.replaceChildren();
    report.append(element('h4','','Как ты спел — до автотюна'));
    const voices=(diagnostics?.voices||[]).filter(v=>v.performance);
    for(const voice of voices){
      const p=voice.performance,card=element('div','performance-card');
      const hero=element('div','performance-hero'),score=element('div','performance-score',p.hit_percent==null?'—':p.hit_percent+'%');
      score.style.setProperty('--score',(p.hit_percent||0)+'%');score.setAttribute('aria-label','Попадание в ноты: '+(p.hit_percent==null?'недостаточно данных':p.hit_percent+'%'));
      const heading=element('div');heading.append(element('strong','',roles.find(r=>r.id===voice.role)?.name||'Вокал'),element('p','coach-summary',p.summary||'Попадание в мелодию оригинала'));
      hero.append(score,heading);card.append(hero);
      const metrics=element('div','performance-metrics');metrics.append(element('span','',p.hit_percent==null?'Недостаточно нот':'В пределах ±½ полутона'),element('span','',`Отклонение ${p.median_cents??'—'} центов`),element('span','',`Сравнено ${p.compared_seconds} с`));card.append(metrics);
      for(const strength of (p.strengths||[]).slice(0,1))card.append(element('p','coach-strength','✓ '+strength));
      if(p.advice?.length){card.append(element('h4','','На следующем дубле'));const tips=element('ul','coach-advice');for(const tip of p.advice.slice(0,2))tips.append(element('li','',tip));card.append(tips);}
      const measurements=element('details');measurements.append(element('summary','','Подробности и точность оценки'));
      if(p.range_hz)measurements.append(element('p','subtle',`Диапазон ${p.range_hz.join('–')} Гц · перепад громкости ${p.level_spread_db??'—'} дБ · перегруз ${p.clipping_percent??0}%`));
      for(const tip of (p.advice||[]).slice(2))measurements.append(element('p','',tip));
      measurements.append(element('p','subtle','Оценка сухого голоса до автотюна. Октава учитывается; неясные ноты и одобренные спецэффекты пропускаются.'));
      if(p.limits)measurements.append(element('p','subtle',p.limits));card.append(measurements);
      const line=element('div','performance-timeline');
      for(const segment of p.segments||[]){const b=button(`${seconds(segment.start,true)} · ${segment.hit_percent}%`,()=>{$('result').currentTime=segment.start;});b.title=`Слушать ${seconds(segment.start,true)}–${seconds(segment.end,true)}`;b.style.setProperty('--hit',segment.hit_percent+'%');line.append(b);}
      if(line.childElementCount){const details=element('details');details.append(element('summary','','Попадание по фрагментам'),line);card.append(details);}report.append(card);
    }
    if(!voices.length)report.append(element('p','subtle','Для разбора нот собери песню в новой версии.'));
    window.loadPersonalProfile();
  };
  $('reviewFeedback').addEventListener('click',()=>$('openFeedback').click());
  for(const radio of $('renderRating').querySelectorAll('[name="renderScore"]'))radio.addEventListener('change',()=>{$('ratingReasons').open=Number(radio.value)<8;});
  $('saveRating').addEventListener('click',async()=>{
    if(busy()||!currentRender||projectId!==currentProject)return;
    const chosen=$('renderRating').querySelector('[name="renderScore"]:checked');
    if(!chosen){$('ratingStatus').textContent='Выбери оценку от 1 до 10.';return;}
    const score=Number(chosen.value),reasons=[...$('ratingReasons').querySelectorAll('input:checked')].map(input=>input.value);
    mutating=true;syncControls();$('saveRating').disabled=true;
    try{paint(await post('render-rating',{render_id:currentRender,score,reasons}));$('ratingStatus').textContent=`Сохранено ${score}/10 · ${score>=8&&!reasons.length?'отмечено «хорошо», признаки голоса добавлены в профиль':'замечания сохранены'}. Отправки в интернет нет.`;}
    catch(e){$('ratingStatus').textContent=e.message;}finally{mutating=false;syncControls();$('saveRating').disabled=false;}
  });
  window.loadPersonalProfile();if(project)window.showRenderFeedback(project.renders?.at(-1),!!project.render_diagnostics?.[project.renders?.at(-1)],project.render_diagnostics?.[project.renders?.at(-1)],project.render_ratings?.[project.renders?.at(-1)]);
})();
