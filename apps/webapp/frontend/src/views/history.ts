import { applyLang, t } from '../i18n/i18n';
import { goToProgram } from '../router';

export async function renderHistoryView(): Promise<void> {
  await applyLang(document.documentElement.lang as any || 'en');
  const content = document.getElementById('content');
  const titleEl = document.getElementById('page-title');
  const dateBlock = document.getElementById('program-date');

  if (!content || !titleEl || !dateBlock) return;

  titleEl.textContent = t('history');
  dateBlock.hidden = true;
  content.innerHTML = '';

  // TODO: заменить мок данными от API
  const mockPrograms = [
    { id: 'p1', title: 'Push Day', created: '2025-09-01' },
    { id: 'p2', title: 'Pull Day', created: '2025-09-05' },
  ];

  if (mockPrograms.length === 0) {
    const p = document.createElement('p');
    p.textContent = t('no_programs');
    content.appendChild(p);
    return;
  }

  const ul = document.createElement('ul');
  ul.className = 'history-list';

  mockPrograms.forEach((prog) => {
    const li = document.createElement('li');
    const a = document.createElement('a');
    a.href = '#';
    a.className = 'history-link';
    a.textContent = `${prog.title} — ${prog.created}`;
    a.addEventListener('click', (e) => {
      e.preventDefault();
      goToProgram(prog.id);
    });
    li.appendChild(a);
    ul.appendChild(li);
  });

  content.appendChild(ul);
}
