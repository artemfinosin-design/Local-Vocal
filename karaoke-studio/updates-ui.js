/* Releases are checked automatically; installation is explicitly requested. */
(() => {
  const dialog=window.studioDialogs.updates;
  dialog.querySelector('.dialog-content').innerHTML='<p>Обновления из GitHub Releases · artemfinosin-design/Local-Vocal.</p><p class="subtle">Проверка выполняется при запуске. Скачивание и перезапуск — по твоей кнопке. Песни, дубли, личный профиль и скачанные модели сохраняются. В интернет отправляется только запрос файла обновления.</p><p id="updateStatus" class="status" role="status" aria-live="polite"></p><progress id="updateProgress" max="100" value="0" hidden></progress><p id="updateAmount" class="subtle"></p><div class="voice-actions"><button id="checkUpdates">Проверить обновления</button><button id="downloadUpdate" class="primary" hidden>Скачать обновление</button><button id="installUpdate" class="primary" hidden>Установить и перезапустить</button></div><details><summary>Что нового</summary><p id="updateNotes" class="subtle"></p></details>';
  let timer,state;
  function paint(value){
    state=value;const active=['checking','downloading'].includes(value.state);
    $('checkUpdates').disabled=active;$('downloadUpdate').hidden=value.state!=='available';$('installUpdate').hidden=value.state!=='prepared';
    $('updateProgress').hidden=value.state!=='downloading';$('updateProgress').value=value.total?Math.min(100,value.done/value.total*100):0;
    const messages={idle:'Проверка ещё не выполнена.',checking:'Проверяю новые версии…',current:`Установлена актуальная версия β${value.current}.`,available:`Доступна β${value.latest}. Можно скачать обновление.`,downloading:'Скачиваю и проверяю обновление…',prepared:'Обновление готово. Сохрани запись, затем установи и перезапусти программу.',error:value.error};
    $('updateStatus').textContent=messages[value.state]||'';
    $('updateAmount').textContent=value.total?`${((value.done||0)/1048576).toFixed(1)} / ${(value.total/1048576).toFixed(1)} МБ`:'';
    $('updateNotes').textContent=value.notes||'Описание релиза появится после проверки.';
    $('openUpdates').textContent=['available','prepared'].includes(value.state)?'Обновления · есть новая версия':'Обновления';
    clearTimeout(timer);if(active)timer=setTimeout(poll,1500);
  }
  async function poll(){try{paint(await request('/api/update-status'));}catch(e){$('updateStatus').textContent=e.message;}}
  async function start(action){try{paint(await request('/api/update-'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}));}catch(e){$('updateStatus').textContent=e.message;}}
  $('openUpdates').addEventListener('click',()=>{if(busy())return;dialog.showModal();poll();});
  $('checkUpdates').addEventListener('click',()=>start('check'));
  $('downloadUpdate').addEventListener('click',()=>start('download'));
  $('installUpdate').addEventListener('click',async()=>{
    if(busy()||state?.state!=='prepared')return;
    if(!window.pywebview?.api?.apply_update){$('updateStatus').textContent='Установка доступна в настольной программе SvoyaVersiya.exe. Скачанные файлы уже подготовлены.';return;}
    pauseAll();$('installUpdate').disabled=true;$('updateStatus').textContent='Завершаю сохранение и открываю установку обновления…';
    try{const result=await window.pywebview.api.apply_update();if(result?.error)throw new Error(result.error);}
    catch(e){$('updateStatus').textContent=e.message;$('installUpdate').disabled=false;}
  });
  request('/api/update-status').then(value=>value.state==='idle'?start('check'):paint(value)).catch(()=>{});
})();
