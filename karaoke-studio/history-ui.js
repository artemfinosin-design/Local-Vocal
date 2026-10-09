/* Projects and their dry takes stay local; deletion is recoverable. */
(() => {
  const dialog=window.studioDialogs.history,content=dialog.querySelector('.dialog-content');
  let changing=false;
  async function refresh(){
    content.replaceChildren(element('p','subtle','Песни и дубли сохраняются автоматически на этом устройстве. Удалённые песни можно вернуть из локальной корзины.'));
    try {
      const history=await request('/api/history');
      if(!history.songs.length)content.append(element('p','','Пока нет записанных песен.'));
      for(const song of history.songs){
        const card=element('article','history-card');card.append(element('h3','',song.filename));
        const date=song.updated_at?new Date(song.updated_at*1000).toLocaleString('ru-RU'):'';
        card.append(element('p','subtle',`${seconds(song.duration)} · Дублей: ${song.takes}${date?' · '+date:''}`));
        if(song.render){const audio=element('audio');audio.controls=true;audio.preload='none';audio.src=`/api/audio?id=${song.id}&name=${song.render}`;card.append(audio);}
        const actions=element('div','voice-actions');
        actions.append(button('Редактировать песню',async event=>{if(changing)return;changing=true;const node=event.currentTarget;node.disabled=true;node.textContent='Открываю проект…';try{await openSavedProject(song.id);}catch(error){if(!dialog.open)dialog.showModal();let status=card.querySelector('.history-error');if(!status){status=element('p','status history-error');status.setAttribute('role','alert');card.append(status);}status.textContent='Не удалось открыть проект: '+error.message;}finally{changing=false;node.disabled=false;node.textContent='Редактировать песню';}}));
        if(song.render){const download=element('a','preview-button','Скачать WAV');download.href=`/api/audio?id=${song.id}&name=${song.render}`;download.download=song.filename.replace(/\.[^.]+$/,'')+' — моя версия.wav';actions.append(download);}
        actions.append(button('Удалить',()=>{if(changing)return;actions.replaceChildren(element('span','subtle','Переместить песню и все её дубли в корзину?'),button('Да, удалить',()=>change('delete',song.id)),button('Отмена',refresh));}));
        card.append(actions);content.append(card);
      }
      if(history.trash.length){
        const details=element('details');details.append(element('summary','','Корзина · '+history.trash.length));
        for(const song of history.trash){const row=element('article','history-card');row.append(element('strong','',song.filename),button('Восстановить',()=>change('restore',song.id)));details.append(row);}
        content.append(details);
      }
    }catch(error){content.append(element('p','status',error.message));}
  }
  async function change(action,id){
    if(changing)return;changing=true;content.querySelectorAll('button').forEach(node=>node.disabled=true);pauseAll();
    let failure;
    try {
      await request(`/api/history-${action}?id=${id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
      if(action==='delete'){
        if(localStorage.getItem('karaokeProject')===id)localStorage.removeItem('karaokeProject');
        if(projectId===id){resetProject();dialog.showModal();}
      }
    }catch(error){failure=error.message;}
    finally{changing=false;await refresh();if(failure)content.append(element('p','status',failure));}
  }
  dialog.addEventListener('close',()=>content.querySelectorAll('audio').forEach(audio=>audio.pause()));
  $('openHistory').addEventListener('click',()=>{if($('openHistory').disabled)return;dialog.showModal();refresh();});
})();
