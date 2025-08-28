import { API, getJSON, statusToMessage } from '../api/http';
import { ProgramResp, SubscriptionResp } from '../api/types';
import { applyLang, t, formatDate } from '../i18n/i18n';
import { renderProgram } from '../ui/render_program';
import { createButton } from '../ui/components';

const content = document.getElementById('content');
const dateEl = document.getElementById('program-date');
const originEl = document.getElementById('program-origin');
const controls = document.getElementById('controls');
const tg = (window as any).Telegram?.WebApp;
const initData: string = tg?.initData || '';

function setText(txt: string): void {
  if (content) content.textContent = txt;
}

function renderProgramControls(): void {
  if (!controls) return;
  controls.innerHTML = '';
  const btn = createButton(t('history'), () => {
    const url = new URL(window.location.toString());
    url.searchParams.set('page', 'history');
    url.searchParams.delete('program_id');
    url.searchParams.delete('type');
    window.location.href = url.toString();
  });
  controls.appendChild(btn);
}

export async function renderProgramView(id?: string, type?: 'subscription'): Promise<void> {
  if (!initData) {
    await applyLang('eng');
    setText(t('open_from_telegram'));
    return;
  }

  let message: string | null = null;
  const q = new URLSearchParams();
  q.set('init_data', initData);
  if (id) q.set('program_id', id);

  const url =
    type === 'subscription'
      ? `${API.subscription}?${q.toString()}`
      : `${API.program}?${q.toString()}`;

  const res = await getJSON<ProgramResp | SubscriptionResp>(url);

  if (!res.ok) {
    message = statusToMessage(res.status);
  } else {
    const data = res.data as ProgramResp | SubscriptionResp;
    await applyLang((data as any).language);
    if ((data as any).error === 'service_unavailable') {
      message = t('service_unavailable');
    } else {
      renderProgram((data as any).program || '');
      if ('created_at' in data && data.created_at && dateEl) {
        const ts = Number(data.created_at);
        dateEl.textContent = Number.isFinite(ts)
          ? `${t('created')}: ${formatDate(ts, document.documentElement.lang || 'en')}`
          : '';
      }
      if ('coach_type' in data && originEl) {
        if (data.coach_type === 'ai_coach') {
          originEl.textContent = t('ai_label');
          originEl.className = 'ai-label';
        } else {
          originEl.textContent = '';
          originEl.className = '';
        }
      }
    }
  }

  if (message) {
    setText(message);
    if (dateEl) dateEl.textContent = '';
    if (originEl) {
      originEl.textContent = '';
      originEl.className = '';
    }
  }

  renderProgramControls();
}
