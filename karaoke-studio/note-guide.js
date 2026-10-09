/* Visual feedback reads the microphone; it never changes the recorded signal. */
function detectNote(samples, rate) {
  let energy=0;for(const value of samples)energy+=value*value;
  if(Math.sqrt(energy/samples.length)<.008)return null;
  const half=Math.floor(samples.length/2), max=Math.min(half-1,Math.ceil(rate/65));
  const difference=new Float32Array(max+1);let sum=0;
  for(let lag=1;lag<=max;lag++){
    let delta=0;for(let i=0;i<half;i++){const d=samples[i]-samples[i+lag];delta+=d*d;}
    sum+=delta;difference[lag]=sum?delta*lag/sum:1;
  }
  for(let lag=Math.floor(rate/1100);lag<max-1;lag++){
    if(difference[lag]>.12)continue;
    while(lag<max-1&&difference[lag+1]<difference[lag])lag++;
    const a=difference[lag-1],b=difference[lag],c=difference[lag+1];
    const refined=lag+(a-c)/(2*(a-2*b+c)||Infinity);
    return 69+12*Math.log2(rate/refined/440);
  }
  return null;
}
function noteDistance(a,b){return Math.abs(((a-b+6)%12+12)%12-6);}
if(typeof module!=='undefined')module.exports={detectNote,noteDistance};
if(typeof document!=='undefined')(()=>{
  const canvas=document.getElementById('noteCanvas'),status=document.getElementById('noteLive');
  let bars=[],key='',generation=0,context,source,analyser,music,frame=0,lastPitchTime=0,pitch=null,hit=false,loading=false;
  const names=['До','До♯','Ре','Ре♯','Ми','Фа','Фа♯','Соль','Соль♯','Ля','Ля♯','Си'];
  const label=note=>names[((Math.round(note)%12)+12)%12];
  function draw(time=0){
    const w=canvas.clientWidth,h=canvas.clientHeight;if(!w||!h)return;
    const ratio=Math.min(devicePixelRatio||1,2);canvas.width=w*ratio;canvas.height=h*ratio;
    const ctx=canvas.getContext('2d');ctx.scale(ratio,ratio);
    const clock=music?.currentTime||0,visible=bars.filter(b=>b.end>clock-1.5&&b.start<clock+4.5);
    const current=bars.find(b=>b.start<=clock&&b.end>=clock);
    if(analyser&&time-lastPitchTime>90){
      const raw=new Float32Array(analyser.fftSize);analyser.getFloatTimeDomainData(raw);
      const step=Math.max(1,Math.floor(context.sampleRate/12000)),data=new Float32Array(Math.floor(raw.length/step));
      for(let i=0;i<data.length;i++)data[i]=raw[i*step];
      pitch=detectNote(data,context.sampleRate/step);lastPitchTime=time;
      hit=pitch!==null&&!!current&&noteDistance(pitch,current.note)<=.5;
      status.textContent=pitch===null?'Пой — здесь появится твоя нота':`${label(pitch)} · ${hit?'В ноту!':current?'Следуй полоске':'Пауза в партии'}`;
    }
    const notes=bars.map(b=>b.note).sort((a,b)=>a-b),low=notes.length?notes[Math.floor(notes.length*.05)]-3:48,high=notes.length?Math.max(low+12,notes[Math.floor((notes.length-1)*.95)]+3):60;
    const x=t=>(t-clock+1.5)/6*w,y=n=>h-12-(n-low)/(high-low)*(h-24);
    ctx.fillStyle='#102128';ctx.fillRect(0,0,w,h);ctx.lineWidth=1;
    for(let n=low;n<=high;n++){ctx.strokeStyle='#ffffff0c';ctx.beginPath();ctx.moveTo(0,y(n));ctx.lineTo(w,y(n));ctx.stroke();}
    const calm=matchMedia('(prefers-reduced-motion: reduce)').matches||window.studioAppearance?.calm;
    for(const bar of visible){
      const active=bar===current&&hit;ctx.fillStyle=active?'#edffbd':'#8acbd1';ctx.shadowColor='#d3ef85';ctx.shadowBlur=active&&!calm?16:0;
      ctx.beginPath();ctx.roundRect(x(bar.start),y(bar.note)-4,Math.max(4,x(bar.end)-x(bar.start)),8,4);ctx.fill();
    }
    ctx.shadowBlur=0;ctx.strokeStyle='#ff985a';ctx.beginPath();ctx.moveTo(w*.25,0);ctx.lineTo(w*.25,h);ctx.stroke();
    if(pitch!==null&&current){const adjusted=pitch+12*Math.round((current.note-pitch)/12);ctx.fillStyle=hit?'#e6ff9e':'#ff985a';ctx.beginPath();ctx.arc(w*.25,y(adjusted),hit&&!calm?7+Math.sin(time/100)*1.5:5,0,Math.PI*2);ctx.fill();}
    canvas.classList.toggle('note-hit',hit&&!calm);
    if(!bars.length){ctx.fillStyle='#9bb1ba';ctx.font='13px sans-serif';ctx.fillText(loading?'Размечаем мелодию…':'Для этой партии нет уверенных нот',12,h/2);}
    if(analyser||music&&!music.paused)frame=requestAnimationFrame(draw);
  }
  function stop(){cancelAnimationFrame(frame);source?.disconnect();analyser?.disconnect();if(context)context.close().catch(()=>{});context=source=analyser=null;pitch=null;hit=false;music=null;canvas.classList.remove('note-hit');draw();}
  window.noteGuide={
    async select(id,role,force=false){
      const next=id+':'+role;if(next===key&&!force)return;stop();key=next;const ticket=++generation;bars=[];loading=true;music=roles.find(item=>item.id===role)?.guide||null;status.textContent='Размечаем мелодию…';draw();
      try{const data=await request(`/api/note-guide?id=${id}&role=${encodeURIComponent(role)}`);if(ticket!==generation)return;bars=data.bars;loading=false;status.textContent=data.source==='ultrastar'?'Ноты из загруженной карты UltraStar · точка — твой голос':'Автоноты из исходного вокала · точка — твой голос';draw();}
      catch(error){if(ticket===generation){loading=false;status.textContent='Ноты недоступны · запись работает';draw();}}
    },
    reset(){++generation;key='';bars=[];music=null;stop();},
    async start(stream,audio){stop();music=audio;try{context=new AudioContext();await context.resume();source=context.createMediaStreamSource(stream);analyser=context.createAnalyser();analyser.fftSize=8192;source.connect(analyser);lastPitchTime=0;frame=requestAnimationFrame(draw);}catch(error){stop();status.textContent='Микрофон записывается · подсказка нот недоступна';}},
    stop
  };
  document.addEventListener('play',event=>{if(event.target.closest('.track')&&!analyser){music=event.target;cancelAnimationFrame(frame);frame=requestAnimationFrame(draw);}},true);
  document.addEventListener('seeked',event=>{if(event.target===music&&!analyser)draw();},true);
  new ResizeObserver(()=>{if(!analyser)draw();}).observe(canvas);
  const dialog=document.getElementById('noteChartDialog'),file=document.getElementById('noteChartFile'),role=document.getElementById('noteChartRole'),voice=document.getElementById('noteChartVoice'),offset=document.getElementById('noteChartOffset'),apply=document.getElementById('applyNoteChart'),message=document.getElementById('noteChartStatus');
  let chartText='',previewToken=0;
  async function preview(){
    const ticket=++previewToken;apply.disabled=true;
    if(!chartText||!projectId)return;
    message.textContent='Проверяю карту и время нот…';
    try{
      const data=await post('note-chart',{action:'preview',role:role.value,voice:voice.value,text:chartText,offset:Number(offset.value)});
      if(ticket!==previewToken)return;
      const selected=data.voice;voice.replaceChildren();
      for(const item of data.voices){const option=new Option(`${item.name} · нот: ${item.count}`,item.id);voice.append(option);}
      voice.value=selected;
      document.getElementById('noteChartPreview').textContent=`${data.artist?data.artist+' — ':''}${data.title||'Карта нот'} · нот: ${data.count} · ${seconds(data.first,true)}–${seconds(data.last,true)}. Сравни время первой фразы с песней.`;
      message.textContent='Карта готова к применению. При другом аудиомонтаже сдвинь ноты ползунком.';apply.disabled=false;
    }catch(error){if(ticket===previewToken)message.textContent=error.message;}
  }
  document.getElementById('openNoteCharts').addEventListener('click',()=>{
    const title=document.getElementById('songTitle').value||project?.song_info?.title||'',artist=document.getElementById('songArtist').value||project?.song_info?.artist||'';
    document.getElementById('noteChartSong').textContent=[artist,title].filter(Boolean).join(' — ')||'Укажи название песни в разделе «Текст караоке», чтобы искать её карту.';
    document.getElementById('noteChartSearch').href=title?'https://www.google.com/search?'+new URLSearchParams({q:`site:usdb.animux.de ${artist} ${title}`}):'https://usdb.animux.de/';
    role.replaceChildren();for(const part of roles)role.append(new Option(part.name,part.id));
    const active=key.split(':')[1];if(roles.some(part=>part.id===active))role.value=active;
    file.value='';chartText='';voice.replaceChildren();offset.value=0;document.getElementById('noteChartOffsetValue').textContent='0,0 с';apply.disabled=true;
    document.getElementById('noteChartPreview').textContent='Загрузи TXT: появится время первой и последней ноты.';message.textContent='';
  });
  file.addEventListener('change',async()=>{
    const chosen=file.files[0];if(!chosen)return;
    if(chosen.size>100000){message.textContent='Файл нот больше 100 КБ';return;}
    chartText=await chosen.text();preview();
  });
  role.addEventListener('change',preview);voice.addEventListener('change',preview);
  offset.addEventListener('input',()=>document.getElementById('noteChartOffsetValue').textContent=Number(offset.value).toFixed(1).replace('.',',')+' с');
  offset.addEventListener('change',preview);
  apply.addEventListener('click',async()=>{
    if(!chartText||busy())return;apply.disabled=true;message.textContent='Сохраняю ноты локально…';
    try{await post('note-chart',{action:'apply',role:role.value,voice:voice.value,text:chartText,offset:Number(offset.value)});window.studioFlow.dirty();message.textContent='Готово. Карта заменяет автоноты. Для новой оценки пения собери песню снова.';if(key===projectId+':'+role.value)await window.noteGuide.select(projectId,role.value,true);}
    catch(error){message.textContent=error.message;}finally{apply.disabled=false;}
  });
  document.getElementById('clearNoteChart').addEventListener('click',async()=>{
    if(!projectId||busy())return;message.textContent='Возвращаю авторазметку…';
    try{await post('note-chart',{action:'clear',role:role.value});window.studioFlow.dirty();message.textContent='Для этой партии снова используются автоноты. Для новой оценки собери песню снова.';if(key===projectId+':'+role.value)await window.noteGuide.select(projectId,role.value,true);}
    catch(error){message.textContent=error.message;}
  });
})();
