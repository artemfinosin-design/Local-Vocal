/* The working controls are a projected surface attached to the active 3D earcup. */
(() => {
  const workspace=document.getElementById('workspace'),object=document.querySelector('.hero-object'),shell=document.querySelector('.daw-shell');
  const panels=[...document.querySelectorAll('#studio > section')];
  const frame=document.createElement('div');frame.className='session-frame';frame.id='sessionStage';
  document.querySelectorAll('a[href="#workspace"]').forEach(link=>link.href='#sessionStage');
  frame.innerHTML='<div class="earcup-surface" id="earcupSurface"><div class="session-navigation"><button id="stageBack">← Назад</button><span id="stageName">01 / ФАЙЛ</span><button id="stageNext" class="primary" disabled>Продолжить →</button></div><details class="studio-menu"><summary>☰ Меню студии</summary><nav class="studio-tools" aria-label="Инструменты студии"><button id="newSong">Новая песня</button><button id="openHistory">Мои песни</button><button id="openLyrics">Текст караоке</button><button id="openSources">Дорожки и дубли</button><button id="openVoice">Настроить голос</button><button id="openFeedback">Поделиться примером</button><button id="openUpdates">Обновления</button></nav></details><div class="session-content"></div></div>';
  workspace.insertBefore(frame,shell);frame.insertBefore(object,frame.firstChild);object.classList.add('session-scene');
  const actions=document.createElement('nav');actions.className='stage-actions';actions.setAttribute('aria-label','Основные действия');
  for(const id of ['newSong','openHistory','openLyrics','openVoice'])actions.append(document.getElementById(id));
  frame.querySelector('.earcup-surface').insertBefore(actions,frame.querySelector('.session-content'));
  const version=document.createElement('p');version.id='engineStatus';version.className='engine-status';version.setAttribute('role','status');version.textContent='Проверяю версию обработки…';workspace.insertBefore(version,frame);
  object.querySelector('.object-controls')?.remove();
  const viewport=document.getElementById('headphoneViewport');viewport.removeAttribute('tabindex');viewport.setAttribute('aria-label','Наушники с рабочим экраном на амбушюре');
  const content=frame.querySelector('.session-content'),upload=document.getElementById('uploadCard'),record=panels[1],mix=panels[2];
  const listen=document.createElement('section');listen.className='listening-panel';
  listen.innerHTML='<span class="eyebrow">ТВОЯ ВЕРСИЯ ГОТОВА</span><h2>Теперь слушай.</h2><canvas id="waveCanvas" aria-hidden="true"></canvas><button id="listenToggle" class="listen-toggle" aria-label="Воспроизвести готовую песню">▶</button><div id="listenLyrics" class="karaoke-display" aria-live="off"></div>';
  listen.append(document.getElementById('resultBox'));frame.append(listen);const review=document.getElementById('renderRating');workspace.insertBefore(review,frame.nextSibling);content.append(upload,record,mix);frame.querySelector('.studio-tools').addEventListener('click',event=>{if(event.target.closest('button'))frame.querySelector('.studio-menu').open=false;});
  const dialog=(id,title)=>{const node=document.createElement('dialog');node.id=id;node.className='studio-dialog';node.setAttribute('aria-labelledby',id+'-title');node.innerHTML=`<header><div><span class="eyebrow">ИНСТРУМЕНТЫ СТУДИИ</span><h2 id="${id}-title">${title}</h2></div><button class="dialog-close" aria-label="Закрыть окно">✕</button></header><div class="dialog-content"></div>`;node.querySelector('button').addEventListener('click',()=>node.close());node.addEventListener('click',event=>{if(event.target===node){const box=node.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)node.close();}});document.body.append(node);return node;};
  const sourcesDialog=dialog('sourcesDialog','Дорожки и мои дубли');
  const lyricsPanel=document.createElement('section');lyricsPanel.id='lyricsPanel';lyricsPanel.className='inline-lyrics';lyricsPanel.hidden=true;
  lyricsPanel.append(document.querySelector('.lyrics-editor'));workspace.insertBefore(lyricsPanel,frame.nextSibling);
  sourcesDialog.querySelector('.dialog-content').append(panels[0]);
  window.studioDialogs={updates:dialog('updatesDialog','Обновления Local Vocal'),history:dialog('historyDialog','Мои песни'),voice:dialog('voiceDialog','Настрой свой голос'),feedback:dialog('feedbackDialog','Пример для улучшения студии')};
  const library=document.createElement('div');library.id='takeLibrary';sourcesDialog.querySelector('.dialog-content').append(library);
  shell.remove();document.querySelector('.hero').classList.add('intro-only');
  let roleIds=[],roleNames=[],index=0,ready=false,resultReady=false,lastStage='';
  const back=document.getElementById('stageBack'),next=document.getElementById('stageNext');
  document.getElementById('openLyrics').setAttribute('aria-controls','lyricsPanel');
  document.getElementById('openLyrics').addEventListener('click',()=>{if(document.body.classList.contains('busy'))return;lyricsPanel.hidden=!lyricsPanel.hidden;document.getElementById('openLyrics').setAttribute('aria-expanded',String(!lyricsPanel.hidden));if(!lyricsPanel.hidden)lyricsPanel.scrollIntoView({block:'start',behavior:'smooth'});});
  document.getElementById('openSources').addEventListener('click',()=>{if(document.body.classList.contains('busy'))return;sourcesDialog.showModal();});
  function show() {
    const isRole=index>0&&index<=roleIds.length,isMix=index===roleIds.length+1&&index>0,isListen=index===roleIds.length+2&&index>0;
    upload.hidden=index!==0;record.hidden=!isRole;mix.hidden=!isMix;listen.hidden=!isListen;review.hidden=!isListen||!review.dataset.available;
    document.getElementById('openLyrics').disabled=document.getElementById('openSources').disabled=!ready;document.getElementById('openFeedback').disabled=!ready;
    document.querySelectorAll('.track').forEach(track=>track.hidden=!isRole||track.dataset.role!==roleIds[index-1]);
    document.getElementById('stageName').textContent=index===0?'1 / ЗАГРУЗИ ПЕСНЮ':isRole?`${index+1} / ЗАПИСЬ`:isMix?'СОБЕРИ ПЕСНЮ':'СЛУШАЙ';
    back.hidden=index===0;next.hidden=isListen;next.disabled=!ready||(isMix&&!resultReady);
    next.textContent=isMix?'Слушать →':'Дальше →';
    if(!ready)lyricsPanel.hidden=true;
    frame.classList.toggle('listening',isListen);document.getElementById('earcupSurface').classList.toggle('final-navigation',isListen);
    const detail={stage:index===0?'upload':isRole?'record':isMix?'mix':'listen',side:index%2,title:document.getElementById('stageName').textContent};
    window.studioStage=detail;
    const key=detail.stage+detail.side;if(key!==lastStage){lastStage=key;dispatchEvent(new CustomEvent('studio-stage',{detail}));}
    if(isRole)requestAnimationFrame(()=>document.querySelector('.track:not([hidden])')?.querySelector('canvas')&&window.refreshVocalEditors?.());
  }
  const move=amount=>{if(document.body.classList.contains('busy'))return;index=Math.max(0,index+amount);show();content.scrollTop=0;frame.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});};
  back.addEventListener('click',()=>move(-1));next.addEventListener('click',()=>move(1));
  window.studioFlow={
    ready(roles,hasResult){const currentRole=roleIds[index-1];roleIds=roles.map(role=>role.id);roleNames=roles.map(role=>role.name);ready=true;resultReady=hasResult;if(currentRole&&roleIds.includes(currentRole))index=roleIds.indexOf(currentRole)+1;else index=Math.min(index,roleIds.length+2);show();},
    uploading(){index=0;ready=resultReady=false;show();},
    result(){resultReady=true;show();},dirty(){resultReady=false;show();},show,
  };
  show();
  const audio = document.getElementById('result');
  const play = document.getElementById('listenToggle');
  let context, analysers, drawId;
  const canvas = document.getElementById('waveCanvas');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  function draw() {
    const ratio = Math.min(devicePixelRatio, 2);
    canvas.width = canvas.clientWidth * ratio; canvas.height = canvas.clientHeight * ratio;
    const ctx = canvas.getContext('2d'); ctx.scale(ratio, ratio);
    const w = canvas.clientWidth, h = canvas.clientHeight;
    for (let side = 0; side < 2; side++) {
      const values = new Uint8Array(analysers[side].frequencyBinCount);
      analysers[side].getByteTimeDomainData(values);
      ctx.strokeStyle = side ? '#d3ef85' : '#ff985a'; ctx.lineWidth = 1.5;
      ctx.beginPath();
      for (let i = 0; i < values.length; i++) {
        const x = side ? w - i / values.length * w / 2 : i / values.length * w / 2;
        const y = h / 2 + (values[i] - 128) / 128 * h * 0.42;
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      }
      ctx.stroke();
    }
    if (!audio.paused && !reduced) drawId = requestAnimationFrame(draw);
  }
  play.addEventListener('click', async () => {
    try {
      if (!audio.paused) { audio.pause(); return; }
      if (!context) {
        context = new AudioContext();
        const source = context.createMediaElementSource(audio), splitter = context.createChannelSplitter(2);
        source.connect(context.destination); source.connect(splitter);
        analysers = [context.createAnalyser(), context.createAnalyser()];
        analysers.forEach((node, i) => { node.fftSize = 512; splitter.connect(node, i); });
      }
      await context.resume(); await audio.play();
    } catch (error) { document.getElementById('renderStatus').textContent = 'Не удалось включить звук: ' + error.message; }
  });
  audio.addEventListener('play', () => { play.textContent = 'Ⅱ'; play.setAttribute('aria-label', 'Приостановить песню'); if (analysers) { cancelAnimationFrame(drawId); draw(); } });
  const pause = () => { play.textContent = '▶'; play.setAttribute('aria-label', 'Воспроизвести готовую песню'); cancelAnimationFrame(drawId); };
  audio.addEventListener('pause', pause); audio.addEventListener('ended', pause);
})();
