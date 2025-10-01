import { t } from '../i18n/i18n';

export type SegmentId = 'program' | 'subscriptions';
export type SegmentChangeHandler = (next: SegmentId) => void;

const SEGMENTS: SegmentId[] = ['program', 'subscriptions'];

export function renderSegmented(
  container: HTMLElement,
  active: SegmentId,
  onChange: SegmentChangeHandler
): void {
  container.innerHTML = '';

  const wrapper = document.createElement('div');
  wrapper.className = 'segmented';
  wrapper.setAttribute('role', 'tablist');
  wrapper.setAttribute('aria-label', t('tabs.switch_label'));

  const buttons: HTMLButtonElement[] = [];

  SEGMENTS.forEach((id, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'segmented__tab';
    button.setAttribute('role', 'tab');

    const isActive = id === active;
    button.setAttribute('aria-selected', String(isActive));
    button.tabIndex = isActive ? 0 : -1;
    button.textContent = t(id === 'program' ? 'tabs.program' : 'tabs.subscriptions');

    button.addEventListener('click', () => {
      if (id !== active) {
        onChange(id);
      }
    });

    button.addEventListener('keydown', (event: KeyboardEvent) => {
      if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
        event.preventDefault();
        const direction = event.key === 'ArrowRight' ? 1 : -1;
        const nextIndex = (index + direction + SEGMENTS.length) % SEGMENTS.length;
        buttons[nextIndex].focus();
        return;
      }

      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        if (id !== active) {
          onChange(id);
        }
      }
    });

    buttons.push(button);
    wrapper.appendChild(button);
  });

  container.appendChild(wrapper);
}
