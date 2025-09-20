import { t } from '../i18n/i18n';
import type { HistoryResp } from '../api/types';
import { goToProgram } from '../router';
import { readInitData } from '../telegram';

const content = document.getElementById('content') as HTMLElement | null;
const dateChip = document.getElementById('program-date') as HTMLDivElement | null;

async function getHistory(): Promise<HistoryResp> {
  const headers: Record<string, string> = {};
  const initData = readInitData();
  if (initData) headers['X-Telegram-InitData'] = initData;
  const resp = await fetch('/api/programs/', { headers });
  if (!resp.ok) throw new Error('unexpected_error');
  return (await resp.json()) as HistoryResp;
}

export async function renderHistoryView(): Promise<void> {
  if (!content) return;
  content.setAttribute('aria-busy', 'true');
  content.innerHTML = '';

  const historyButton = document.getElementById('history-button') as HTMLButtonElement | null;

  // локализация кнопки
  if (historyButton) {
    historyButton.textContent = t('back');
    historyButton.disabled = false;
    historyButton.onclick = () => goToProgram();
  }
  if (dateChip) dateChip.hidden = true;

  const wrap = document.createElement('div');
  wrap.className = 'week';
  const h2 = document.createElement('h2');
  h2.textContent = t('history');
  wrap.appendChild(h2);

  const ul = document.createElement('ul');
  ul.className = 'history-list';
  wrap.appendChild(ul);
  content.appendChild(wrap);

  try {
    const data = await getHistory();
    const items = data.programs ?? [];
    if (items.length === 0) {
      const p = document.createElement('p');
      p.className = 'history-empty';
      p.textContent = t('no_programs');
      content.appendChild(p);
    } else {
      items.forEach((it) => {
        const li = document.createElement('li');
        const a = document.createElement('a');
        a.href = '#';
        a.textContent = `${new Date(it.created_at * 1000).toLocaleString()}`;
        a.onclick = (e) => { e.preventDefault(); goToProgram('direct'); };
        li.appendChild(a);
        ul.appendChild(li);
      });
    }
  } catch {
    const err = document.createElement('div');
    err.className = 'error-block';
    err.textContent = t('unexpected_error');
    content.appendChild(err);
  } finally {
    content.removeAttribute('aria-busy');
  }
}
