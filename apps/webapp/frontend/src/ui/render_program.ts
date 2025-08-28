const content = document.getElementById('content');

export function renderProgram(program: string): void {
  if (!content) return;
  content.innerHTML = '';
  content.style.whiteSpace = 'normal';
  try {
    const blocks = program.split(/\n{2,}/).filter(Boolean);
    if (blocks.length === 0) throw new Error('empty');
    for (const block of blocks) {
      const lines = block.split(/\n/).filter(Boolean);
      if (lines.length === 0) continue;
      const wrapper = document.createElement('div');
      wrapper.className = 'program-day';
      const title = document.createElement('h3');
      title.textContent = lines[0];
      wrapper.appendChild(title);
      const ul = document.createElement('ul');
      for (const line of lines.slice(1)) {
        const li = document.createElement('li');
        li.textContent = line;
        ul.appendChild(li);
      }
      wrapper.appendChild(ul);
      content.appendChild(wrapper);
    }
  } catch {
    content.style.whiteSpace = 'pre-wrap';
    content.textContent = program || '';
  }
}
