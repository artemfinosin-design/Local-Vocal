(() => {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const bars = document.querySelector('.signal-bars');
  for (let i = 0; i < 40; i++) {
    const bar = document.createElement('i');
    bar.style.setProperty('--bar', `${4 + ((i * 7 + i * i) % 15)}px`);
    bars.append(bar);
  }
  if ('IntersectionObserver' in window && !reduced) {
    document.body.classList.add('motion-ready');
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    }, {threshold: 0.08});
    document.querySelectorAll('.reveal').forEach(element => observer.observe(element));
  }
  let scheduled = false;
  const progress = () => {
    const maximum = document.documentElement.scrollHeight - innerHeight;
    document.documentElement.style.setProperty('--scroll', `${maximum > 0 ? scrollY / maximum * 100 : 0}%`);
    scheduled = false;
  };
  addEventListener('scroll', () => { if (!scheduled) { scheduled = true; requestAnimationFrame(progress); } }, {passive: true});
  progress();
  let toastTimer;
  window.studioToast = message => {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.classList.add('visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('visible'), 3500);
  };
  const secret = () => {
    document.body.classList.toggle('acid-mode');
    const acid = document.body.classList.contains('acid-mode');
    dispatchEvent(new CustomEvent('studio-accent', {detail: acid ? '#d3ef85' : '#ff985a'}));
    window.studioToast(acid ? 'Паттерн 303 найден. Добро пожаловать в acid room.' : 'Вернулись к тёплому студийному свету.');
  };
  document.getElementById('brandEgg').addEventListener('dblclick', event => { event.preventDefault(); secret(); });
  let keys = '';
  addEventListener('keydown', event => {
    if (/INPUT|TEXTAREA/.test(event.target.tagName)) return;
    if (event.key.length === 1) keys = (keys + event.key.toLowerCase()).slice(-6);
    if (keys === 'groove') { secret(); keys = ''; }
  });
  const playback = () => document.body.classList.toggle('playing', [...document.querySelectorAll('audio')].some(audio => !audio.paused));
  document.addEventListener('play', playback, true);
  document.addEventListener('pause', playback, true);
  document.addEventListener('ended', playback, true);
})();
