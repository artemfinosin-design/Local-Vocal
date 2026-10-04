/* Estimated unusual effects wait for the singer's explicit approval. */
(() => {
  let audios=[],generation=0;
  window.loadEffectProposals=async()=>{
    const current=projectId,token=++generation;
    audios.forEach(audio=>audio.pause());audios=[];$('effectProposalList').replaceChildren();
    try {
      const result=await request('/api/effect-proposals?id='+current);
      if(current!==projectId||token!==generation)return;
      $('effectProposalStatus').textContent=result.proposals.length?'Предложения не применяются, пока ты их не одобришь. После одобрения собери песню снова.':'Необычные эффекты не найдены уверенно. Другие эффекты доступны в списке «Пространство и характер».';
      for(const event of result.proposals){
        const card=element('article','effect-card'),title=event.type==='estimated_pitch_fall'?'Спад высоты и тембра':event.type==='estimated_colour'?'Узкий, телефонный тембр':'Повторы слова с учащением';
        const status=element('span','chip'),description=element('p','subtle',event.type==='estimated_colour'?'В исходнике обнаружена узкая полоса частот. Предлагается приблизительная телефонная окраска; насыщение и точный плагин не восстановлены.':event.uncertain_middle?'Часть высоты не распознана: предложенная траектория приблизительная. Проверь исходник.':'Предполагаемый эффект. Прослушай участок, чтобы проверить.');
        card.append(element('strong','',`${seconds(event.start,true)} — ${seconds(event.end,true)} · ${title}`),description,status);
        const audio=element('audio');audio.hidden=true;audio.preload='metadata';audio.src=audioUrl(event.reference);audios.push(audio);card.append(audio);
        audio.addEventListener('timeupdate',()=>{if(audio.currentTime>=event.end+.15)audio.pause();});
        const controls=element('div','voice-actions');
        controls.append(button('▶ Исходник',async()=>{if(busy())return;pauseAll();audio.currentTime=Math.max(0,event.start-.4);try{await audio.play();}catch(error){$('effectProposalStatus').textContent=error.message;}}));
        function paint(){status.textContent={pending:'Ждёт решения',approved:'Одобрено',rejected:'Отклонено'}[event.status]||'Ждёт решения';}
        async function decide(value){
          if(busy())return;mutating=true;pauseAll();syncControls();controls.querySelectorAll('button').forEach(node=>node.disabled=true);
          try{await post('effect-decision',{id:event.id,status:value});event.status=value;paint();window.studioFlow.dirty();}
          catch(error){$('effectProposalStatus').textContent=error.message;}
          finally{mutating=false;syncControls();controls.querySelectorAll('button').forEach(node=>node.disabled=false);}
        }
        controls.append(button('Применить',()=>decide('approved'),'primary'),button('Отклонить',()=>decide('rejected')),button('Сбросить решение',()=>decide('pending')));paint();card.append(controls);$('effectProposalList').append(card);
      }
    }catch(error){if(current===projectId)$('effectProposalStatus').textContent=error.message;}
  };
  if(projectId)window.loadEffectProposals();
})();
