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
    async select(id,role){
      const next=id+':'+role;if(next===key)return;stop();key=next;const ticket=++generation;bars=[];loading=true;music=roles.find(item=>item.id===role)?.guide||null;status.textContent='Размечаем мелодию…';draw();
      try{const data=await request(`/api/note-guide?id=${id}&role=${encodeURIComponent(role)}`);if(ticket!==generation)return;bars=data.bars;loading=false;status.textContent='Полоски — мелодия, точка — твой голос';draw();}
      catch(error){if(ticket===generation){loading=false;status.textContent='Ноты недоступны · запись работает';draw();}}
    },
    reset(){++generation;key='';bars=[];music=null;stop();},
    async start(stream,audio){stop();music=audio;try{context=new AudioContext();await context.resume();source=context.createMediaStreamSource(stream);analyser=context.createAnalyser();analyser.fftSize=8192;source.connect(analyser);lastPitchTime=0;frame=requestAnimationFrame(draw);}catch(error){stop();status.textContent='Микрофон записывается · подсказка нот недоступна';}},
    stop
  };
  document.addEventListener('play',event=>{if(event.target.closest('.track')&&!analyser){music=event.target;cancelAnimationFrame(frame);frame=requestAnimationFrame(draw);}},true);
  document.addEventListener('seeked',event=>{if(event.target===music&&!analyser)draw();},true);
  new ResizeObserver(()=>{if(!analyser)draw();}).observe(canvas);
})();
