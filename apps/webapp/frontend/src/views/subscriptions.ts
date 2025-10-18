import { t } from '../i18n/i18n';
import { tmeReady } from '../telegram';

export async function renderSubscriptions(root: HTMLElement): Promise<void> {
  root.innerHTML = '';

  const container = document.createElement('section');
  container.style.display = 'flex';
  container.style.flexDirection = 'column';
  container.style.alignItems = 'center';
  container.style.justifyContent = 'center';
  container.style.gap = '12px';
  container.style.padding = 'clamp(28px, 4vw, 40px)';
  container.style.minHeight = '40vh';
  container.style.textAlign = 'center';

  const heading = document.createElement('h2');
  heading.textContent = t('subscriptions.title');
  heading.style.margin = '0';

  const description = document.createElement('p');
  description.textContent = t('subscriptions.empty');
  description.style.margin = '0';
  description.style.color = 'var(--muted)';
  description.style.fontSize = '15px';
  description.style.maxWidth = '320px';

  container.append(heading, description);
  root.appendChild(container);
  tmeReady();
}
