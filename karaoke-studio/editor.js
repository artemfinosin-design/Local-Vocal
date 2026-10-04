/* One selection, one transport and one record action for each vocal part. */
class VocalEditor {
  constructor(role) {
    this.role=role; this.duration=project.duration; this.range=[0,this.duration]; this.view=[0,this.duration]; this.peaks=[];
    const root=this.node=element('div','vocal-editor');
    const selection=element('div','selection-picker');
    this.parts=element('select'); this.parts.setAttribute('aria-label','Выбрать участок для записи');
    const whole=element('option','','Вся партия'); whole.value='all'; this.parts.append(whole);
    role.segments.forEach((range,index)=>{ const option=element('option','',`Фрагмент ${index+1} · ${seconds(range[0],true)} — ${seconds(range[1],true)}`); option.value=index; this.parts.append(option); });
    for(const [index,range] of (role.excluded||[]).entries()) { const option=element('option','',`Исключён · ${seconds(range[0],true)} — ${seconds(range[1],true)}`);option.value='excluded-'+index;this.parts.append(option); }
    const custom=element('option','','Своя область');custom.value='custom';this.parts.append(custom);
    this.parts.addEventListener('change',()=>{ const key=this.parts.value; if(key==='custom') return; const range=key==='all'?[0,this.duration]:key.startsWith('excluded-')?role.excluded[Number(key.slice(9))]:role.segments[Number(key)]; this.setRange(range); });
    selection.append(this.parts,button('Весь трек',()=>{this.view=[0,this.duration];this.draw();},'editor-button'),button('Приблизить участок',()=>{this.view=[Math.max(0,this.range[0]-2),Math.min(this.duration,this.range[1]+2)];this.draw();},'editor-button'));
    this.wave=element('div','wave-editor');
    this.canvas=element('canvas'); this.canvas.setAttribute('aria-label','Волна вокала. Нажми для перемотки.');
    this.wave.append(this.canvas);
    for(const [key,label] of [['start','Начало выделения'],['end','Конец выделения']]) {
      const input=element('input','trim-handle trim-'+key);Object.assign(input,{type:'range',min:0,max:this.duration,step:.01,value:key==='start'?0:this.duration,id:`range-${role.id}-${key}`}); input.setAttribute('aria-label',label);
      input.addEventListener('input',()=>{ if(busy()) return; const index=key==='start'?0:1, value=Number(input.value);this.range[index]=index===0?Math.min(value,this.range[1]-.1):Math.max(value,this.range[0]+.1);this.parts.value='custom';this.refresh(); });
      this.wave.append(input);this[key]=input;
    }
    const seek=event=>{ if(busy()) return; const rect=this.canvas.getBoundingClientRect(); const ratio=Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width));role.guide.currentTime=this.view[0]+ratio*(this.view[1]-this.view[0]);this.draw(); };
    this.canvas.addEventListener('pointerdown',event=>{this.canvas.setPointerCapture?.(event.pointerId);seek(event);});
    this.canvas.addEventListener('pointermove',event=>{if(event.buttons===1) seek(event);});
    const transport=element('div','editor-transport');
    this.play=button('▶ Слушать',async()=>{ if(busy()) return; if(!role.guide.paused){role.guide.pause();return;}stopPreview();pauseAll();if(role.guide.currentTime<this.range[0]||role.guide.currentTime>=this.range[1]) role.guide.currentTime=Math.max(0,this.range[0]-1);role.guide.dataset.stop=this.range[1]+.2;try{await role.guide.play();}catch(error){$('recordStatus').textContent=error.message;} },'editor-button');
    const cursorLabel=element('label','seek-control','Позиция');this.cursor=element('input');Object.assign(this.cursor,{type:'range',min:0,max:this.duration,step:.01,value:0});this.cursor.setAttribute('aria-label','Перемотка песни');this.cursor.addEventListener('input',()=>{if(!busy())role.guide.currentTime=Number(this.cursor.value);this.draw();});cursorLabel.append(this.cursor);
    this.time=element('output','editor-clock',`0:00 / ${seconds(this.duration)}`);transport.append(this.play,cursorLabel,this.time);
    this.caption=element('div','selection-caption');
    this.record=button('● Записать',()=>startRecording(role,this.range.slice()),'primary record-selection');
    this.exclude=button('Исключить выделенное',()=>{const excluded=this.excluded();editSegment(role,null,excluded?'restore':'exclude',excluded||this.range.slice());},'editor-button');
    this.artist=button(role.id==='artist2'?'В основной вокал':'Другой исполнитель',()=>{const index=role.segments.findIndex(item=>item[0]===this.range[0]&&item[1]===this.range[1]);if(index>=0)editSegment(role,index,role.id==='artist2'?'lead':'artist2');},'editor-button');
    const actions=element('div','editor-actions');actions.append(this.record,this.exclude,this.artist);
    root.append(selection,this.wave,transport,this.caption,actions,element('p','editor-help','Потяни за светящиеся края, чтобы выбрать слово или фразу. Перед записью — отсчёт и 3 секунды музыки.'));
    const update=()=>{ const audio=recording?$('instrumental'):role.guide;this.cursor.value=audio.currentTime;this.time.textContent=`${seconds(audio.currentTime,true)} / ${seconds(this.duration)}`;this.draw();if(role.guide.dataset.stop&&role.guide.currentTime>=Number(role.guide.dataset.stop)){role.guide.pause();delete role.guide.dataset.stop;} };
    role.guide.addEventListener('timeupdate',update);role.guide.addEventListener('seeked',update);this.musicUpdate=()=>{if(recording&&!root.closest('.track').hidden)update();};$('instrumental').addEventListener('timeupdate',this.musicUpdate);
    role.guide.addEventListener('play',()=>this.play.textContent='Ⅱ Пауза');role.guide.addEventListener('pause',()=>this.play.textContent='▶ Слушать');
    if(typeof ResizeObserver!=='undefined'){this.observer=new ResizeObserver(()=>this.draw());this.observer.observe(this.wave);}
    this.setRange(role.id==='backing'&&role.segments.length?role.segments[0]:this.range);
    const current=projectId;
    request(`/api/waveform?id=${current}&role=${encodeURIComponent(role.id)}`).then(data=>{if(current===projectId){this.peaks=data.peaks;this.draw();}}).catch(()=>{this.caption.textContent='Волна не загрузилась. Перемотка и запись доступны.';});
  }
  dispose() {this.observer?.disconnect();$('instrumental').removeEventListener('timeupdate',this.musicUpdate);this.role.guide.pause();}
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
    this.start.value=this.range[0];this.end.value=this.range[1];
    const hasTake=project.tracks.some(take=>take.role===this.role.id&&(take.region||[0,this.duration])[0]<this.range[1]&&(take.region||[0,this.duration])[1]>this.range[0]);
    const excluded=this.excluded();this.record.hidden=!!excluded;this.record.textContent=hasTake?'● Перезаписать выделенное':'● Записать выделенное';
    this.exclude.textContent=excluded?'Вернуть выделенное':'Исключить выделенное';
    this.artist.hidden=this.role.id==='backing'||!!excluded||!this.role.segments.some(item=>item[0]===this.range[0]&&item[1]===this.range[1]);
    this.caption.textContent=`${excluded?'Исключено':'Выделено'}: ${seconds(this.range[0],true)} — ${seconds(this.range[1],true)} · ${(this.range[1]-this.range[0]).toFixed(1)} сек.`;
    this.draw();
  }
  draw() {
    const width=this.wave.clientWidth;if(!width)return;
    const height=140,ratio=Math.min(devicePixelRatio||1,2);this.canvas.width=width*ratio;this.canvas.height=height*ratio;
    const ctx=this.canvas.getContext('2d');ctx.scale(ratio,ratio);const length=this.view[1]-this.view[0],x=time=>(time-this.view[0])/length*width;
    ctx.fillStyle='#102128';ctx.fillRect(0,0,width,height);
    ctx.fillStyle='#ff985a18';ctx.fillRect(x(this.range[0]),0,x(this.range[1])-x(this.range[0]),height);
    for(const range of this.role.segments){ctx.fillStyle='#d3ef8530';ctx.fillRect(x(range[0]),height-10,Math.max(2,x(range[1])-x(range[0])),10);}
    for(let pixel=0;pixel<width;pixel+=3){const time=this.view[0]+pixel/width*length,index=Math.floor(time/this.duration*this.peaks.length);const peak=this.peaks[index]||0;ctx.fillStyle=time>=this.range[0]&&time<=this.range[1]?'#ffab74':'#638b96';ctx.fillRect(pixel,height/2-peak*52,2,Math.max(1,peak*104));}
    for(const range of this.role.excluded||[]){ctx.fillStyle='#ff505544';ctx.fillRect(x(range[0]),0,x(range[1])-x(range[0]),height);}
    ctx.fillStyle='#eff5e3';ctx.fillRect(x(Number(this.cursor.value)),0,2,height);
    for(const input of [this.start,this.end]){input.min=this.view[0];input.max=this.view[1];input.value=input===this.start?this.range[0]:this.range[1];}
  }
}
