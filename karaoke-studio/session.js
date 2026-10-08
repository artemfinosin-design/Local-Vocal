/* The working controls are a projected surface attached to the active 3D earcup. */
(() => {
  const workspace=document.getElementById('workspace'),object=document.querySelector('.hero-object'),shell=document.querySelector('.daw-shell');
  const panels=[...document.querySelectorAll('#studio > section')];
  const frame=document.createElement('div');frame.className='session-frame';frame.id='sessionStage';
  document.querySelectorAll('a[href="#workspace"]').forEach(link=>link.href='#sessionStage');
  frame.innerHTML='<div class="earcup-surface" id="earcupSurface"><div class="session-navigation"><button id="stageBack">← Назад</button><span id="stageName">01 / ФАЙЛ</span><button id="stageNext" class="primary" disabled>Продолжить →</button></div><button id="openStudioMenu" class="studio-menu-button" aria-haspopup="dialog">☰ Меню студии</button><div class="studio-menu"><nav class="studio-tools" aria-label="Инструменты студии"><button id="newSong">Новая песня</button><button id="openHistory">Мои песни</button><button id="openLyrics">Текст караоке</button><button id="openSources">Дорожки и дубли</button><button id="openVoice">Настроить голос</button><button id="openFeedback">Поделиться примером</button><button id="openUpdates">Обновления</button></nav></div><div class="session-content" tabindex="0" aria-label="Рабочая панель наушников"></div></div>';
  workspace.insertBefore(frame,shell);frame.insertBefore(object,frame.firstChild);object.classList.add('session-scene');
  frame.querySelector('.session-navigation').append(document.getElementById('openStudioMenu'));
  const actions=document.createElement('nav');actions.className='stage-actions';actions.setAttribute('aria-label','Основные действия');
  for(const id of ['newSong','openHistory','openLyrics','openVoice'])actions.append(document.getElementById(id));
  frame.querySelector('.earcup-surface').insertBefore(actions,frame.querySelector('.session-content'));
  const version=document.createElement('p');version.id='engineStatus';version.className='engine-status';version.setAttribute('role','status');version.textContent='Проверяю версию обработки…';workspace.insertBefore(version,frame);
  object.querySelector('.object-controls')?.remove();
  const viewport=document.getElementById('headphoneViewport');viewport.removeAttribute('tabindex');viewport.setAttribute('aria-label','Наушники с рабочим экраном на амбушюре');
  const content=frame.querySelector('.session-content'),upload=document.getElementById('uploadCard'),record=panels[1],mix=panels[2];
  const listen=document.createElement('section');listen.className='listening-panel';
  listen.innerHTML='<span class="eyebrow">ТВОЯ ВЕРСИЯ ГОТОВА</span><h2>Теперь слушай.</h2><canvas id="waveCanvas" aria-hidden="true"></canvas><button id="listenToggle" class="listen-toggle" aria-label="Воспроизвести готовую песню">▶</button><div id="listenLyrics" class="karaoke-display" aria-live="off"></div>';
  listen.append(document.getElementById('resultBox'));frame.append(listen);const review=document.getElementById('renderRating');workspace.insertBefore(review,frame.nextSibling);const fitted=document.createElement('div');fitted.className='stage-fit';fitted.append(upload,record);content.append(fitted,mix);
  const dialog=(id,title)=>{const node=document.createElement('dialog');node.id=id;node.className='studio-dialog';node.setAttribute('aria-labelledby',id+'-title');node.innerHTML=`<header><div><span class="eyebrow">ИНСТРУМЕНТЫ СТУДИИ</span><h2 id="${id}-title">${title}</h2></div><button class="dialog-close" aria-label="Закрыть окно">✕</button></header><div class="dialog-content"></div>`;node.querySelector('button').addEventListener('click',()=>node.close());node.addEventListener('click',event=>{if(event.target===node){const box=node.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)node.close();}});document.body.append(node);return node;};
  const youtubeDialog=dialog('youtubeDialog','Вход YouTube для загрузки');
  const youtubeOptions=document.getElementById('youtubeLoginOptions');youtubeOptions.hidden=false;youtubeDialog.querySelector('.dialog-content').append(youtubeOptions);
  document.getElementById('openYoutubeLogin').addEventListener('click',()=>youtubeDialog.showModal());
  document.getElementById('youtubeLogin').addEventListener('change',()=>{document.getElementById('openYoutubeLogin').textContent=document.getElementById('youtubeLogin').checked?'Вход YouTube разрешён · настройки ↗':'YouTube требует вход? Настроить ↗';});
  const reviewDialog=dialog('reviewDialog','Твой результат и советы');window.reviewDialog=reviewDialog;reviewDialog.querySelector('.dialog-content').append(review);
  const openReview=document.createElement('button');openReview.id='openReview';openReview.className='review-launch';openReview.textContent='✦ Разбор пения и оценка';actions.append(openReview);openReview.addEventListener('click',()=>reviewDialog.showModal());
  const menuDialog=dialog('menuDialog','Твоя студия');
  menuDialog.classList.add('studio-menu-dialog');
  const tools=frame.querySelector('.studio-tools');
  menuDialog.querySelector('.dialog-content').append(tools);
  frame.querySelector('.studio-menu').remove();
  document.getElementById('openStudioMenu').addEventListener('click',()=>menuDialog.showModal());
  // Close the top-layer menu before an existing tool opens its own dialog.
  tools.addEventListener('click',event=>{if(event.target.closest('button'))menuDialog.close();},true);
  const toolButton=(id,text,handler)=>{const button=document.createElement('button');button.id=id;button.type='button';button.textContent=text;button.addEventListener('click',handler);tools.append(button);return button;};
  const helpDialog=dialog('helpDialog','Как спеть свою версию');
  helpDialog.querySelector('.dialog-content').innerHTML='<div class="guide-cards"><article><b>01 · Добавь песню</b><p>Выбери файл или вставь ссылку YouTube. Разделение, поиск текста и разметка партий запускаются автоматически.</p></article><article><b>02 · Запиши голос</b><p>Выбери всю партию или короткий фрагмент. Перед записью звучат отсчёт и три секунды музыки. Перетащи ползунок на ошибку и начни запись: новый дубль заменит только свой участок. Для удаления включи «Убрать лишний вокал».</p></article><article><b>03 · Проверь задержку</b><p>На экране сборки послушай голос с музыкой: минус сдвигает его раньше, плюс — позже. «Студийный» — плавная коррекция; галочка отключает её.</p></article><article><b>04 · Слушай и оцени</b><p>После сборки студия сама откроет прослушивание. Скачай WAV и оцени обработку через кнопку разбора. Песни сохраняются в «Мои песни».</p></article></div><details class="info-note"><summary>Что происходит с моими файлами?</summary><p>Обработка и личный профиль остаются на компьютере. Интернет нужен для установки, обновлений, YouTube и поиска текста. ZIP с голосом создаётся только по твоему выбору; отправки на сервер нет.</p></details><details class="info-note"><summary>Почему результат иногда отличается?</summary><p>Разделение и распознавание партий могут ошибаться. Эффекты оцениваются по готовому вокалу; точные настройки оригинальных плагинов неизвестны. Если нота не распознана уверенно, коррекция пропускает её.</p></details><p class="subtle">Загрузка и запись помещаются на наушнике без прокрутки. На финальной настройке можно прокручивать задержку и обработку. Небольшая подсказка: логотип любит двойной клик.</p>';
  const helpButton=toolButton('openHelp','? Помощь',()=>helpDialog.showModal());document.querySelector('.topbar').append(helpButton);
  addEventListener('keydown',event=>{if(event.key==='?'&&!event.ctrlKey&&!event.altKey&&!event.metaKey&&!event.target.closest('input,textarea,select,[contenteditable]')&&!document.querySelector('dialog[open]'))helpDialog.showModal();});
  const secretDialog=dialog('secretDialog','Комната звукорежиссёра');
  secretDialog.querySelector('.dialog-content').innerHTML='<div class="guide-cards"><article><b>Секретный дубль № 303</b><p>Звукорежиссёр вышел за чаем. На пульте оставил записку: «Пой ближе к микрофону, дальше от холодильника».</p></article><article><b>Режим суперзвезды</b><p>Уже включён. Для активации нужен только хороший дубль. Блёстки в WAV не экспортируются.</p></article></div><p class="subtle">Ещё один секрет прячется в слове groove. Звук песни эти секреты не меняют.</p>';
  document.getElementById('stageName').addEventListener('dblclick',()=>secretDialog.showModal());
  const appearanceDialog=dialog('appearanceDialog','Сделай студию своей');
  appearanceDialog.querySelector('.dialog-content').innerHTML='<fieldset class="appearance-colors"><legend>Свет студии и отделка наушников</legend><label><input type="radio" name="studioColor" value="amber"><span class="color-swatch" style="--swatch:#ff985a"></span>Тёплый янтарь</label><label><input type="radio" name="studioColor" value="ice"><span class="color-swatch" style="--swatch:#81d7ef"></span>Ледяной голубой</label><label><input type="radio" name="studioColor" value="violet"><span class="color-swatch" style="--swatch:#c0a4ff"></span>Ночной фиолетовый</label><label><input type="radio" name="studioColor" value="mint"><span class="color-swatch" style="--swatch:#a6e3b8"></span>Мятный свет</label></fieldset><label class="check-option"><input id="largeStudioText" type="checkbox"> Крупнее текст и кнопки</label><label class="check-option"><input id="calmStudio" type="checkbox"> Спокойный режим — без вращения и анимаций</label><p class="subtle">Оформление сохраняется на этом устройстве и не меняет звук.</p><button id="resetAppearance" class="editor-button">Вернуть стандартное оформление</button>';
  const colors={amber:'#ff985a',ice:'#81d7ef',violet:'#c0a4ff',mint:'#a6e3b8'};
  let appearance={color:'amber',large:false,calm:false};
  try{const saved=JSON.parse(localStorage.getItem('studioAppearance'));if(saved&&colors[saved.color])appearance={color:saved.color,large:saved.large===true,calm:saved.calm===true};}catch{}
  function applyAppearance(save=false){
    document.body.classList.remove('acid-mode');document.documentElement.style.setProperty('--accent',colors[appearance.color]);
    document.body.classList.toggle('large-studio',appearance.large);document.body.classList.toggle('calm-studio',appearance.calm);
    document.querySelector(`[name="studioColor"][value="${appearance.color}"]`).checked=true;
    document.getElementById('largeStudioText').checked=appearance.large;document.getElementById('calmStudio').checked=appearance.calm;
    window.studioAppearance=appearance;
    dispatchEvent(new CustomEvent('studio-accent',{detail:colors[appearance.color]}));dispatchEvent(new Event('studio-appearance'));
    if(save)try{localStorage.setItem('studioAppearance',JSON.stringify(appearance));}catch{}
  }
  appearanceDialog.addEventListener('change',()=>{appearance={color:appearanceDialog.querySelector('[name="studioColor"]:checked').value,large:document.getElementById('largeStudioText').checked,calm:document.getElementById('calmStudio').checked};applyAppearance(true);});
  document.getElementById('resetAppearance').addEventListener('click',()=>{appearance={color:'amber',large:false,calm:false};applyAppearance(true);});
  toolButton('openAppearance','Оформление студии',()=>appearanceDialog.showModal());applyAppearance();
  const advancedDialog=dialog('advancedDialog','Обработка: подробные настройки');
  const options=mix.querySelector('.mix-options'),advanced=document.createElement('div');advanced.className='mix-options';
  const basic=[options.querySelector('#autotune').closest('label'),options.querySelector('#tuneMode').closest('label'),options.querySelector('#tuneDescription'),options.querySelector('#pitchFalls').closest('label')];
  for(const node of [...options.children])if(!basic.includes(node))advanced.append(node);
  advancedDialog.querySelector('.dialog-content').append(advanced);
  const advancedButton=document.createElement('button');advancedButton.id='openAdvanced';advancedButton.className='editor-button';advancedButton.textContent='Эффекты, баланс и подробные настройки ↗';advancedButton.addEventListener('click',()=>advancedDialog.showModal());options.append(advancedButton);
  const hint=document.createElement('p');hint.id='stageHint';hint.className='stage-hint';frame.querySelector('.session-navigation').after(hint);
  const scrollCue=document.createElement('button');scrollCue.type='button';scrollCue.className='scroll-cue';scrollCue.textContent='Ещё ниже ↓';scrollCue.setAttribute('aria-label','Показать следующие элементы рабочей панели');content.after(scrollCue);
  const updateScrollCue=()=>{scrollCue.hidden=frame.dataset.stage!=='mix'||content.scrollHeight-content.clientHeight-content.scrollTop<12;};
  let fitFrame;
  function fitStage(){
    cancelAnimationFrame(fitFrame);fitFrame=requestAnimationFrame(()=>{
      if(!['upload','record'].includes(frame.dataset.stage))return;
      fitted.style.zoom='1';
      const available=content.clientHeight-parseFloat(getComputedStyle(content).paddingTop)-parseFloat(getComputedStyle(content).paddingBottom);
      if(available>0&&fitted.scrollHeight>0)fitted.style.zoom=String(Math.min(1,available/fitted.scrollHeight));
    });
  }
  new ResizeObserver(fitStage).observe(content);
  new MutationObserver(fitStage).observe(fitted,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['hidden','open']});
  addEventListener('studio-appearance',fitStage);
  scrollCue.addEventListener('click',()=>content.scrollBy({top:content.clientHeight*.7,behavior:window.studioAppearance.calm?'auto':'smooth'}));
  content.addEventListener('scroll',updateScrollCue,{passive:true});new ResizeObserver(updateScrollCue).observe(content);new MutationObserver(updateScrollCue).observe(content,{childList:true,subtree:true,attributes:true,attributeFilter:['hidden','open']});
  const sourcesDialog=dialog('sourcesDialog','Дорожки и мои дубли');
  const lyricsDialog=dialog('lyricsDialog','Текст караоке');lyricsDialog.querySelector('.dialog-content').append(document.querySelector('.lyrics-editor'));
  sourcesDialog.querySelector('.dialog-content').append(panels[0]);
  window.studioDialogs={updates:dialog('updatesDialog','Обновления Local Vocal'),history:dialog('historyDialog','Мои песни'),voice:dialog('voiceDialog','Настрой свой голос'),feedback:dialog('feedbackDialog','Пример для улучшения студии')};
  const library=document.createElement('div');library.id='takeLibrary';sourcesDialog.querySelector('.dialog-content').append(library);
  shell.remove();document.querySelector('.hero').classList.add('intro-only');
  let roleIds=[],roleNames=[],index=0,ready=false,resultReady=false,lastStage='';
  const back=document.getElementById('stageBack'),next=document.getElementById('stageNext');
  document.getElementById('openLyrics').setAttribute('aria-controls','lyricsDialog');
  document.getElementById('openLyrics').addEventListener('click',()=>{if(!document.body.classList.contains('busy'))lyricsDialog.showModal();});
  document.getElementById('openSources').addEventListener('click',()=>{if(document.body.classList.contains('busy'))return;sourcesDialog.showModal();});
  function show() {
    const isRole=index>0&&index<=roleIds.length,isMix=index===roleIds.length+1&&index>0,isListen=index===roleIds.length+2&&index>0;
    upload.hidden=index!==0;record.hidden=!isRole;mix.hidden=!isMix;listen.hidden=!isListen;review.hidden=!review.dataset.available;openReview.hidden=!isListen;openReview.disabled=!review.dataset.available;
    document.getElementById('openLyrics').disabled=document.getElementById('openSources').disabled=!ready;document.getElementById('openFeedback').disabled=!ready;
    document.querySelectorAll('.track').forEach(track=>track.hidden=!isRole||track.dataset.role!==roleIds[index-1]);
    document.getElementById('stageName').textContent=index===0?'1 / ЗАГРУЗИ ПЕСНЮ':isRole?`${index+1} / ЗАПИСЬ`:isMix?'СОБЕРИ ПЕСНЮ':'СЛУШАЙ';
    back.hidden=index===0;next.hidden=isListen;next.disabled=!ready||(isMix&&!resultReady);
    next.textContent=isMix?'Слушать →':index===0?'К записи →':index===roleIds.length?'Проверить и собрать →':'Следующая партия →';
    hint.textContent=index===0?'01 · Добавь песню — студия разберёт звук и найдёт текст.':isRole?`${roleNames[index-1]} · Выбери фрагмент и запиши. Остальные партии доступны дальше.`:isMix?'03 · Сначала задержка, затем сборка. Громкость и пространство подбираются автоматически.':'04 · Слушай свою версию. Оценка и разбор пения — кнопка сверху.';
    hint.hidden=!isMix;updateScrollCue();
    if(!ready)lyricsDialog.close();
    const stage=index===0?'upload':isRole?'record':isMix?'mix':'listen';if(frame.dataset.stage!==stage)content.scrollTop=0;frame.dataset.stage=stage;fitted.hidden=isMix||isListen;fitStage();
    frame.classList.toggle('listening',isListen);document.getElementById('earcupSurface').classList.toggle('final-navigation',isListen);
    const detail={stage:index===0?'upload':isRole?'record':isMix?'mix':'listen',side:index%2,title:document.getElementById('stageName').textContent};
    window.studioStage=detail;
    const key=detail.stage+detail.side;if(key!==lastStage){lastStage=key;dispatchEvent(new CustomEvent('studio-stage',{detail}));}
    if(isRole)window.noteGuide?.select(projectId,roleIds[index-1]);
    if(isRole)requestAnimationFrame(()=>document.querySelector('.track:not([hidden])')?.querySelector('canvas')&&window.refreshVocalEditors?.());
  }
  const move=amount=>{if(document.body.classList.contains('busy'))return;index=Math.max(0,index+amount);show();content.scrollTop=0;frame.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});};
  back.addEventListener('click',()=>move(-1));next.addEventListener('click',()=>move(1));
  window.studioFlow={
    ready(roles,hasResult){const currentRole=roleIds[index-1];roleIds=roles.map(role=>role.id);roleNames=roles.map(role=>role.name);ready=true;resultReady=hasResult;if(currentRole&&roleIds.includes(currentRole))index=roleIds.indexOf(currentRole)+1;else index=Math.min(index,roleIds.length+2);show();},
    uploading(){index=0;ready=resultReady=false;show();},
    result(){resultReady=true;index=roleIds.length+2;show();frame.scrollIntoView({block:'start',behavior:window.studioAppearance.calm?'auto':'smooth'});},dirty(){resultReady=false;show();},show,
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
    if (!audio.paused && !reduced && !window.studioAppearance.calm) drawId = requestAnimationFrame(draw);
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
