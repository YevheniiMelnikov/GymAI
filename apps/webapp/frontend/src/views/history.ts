import { applyLang, t } from '../i18n/i18n';
import type { HistoryResp, Locale } from '../api/types';
import { goToProgram } from '../router';
import { readInitData, readLocale } from '../telegram';

const content = document.getElementById('content') as HTMLElement | null;
const dateChip = document.getElementById('program-date') as HTMLDivElement | null;

async function getHistory(locale: Locale): Promise<HistoryResp> {
  const headers: Record<string, string> = {};
  const initData = readInitData();
  if (initData) headers['X-Telegram-InitData'] = initData;
  const url = new URL('api/programs/', window.location.href);
  url.searchParams.set('locale', locale);
  const resp = await fetch(url.toString(), { headers });
  if (!resp.ok) throw new Error('unexpected_error');
  return (await resp.json()) as HistoryResp;
}

export async function renderHistoryView(titleEl?: HTMLElement | null): Promise<void> {
  if (!content) return;
  content.setAttribute('aria-busy', 'true');
  content.innerHTML = '';

  if (dateChip) dateChip.hidden = true;

  if (titleEl) {
    titleEl.textContent = t('page.history');
  }

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
    const requestLocale = readLocale();
    const data = await getHistory(requestLocale);
    const lang = await applyLang(data.language ?? requestLocale);

    if (titleEl) {
      titleEl.textContent = t('page.history');
    }

    const resolveSource = (): 'direct' | 'subscription' => {
      const raw = new URL(window.location.href).searchParams.get('source');
      return raw === 'subscription' ? 'subscription' : 'direct';
    };

    h2.textContent = t('history');

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
        a.textContent = new Date(it.created_at * 1000).toLocaleString(lang);
        a.onclick = (e) => {
          e.preventDefault();
          const url = new URL(window.location.href);
          url.searchParams.set('id', String(it.id));
          history.replaceState({}, '', url.toString());
          goToProgram('direct');
        };
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
