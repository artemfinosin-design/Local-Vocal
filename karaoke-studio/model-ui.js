/* Adding a vocal example retrains the local estimator. No audio leaves localhost. */
(() => {
  const panel=document.createElement('section');panel.className='learning-panel';
  panel.innerHTML='<span class="eyebrow">ЛОКАЛЬНОЕ ОБУЧЕНИЕ</span><h3>Научи студию слышать обработку</h3><p>Студия учится на вокале новых песен. Можно добавить отдельную вокальную дорожку. Она создаст примеры с известными эффектами, обучится и проверит себя на других фрагментах. Используются только параметры, прошедшие проверку и подтверждённые анализом сигнала. Эхо и стерео измеряются отдельно: прогноз модели не включает эхо сам по себе.</p><label class="button" role="button" tabindex="0">Добавить пример вокала<input id="effectExample" type="file" accept=".mp3,.wav,.flac,.m4a,.ogg,.aac" hidden></label><p id="effectModelStatus" role="status"></p><p class="hint">Вокал из готовой песни уже содержит эффекты. Такое обучение распознаёт добавленную обработку и не восстанавливает исходную цепочку плагинов точно.</p>';
  document.querySelector('#sourcesDialog .dialog-content').prepend(panel);
  const input=panel.querySelector('input'),status=panel.querySelector('[role="status"]');let timer;
  async function refresh() {
    clearTimeout(timer);
    try {
      const response=await fetch('/api/effects-model'),data=await response.json();
      if(!response.ok)throw new Error(data.error);
      input.disabled=data.state==='processing';
      const names=['пространство','длина хвоста','уровень эха','стереоширина'];
      const enabled=data.report?.enabled?.flatMap((on,i)=>on&&i<2?[names[i]]:[])||[];
      status.textContent=data.state==='processing'?data.message:data.state==='error'?data.message:data.report?`В базе: ${data.examples} исходников. Модель обучена на ${data.report.sources.length}. Проверено на ${data.report.test_examples} примерах. Модель помогает оценивать: ${enabled.length?enabled.join(', '):'пока ни к одному параметру; используется осторожный анализ'}.`:'Добавь первый пример — обучение начнётся автоматически.';
      if(data.state==='processing')timer=setTimeout(refresh,1800);
    } catch(error){status.textContent='Не удалось получить состояние модели: '+error.message;}
  }
  panel.querySelector('label').addEventListener('keydown',event=>{if((event.key==='Enter'||event.key===' ')&&!input.disabled){event.preventDefault();input.click();}});
  input.addEventListener('change',async()=>{
    const file=input.files[0];if(!file)return;
    if(file.size>150*1024*1024){status.textContent='Пример должен быть меньше 150 МБ';return;}
    input.disabled=true;status.textContent='Добавляю локальный пример…';
    try {
      const response=await fetch('/api/effects-example?filename='+encodeURIComponent(file.name),{method:'POST',body:file,headers:{'Content-Type':'application/octet-stream'}});
      const data=await response.json();if(!response.ok)throw new Error(data.error);
      refresh();
    } catch(error){status.textContent=error.message;input.disabled=false;}
    finally{input.value='';}
  });
  document.getElementById('openSources').addEventListener('click',refresh);refresh();
})();
