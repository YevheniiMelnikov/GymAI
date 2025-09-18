import { API, getJSON, statusToMessage } from '../api/http';
import { HistoryItem, HistoryResp } from '../api/types';
import { applyLang, t } from '../i18n/i18n';
import { fmtDate } from '../ui/render_program';
import { goToProgram } from '../router';
import { createToggle } from '../ui/components';

const content = document.getElementById('content') as HTMLElement | null;
const historyButton = document.getElementById('history-button') as HTMLButtonElement | null;
const titleEl = document.getElementById('page-title') as HTMLElement | null;
const metaContainer = document.querySelector('.page-meta') as HTMLElement | null;
const dateChip = document.getElementById('program-date') as HTMLSpanElement | null;
const originChip = document.getElementById('program-origin') as HTMLSpanElement | null;

const tg = (window as any).Telegram?.WebApp;
const initData: string = tg?.initData || '';

let showAI = true;
let items: HistoryItem[] = [];

function setText(message: string): void {
  if (content) {
    content.textContent = message;
  }
}

function renderToolbar(): void {
  if (!content) return;
  const toolbar = document.createElement('div');
  toolbar.className = 'history-toolbar';
  const toggle = createToggle(showAI, (state) => {
    showAI = state;
    renderList();
  });
  toolbar.appendChild(toggle);
  content.appendChild(toolbar);
}

function renderList(): void {
  if (!content) return;
  content.innerHTML = '';
  renderToolbar();
  const filtered = items.filter((item) => showAI || item.coach_type !== 'ai_coach');
  if (filtered.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'history-empty';
    empty.textContent = t('no_programs');
    content.appendChild(empty);
    return;
  }
  const list = document.createElement('ul');
  list.className = 'history-list';
  const locale = document.documentElement.lang || 'en';
  for (const item of filtered) {
    const row = document.createElement('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'history-list__item';
    button.textContent = fmtDate(new Date(item.created_at * 1000).toISOString(), locale);
    button.addEventListener('click', () => {
      goToProgram(String(item.id));
    });
    row.appendChild(button);
    if (item.coach_type === 'ai_coach') {
      const badge = document.createElement('span');
      badge.textContent = t('ai_label');
      badge.className = 'ai-label';
      row.appendChild(badge);
    }
    list.appendChild(row);
  }
  content.appendChild(list);
}

function prepareHeader(): void {
  if (titleEl) {
    titleEl.textContent = t('history');
  }
  if (historyButton) {
    historyButton.textContent = t('program.view_history');
    historyButton.disabled = true;
    historyButton.classList.add('history-cta__button--disabled');
  }
  if (metaContainer) {
    metaContainer.classList.add('page-meta--hidden');
  }
  if (dateChip) {
    dateChip.textContent = '';
    dateChip.setAttribute('hidden', 'true');
  }
  if (originChip) {
    originChip.textContent = '';
    originChip.setAttribute('hidden', 'true');
  }
  document.title = t('history');
}

export async function renderHistory(): Promise<void> {
  if (!content) return;
  if (!initData) {
    await applyLang('eng');
    setText(t('open_from_telegram'));
    return;
  }
  content.setAttribute('aria-busy', 'true');
  const params = new URLSearchParams();
  params.set('init_data', initData);
  const res = await getJSON<HistoryResp>(`${API.programs}?${params.toString()}`);
  if (!res.ok) {
    content.removeAttribute('aria-busy');
    setText(statusToMessage(res.status));
    return;
  }
  const data = res.data;
  await applyLang(data.language);
  prepareHeader();
  content.removeAttribute('aria-busy');
  if (data.error === 'service_unavailable') {
    setText(t('service_unavailable'));
    return;
  }
  items = (data.programs ?? []).sort((a, b) => b.created_at - a.created_at);
  renderList();
}
