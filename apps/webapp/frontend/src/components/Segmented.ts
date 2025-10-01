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
  let currentActive: SegmentId = active;

  const updateActiveState = (next: SegmentId): void => {
    currentActive = next;
    buttons.forEach((button) => {
      const isActive = button.dataset.tab === next;
      button.setAttribute('aria-selected', String(isActive));
      button.tabIndex = isActive ? 0 : -1;
      button.classList.toggle('is-active', isActive);
    });
  };

  SEGMENTS.forEach((id, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'segmented__tab';
    button.setAttribute('role', 'tab');
    button.dataset.tab = id;
    button.setAttribute('aria-selected', 'false');
    button.tabIndex = -1;

    const labelKey = id === 'program' ? 'tabs.program' : 'tabs.subscriptions';
    const updateLabel = (): void => {
      button.textContent = t(labelKey);
    };

    updateLabel();
    if (typeof queueMicrotask === 'function') {
      queueMicrotask(updateLabel);
    } else {
      void Promise.resolve().then(updateLabel);
    }

    button.addEventListener('click', () => {
      if (id !== currentActive) {
        updateActiveState(id);
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
        if (id !== currentActive) {
          updateActiveState(id);
          onChange(id);
        }
      }
    });

    buttons.push(button);
    wrapper.appendChild(button);
  });

  updateActiveState(currentActive);
  container.appendChild(wrapper);
}
