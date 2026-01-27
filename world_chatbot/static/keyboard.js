(() => {
  const root = document.getElementById('keyboard');
  const input = document.getElementById('input');
  const sendBtn = document.getElementById('sendBtn');

  const rows = [
    ['`','1','2','3','4','5','6','7','8','9','0','-','=','Backspace'],
    ['Tab','q','w','e','r','t','y','u','i','o','p','[',']','\\'],
    ['Caps','a','s','d','f','g','h','j','k','l',';','\'','Enter'],
    ['Shift','z','x','c','v','b','n','m',',','.','/','Shift'],
    ['Space']
  ];

  function insertText(t) {
    const start = input.selectionStart ?? input.value.length;
    const end = input.selectionEnd ?? input.value.length;
    input.value = input.value.slice(0,start) + t + input.value.slice(end);
    const pos = start + t.length;
    input.setSelectionRange(pos,pos);
    input.focus();
  }

  function backspace() {
    const start = input.selectionStart ?? input.value.length;
    const end = input.selectionEnd ?? input.value.length;
    if (start !== end) {
      input.value = input.value.slice(0,start) + input.value.slice(end);
      input.setSelectionRange(start,start);
      input.focus();
      return;
    }
    if (start <= 0) return;
    input.value = input.value.slice(0,start-1) + input.value.slice(start);
    input.setSelectionRange(start-1,start-1);
    input.focus();
  }

  function makeKey(label) {
    const b = document.createElement('button');
    b.className = 'key';
    b.textContent = label;
    if (['Backspace','Tab','Caps','Enter','Shift'].includes(label)) b.classList.add('wide');
    if (label === 'Space') b.classList.add('space');
    b.addEventListener('click', () => {
      if (label === 'Backspace') return backspace();
      if (label === 'Tab') return insertText('\t');
      if (label === 'Enter') return sendBtn.click();
      if (label === 'Space') return insertText(' ');
      if (label === 'Caps' || label === 'Shift') return; // visual only
      insertText(label);
    });
    return b;
  }

  function render() {
    root.innerHTML = '';
    for (const r of rows) {
      const row = document.createElement('div');
      row.className = 'keyrow';
      for (const k of r) row.appendChild(makeKey(k));
      root.appendChild(row);
    }
  }

  render();
})();
