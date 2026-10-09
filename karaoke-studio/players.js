function playbackPosition(time,duration){
  const total=Number.isFinite(duration)&&duration>0?duration:0;
  const current=Number.isFinite(time)?Math.max(0,Math.min(total,time)):0;
  return {total,current,progress:total?current/total*100:0};
}
if(typeof module!=='undefined')module.exports={playbackPosition};
if(typeof document!=='undefined')(()=>{
  const known=new WeakMap();
  const clock=value=>`${Math.floor(value/60)}:${String(Math.floor(value)%60).padStart(2,'0')}`;
  function attach(audio){
    if(audio.hidden||known.has(audio))return;
    const player=document.createElement('div');player.className='audio-player';
    const play=document.createElement('button');play.className='audio-player-play';play.type='button';
    const seek=document.createElement('input');Object.assign(seek,{type:'range',min:0,max:1,step:.01,value:0});seek.className='audio-player-seek';seek.setAttribute('aria-label','Перемотка аудиозаписи');
    const time=document.createElement('output');time.className='audio-player-time';
    const status=document.createElement('span');status.className='audio-player-status';status.setAttribute('role','status');
    player.append(play,seek,time,status);audio.after(player);audio.classList.add('studio-audio-source');known.set(audio,player);
    const refresh=()=>{
      const p=playbackPosition(audio.currentTime,audio.duration);seek.max=p.total||1;seek.value=p.current;seek.disabled=recording||!p.total;
      seek.style.setProperty('--played',p.progress+'%');time.textContent=clock(p.current)+' / '+(p.total?clock(p.total):'—:—');
      play.textContent=audio.paused?'▶':'Ⅱ';play.setAttribute('aria-label',audio.paused?'Воспроизвести аудиозапись':'Приостановить аудиозапись');play.disabled=recording;
      player.classList.toggle('is-playing',!audio.paused);
    };
    play.addEventListener('click',async()=>{
      if(recording)return;status.textContent='';
      if(audio.id==='result'){document.getElementById('listenToggle').click();return;}
      if(!audio.paused){audio.pause();return;}
      stopPreview();pauseAll();
      try{await audio.play();}catch(error){status.textContent='Не удалось включить: '+error.message;}
    });
    seek.addEventListener('input',()=>{if(!recording&&Number.isFinite(audio.duration)){audio.currentTime=Number(seek.value);refresh();}});
    for(const event of ['timeupdate','loadedmetadata','durationchange','play','pause','ended','emptied'])audio.addEventListener(event,refresh);
    audio.addEventListener('error',()=>{status.textContent='Аудиофайл недоступен. Открой проект или собери результат заново.';});
    player.refresh=refresh;audio.controls=false;refresh();
  }
  function scan(){for(const audio of document.querySelectorAll('audio')){if(audio.controls)attach(audio);if(known.has(audio)&&audio.controls)audio.controls=false;}}
  window.syncAudioPlayers=()=>{scan();document.querySelectorAll('.audio-player').forEach(player=>player.refresh());};
  new MutationObserver(scan).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['controls']});
  scan();
})();
