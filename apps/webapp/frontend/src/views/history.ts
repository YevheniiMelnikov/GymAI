import { API, getJSON, statusToMessage } from '../api/http';
import { HistoryResp, HistoryItem } from '../api/types';
import { applyLang, t, formatDate } from '../i18n/i18n';
import { createToggle } from '../ui/components';

const content = document.getElementById('content');
const controls = document.getElementById('controls');
const tg = (window as any).Telegram?.WebApp;
const initData: string = tg?.initData || '';
let showAI = true;
let items: HistoryItem[] = [];

function setText(txt: string): void {
  if (content) content.textContent = txt;
}

function render(): void {
  if (!content) return;
  content.innerHTML = '';
  const filtered = items.filter((p) => showAI || p.coach_type !== 'ai_coach');
  if (filtered.length === 0) {
    setText(t('no_programs'));
    return;
  }
  const list = document.createElement('ul');
  list.className = 'history-list';
  for (const p of filtered) {
    const li = document.createElement('li');
    const link = document.createElement('a');
    link.textContent = formatDate(p.created_at, document.documentElement.lang || 'en');
    link.href = '#';
    link.addEventListener('click', (e) => {
      e.preventDefault();
      const url = new URL(window.location.toString());
      url.searchParams.delete('page');
      url.searchParams.set('program_id', String(p.id));
      url.searchParams.delete('type');
      window.location.href = url.toString();
    });
    li.appendChild(link);
    if (p.coach_type === 'ai_coach') {
      const badge = document.createElement('span');
      badge.textContent = t('ai_label');
      badge.className = 'ai-label';
      li.appendChild(badge);
    }
    list.appendChild(li);
  }
  content.appendChild(list);
}

export async function renderHistory(): Promise<void> {
  if (!initData) {
    await applyLang('eng');
    setText(t('open_from_telegram'));
    return;
  }
  if (controls) {
    controls.innerHTML = '';
    const toggle = createToggle(true, (state) => {
      showAI = state;
      render();
    });
    controls.appendChild(toggle);
  }
  const q = new URLSearchParams();
  q.set('init_data', initData);
  const url = `${API.programs}?${q.toString()}`;
  const res = await getJSON<HistoryResp>(url);
  if (!res.ok) {
    setText(statusToMessage(res.status));
    return;
  }
  const data = res.data;
  await applyLang(data.language);
  if (data.error === 'service_unavailable') {
    setText(t('service_unavailable'));
    return;
  }
  items = (data.programs || []).sort((a, b) => b.created_at - a.created_at);
  render();
}
