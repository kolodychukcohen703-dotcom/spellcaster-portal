(() => {
  const socket = io('/world');
  const chat = document.getElementById('chat');
  const input = document.getElementById('input');
  const sendBtn = document.getElementById('sendBtn');
  const worldList = document.getElementById('worldList');
  const homeList = document.getElementById('homeList');
  const connDot = document.getElementById('connDot');
  const connText = document.getElementById('connText');
  const quick = document.getElementById('quick');
  const userCount = document.getElementById('userCount');

  function nowTime(ts) {
    const d = ts ? new Date(ts) : new Date();
    return d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
  }

  function addMsg({user, body, kind, ts}) {
    const el = document.createElement('div');
    el.className = 'msg ' + (kind || '');
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.innerHTML = `<span>${user}</span><span>${nowTime(ts)}</span>`;
    const b = document.createElement('div');
    b.className = 'body';
    b.textContent = body;
    el.appendChild(meta);
    el.appendChild(b);
    chat.appendChild(el);
    chat.scrollTop = chat.scrollHeight;
  }

  function renderCards(container, items, type) {
    container.innerHTML = '';
    items.forEach(it => {
      const c = document.createElement('div');
      c.className = 'card';
      const title = document.createElement('div');
      title.innerHTML = `<div class="k">${type}</div><div class="v">${it.id} — ${it.name}</div>`;
      const small = document.createElement('div');
      small.className = 'k';
      small.textContent = type === 'world'
        ? `biome=${it.biome}  magic=${it.magic}  pop=${it.population}`
        : `world=${it.world}  style=${it.style}  size=${it.size}`;
      c.appendChild(title);
      c.appendChild(small);
      c.addEventListener('click', () => {
        // Click selects (world) or stats (home)
        input.value = type === 'world' ? `!select world ${it.id}` : `!home stats ${it.id}`;
        input.focus();
      });
      c.addEventListener('dblclick', () => {
        input.value = type === 'world' ? `!stats ${it.id}` : `!home map ${it.id}`;
        input.focus();
      });
      container.appendChild(c);
    });
  }

  function send() {
    const text = (input.value || '').trim();
    if (!text) return;
    socket.emit('chat', {body: text});
    input.value = '';
    input.focus();
  }

  sendBtn.addEventListener('click', send);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); send(); }
  });

  socket.on('connect', () => {
    connDot.classList.add('on');
    connDot.classList.remove('off');
    connText.textContent = 'online';
  });
  socket.on('disconnect', () => {
    connDot.classList.remove('on');
    connText.textContent = 'offline';
  });

  socket.on('msg', (payload) => addMsg(payload));
  socket.on('state', (payload) => {
    renderCards(worldList, payload.worlds || [], 'world');
    renderCards(homeList, payload.homes || [], 'home');
  });

  socket.on('user_count', (payload) => {
    if (userCount) userCount.textContent = String(payload.count ?? 0);
  });

  const quickButtons = [
    {label:'!help', cmd:'!help'},
    {label:'!world list', cmd:'!world list'},
    {label:'!home list', cmd:'!home list'},
    {label:'!create world', cmd:'!create world'},
    {label:'!create home', cmd:'!create home'},
    {label:'!users', cmd:'!users'}
  ];
  quickButtons.forEach(b => {
    const btn = document.createElement('button');
    btn.textContent = b.label;
    btn.addEventListener('click', () => {
      input.value = b.cmd;
      input.focus();
    });
    quick.appendChild(btn);
  });
})();
