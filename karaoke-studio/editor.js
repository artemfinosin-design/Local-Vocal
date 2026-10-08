/* One selection, one transport and one record action for each vocal part. */
class VocalEditor {
  constructor(role) {
    this.role=role; this.duration=project.duration; this.range=[0,this.duration]; this.view=[0,this.duration]; this.peaks=[]; this.selecting=false;
    const root=this.node=element('div','vocal-editor');
    const selection=element('div','selection-picker');
    this.parts=element('select'); this.parts.setAttribute('aria-label','Выбрать участок для записи');
    const whole=element('option','','Вся партия'); whole.value='all'; this.parts.append(whole);
    role.segments.forEach((range,index)=>{ const option=element('option','',`Фрагмент ${index+1} · ${seconds(range[0],true)} — ${seconds(range[1],true)}`); option.value=index; this.parts.append(option); });
    for(const [index,range] of (role.excluded||[]).entries()) { const option=element('option','',`Исключён · ${seconds(range[0],true)} — ${seconds(range[1],true)}`);option.value='excluded-'+index;this.parts.append(option); }
    const custom=element('option','','Выделенная область');custom.value='custom';this.parts.append(custom);this.parts.className='region-picker';
    this.parts.addEventListener('change',()=>{ const key=this.parts.value; if(key==='custom') return; const range=key==='all'?[0,this.duration]:key.startsWith('excluded-')?role.excluded[Number(key.slice(9))]:role.segments[Number(key)]; this.setRange(range);role.guide.currentTime=range[0];this.cursor.value=range[0];this.refresh(); });
    this.selectionToggle=button('Убрать лишний вокал',()=>{this.selecting=!this.selecting;if(this.selecting){const at=Math.min(Number(this.cursor.value),Math.max(0,this.duration-.1));this.setRange([at,Math.min(this.duration,at+2)]);}this.refresh();},'editor-button');this.selectionToggle.setAttribute('aria-pressed','false');selection.append(this.selectionToggle,this.parts,button('Показать всю песню',()=>{this.view=[0,this.duration];this.draw();},'editor-button view-control'),button('Увеличить выделение',()=>{this.view=[Math.max(0,this.range[0]-2),Math.min(this.duration,this.range[1]+2)];this.draw();},'editor-button view-control'));
    this.wave=element('div','wave-editor');
    this.canvas=element('canvas'); this.canvas.setAttribute('aria-label','Волна вокала. Нажми для перемотки.');
    this.wave.append(this.canvas);
    for(const [key,label] of [['start','Начало выделения'],['end','Конец выделения']]) {
      const input=element('input','trim-handle trim-'+key);Object.assign(input,{type:'range',min:0,max:this.duration,step:.01,value:key==='start'?0:this.duration,id:`range-${role.id}-${key}`}); input.setAttribute('aria-label',label);
      input.addEventListener('input',()=>{ if(busy()) return; const index=key==='start'?0:1, value=Number(input.value);this.range[index]=index===0?Math.min(value,this.range[1]-.1):Math.max(value,this.range[0]+.1);this.parts.value='custom';this.refresh(); });
      this.wave.append(input);this[key]=input;
    }
    const timeAt=event=>{const rect=this.canvas.getBoundingClientRect();return this.view[0]+Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width))*(this.view[1]-this.view[0]);};
    const seek=event=>{if(busy())return;const at=timeAt(event);role.guide.currentTime=at;this.cursor.value=at;this.refresh();};
    this.canvas.addEventListener('pointerdown',event=>{if(busy())return;this.canvas.setPointerCapture?.(event.pointerId);if(this.selecting){role.guide.pause();this.anchor=Math.min(timeAt(event),this.duration-.1);this.setRange([this.anchor,Math.min(this.duration,this.anchor+.1)]);}else seek(event);});
    this.canvas.addEventListener('pointermove',event=>{if(event.buttons!==1||busy())return;if(this.selecting){const at=timeAt(event);this.setRange([Math.min(this.anchor,at),Math.max(this.anchor+.1,at)]);}else seek(event);});
    const transport=element('div','editor-transport');
    this.play=button('▶ Слушать партию',async()=>{ if(busy()) return; if(!role.guide.paused){role.guide.pause();return;}stopPreview();pauseAll();if(this.selecting&&(role.guide.currentTime<this.range[0]||role.guide.currentTime>=this.range[1])) role.guide.currentTime=Math.max(0,this.range[0]-1);role.guide.dataset.stop=this.selecting?this.range[1]+.2:this.duration;try{await role.guide.play();}catch(error){$('recordStatus').textContent=error.message;} },'editor-button');
    const cursorLabel=element('label','seek-control','Позиция');this.cursor=element('input');Object.assign(this.cursor,{type:'range',min:0,max:this.duration,step:.01,value:0});this.cursor.setAttribute('aria-label','Перемотка песни');this.cursor.addEventListener('input',()=>{if(!busy())role.guide.currentTime=Number(this.cursor.value);this.refresh();});cursorLabel.append(this.cursor);
    this.time=element('output','editor-clock',`0:00 / ${seconds(this.duration)}`);transport.append(this.play,cursorLabel,this.time);
    this.caption=element('div','selection-caption');
    this.record=button('● Записать',()=>startRecording(role,[Number(this.cursor.value),this.duration]),'primary record-selection');
    this.exclude=button('Убрать вокал на участке',()=>{const excluded=this.excluded();editSegment(role,null,excluded?'restore':'exclude',excluded||this.range.slice());},'editor-button');
    this.artist=button(role.id==='artist2'?'Вернуть основному исполнителю':'Отнести другому исполнителю',()=>{const index=role.segments.findIndex(item=>item[0]===this.range[0]&&item[1]===this.range[1]);if(index>=0)editSegment(role,index,role.id==='artist2'?'lead':'artist2');},'editor-button');
    const actions=element('div','editor-actions');actions.append(this.record,this.exclude,this.artist);
    root.append(selection,this.wave,transport,this.caption,actions,element('p','editor-help','Перетащи ползунок и запиши с этого места. Белая заливка — уже записано. Перед записью — отсчёт и 3 секунды музыки.'));
    const update=()=>{ const audio=recording?$('recordingMusic'):role.guide;this.cursor.value=audio.currentTime;this.time.textContent=`${seconds(audio.currentTime,true)} / ${seconds(this.duration)}`;this.refresh();if(role.guide.dataset.stop&&role.guide.currentTime>=Number(role.guide.dataset.stop)){role.guide.pause();delete role.guide.dataset.stop;} };
    role.guide.addEventListener('timeupdate',update);role.guide.addEventListener('seeked',update);this.musicUpdate=()=>{if(recording&&!root.closest('.track').hidden)update();};$('recordingMusic').addEventListener('timeupdate',this.musicUpdate);
    role.guide.addEventListener('play',()=>this.play.textContent='Ⅱ Пауза');role.guide.addEventListener('pause',()=>this.play.textContent='▶ Слушать партию');
    if(typeof ResizeObserver!=='undefined'){this.observer=new ResizeObserver(()=>this.draw());this.observer.observe(this.wave);}
    this.setRange(role.id==='backing'&&role.segments.length?role.segments[0]:this.range);role.guide.currentTime=this.range[0];this.cursor.value=this.range[0];this.refresh();
    const current=projectId;
    request(`/api/waveform?id=${current}&role=${encodeURIComponent(role.id)}`).then(data=>{if(current===projectId){this.peaks=data.peaks;this.draw();}}).catch(()=>{this.caption.textContent='Волна не загрузилась. Перемотка и запись доступны.';});
  }
  dispose() {this.observer?.disconnect();$('recordingMusic').removeEventListener('timeupdate',this.musicUpdate);this.role.guide.pause();}
  excluded() { return this.role.excluded?.find(item=>item[0]===this.range[0]&&item[1]===this.range[1]); }
  setRange(range) {
    this.range=[Math.max(0,range[0]),Math.min(this.duration,range[1])];
    const index=this.role.segments.findIndex(item=>item[0]===this.range[0]&&item[1]===this.range[1]);
    const excluded=this.role.excluded?.findIndex(item=>item[0]===this.range[0]&&item[1]===this.range[1]);
    this.parts.value=this.range[0]===0&&this.range[1]===this.duration?'all':excluded>=0?'excluded-'+excluded:index>=0?String(index):'custom';
    if(this.range[0]<this.view[0]||this.range[1]>this.view[1]) this.view=[0,this.duration];
    this.refresh();
  }
  refresh() {
    this.node.classList.toggle('editing',this.selecting);
    this.start.value=this.range[0];this.end.value=this.range[1];this.node.querySelector('.editor-help').textContent=this.selecting?'Протяни по волне, чтобы выделить лишний вокал, затем нажми «Убрать вокал на участке».':'Перетащи ползунок и запиши с этого места. Белая заливка — уже записано. Перед записью — отсчёт и 3 секунды музыки.';
    this.node.querySelectorAll('.view-control').forEach(node=>node.hidden=!this.selecting);const position=Number(this.cursor.value);this.start.hidden=this.end.hidden=this.parts.hidden=this.exclude.hidden=!this.selecting;this.selectionToggle.textContent=this.selecting?'Закончить выделение':'Убрать лишний вокал';this.selectionToggle.setAttribute('aria-pressed',String(this.selecting));
    const hasTake=project.tracks.some(take=>take.role===this.role.id&&(take.region||[0,this.duration])[0]<this.range[1]&&(take.region||[0,this.duration])[1]>this.range[0]);
    const excluded=this.excluded();this.record.hidden=this.selecting;this.record.disabled=busy()||window.engineCompatible===false||position>=this.duration-.05;this.record.textContent=position>=this.duration-.05?'Перемести ползунок к месту записи':`● ${hasTake?'Записать / перезаписать':'Записать'} с ${seconds(position,true)}`;
    this.exclude.textContent=excluded?'Вернуть выделенное':'Убрать вокал на участке';
    this.artist.hidden=!this.selecting||this.role.id==='backing'||!!excluded||!this.role.segments.some(item=>item[0]===this.range[0]&&item[1]===this.range[1]);
    this.caption.textContent=this.selecting?`${excluded?'Убрано':'Убрать вокал'}: ${seconds(this.range[0],true)} — ${seconds(this.range[1],true)} · ${(this.range[1]-this.range[0]).toFixed(1)} сек.`:`Начать с ${seconds(position,true)} · новый дубль заменит только записанный участок`;
    this.draw();
  }
  draw() {
    const width=this.wave.clientWidth;if(!width)return;
    const height=this.canvas.clientHeight||140,ratio=Math.min(devicePixelRatio||1,2);this.canvas.width=width*ratio;this.canvas.height=height*ratio;
    const ctx=this.canvas.getContext('2d');ctx.scale(ratio,ratio);const length=this.view[1]-this.view[0],x=time=>(time-this.view[0])/length*width;
    ctx.fillStyle='#102128';ctx.fillRect(0,0,width,height);
    if(this.selecting){ctx.fillStyle='#ff985a18';ctx.fillRect(x(this.range[0]),0,x(this.range[1])-x(this.range[0]),height);}
    for(const range of this.role.segments){ctx.fillStyle='#d3ef8530';ctx.fillRect(x(range[0]),height-10,Math.max(2,x(range[1])-x(range[0])),10);}
    for(let pixel=0;pixel<width;pixel+=3){const time=this.view[0]+pixel/width*length,index=Math.floor(time/this.duration*this.peaks.length);const peak=this.peaks[index]||0;ctx.fillStyle=this.selecting&&time>=this.range[0]&&time<=this.range[1]?'#ffab74':'#638b96';ctx.fillRect(pixel,height/2-peak*height*.37,2,Math.max(1,peak*height*.74));}
    for(const range of this.role.excluded||[]){ctx.fillStyle='#ff505544';ctx.fillRect(x(range[0]),0,x(range[1])-x(range[0]),height);}
    const coverage=activeTakes(this.role).map(take=>take.region||[0,this.duration]).sort((a,b)=>a[0]-b[0]),merged=[];
    for(const range of coverage){const last=merged.at(-1);if(last&&range[0]<=last[1])last[1]=Math.max(last[1],range[1]);else merged.push(range.slice());}
    for(const range of merged){ctx.fillStyle='#ffffff30';ctx.fillRect(x(range[0]),0,x(range[1])-x(range[0]),height);}
    if(recording&&recordSession?.role===this.role.id){ctx.fillStyle='#ffffff66';ctx.fillRect(x(recordSession.cueStart),0,Math.max(0,x(Number(this.cursor.value))-x(recordSession.cueStart)),height);}
    ctx.fillStyle='#eff5e3';ctx.fillRect(x(Number(this.cursor.value)),0,2,height);
    for(const input of [this.start,this.end]){input.min=this.view[0];input.max=this.view[1];input.value=input===this.start?this.range[0]:this.range[1];}
  }
}
