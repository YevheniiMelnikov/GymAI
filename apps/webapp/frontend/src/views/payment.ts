import { getPaymentData, HttpError } from '../api/http';
import { applyLang, t } from '../i18n/i18n';
import { readInitData, tmeReady } from '../telegram';

type PaymentCtx = {
  root: HTMLElement;
  content: HTMLElement;
  dateEl: HTMLElement;
  titleEl?: HTMLElement | null;
};

type Cleanup = () => void;

const LIQPAY_SCRIPT_ID = 'liqpay-checkout-script';
const LIQPAY_SCRIPT_SRC = 'https://static.liqpay.ua/libjs/checkout.js';

let liqpayLoader: Promise<void> | null = null;

function setBusy(node: HTMLElement, busy: boolean) {
  if (busy) node.setAttribute('aria-busy', 'true');
  else node.removeAttribute('aria-busy');
}

function loadCheckoutScript(): Promise<void> {
  if (typeof (window as any).LiqPayCheckout !== 'undefined') {
    return Promise.resolve();
  }
  if (liqpayLoader) {
    return liqpayLoader;
  }
  liqpayLoader = new Promise((resolve, reject) => {
    const existing = document.getElementById(LIQPAY_SCRIPT_ID);
    if (existing) {
      existing.addEventListener('load', () => resolve());
      existing.addEventListener('error', () => reject(new Error('liqpay_unavailable')));
      return;
    }
    const script = document.createElement('script');
    script.id = LIQPAY_SCRIPT_ID;
    script.src = LIQPAY_SCRIPT_SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('liqpay_unavailable'));
    document.head.appendChild(script);
  });
  return liqpayLoader;
}

function mountCheckout(container: HTMLElement, data: string, signature: string): void {
  const checkout = (window as any).LiqPayCheckout;
  if (!checkout || typeof checkout.init !== 'function') {
    throw new Error('liqpay_unavailable');
  }
  checkout
    .init({
      data,
      signature,
      embedTo: `#${container.id}`,
      mode: 'embed',
    })
    ?.on('liqpay.ready', () => {
      container.removeAttribute('aria-busy');
      tmeReady();
    })
    ?.on('liqpay.close', () => {
      container.setAttribute('aria-busy', 'true');
    });
}

export async function renderPayment(ctx: PaymentCtx, orderId: string | null): Promise<Cleanup> {
  const { content, dateEl, titleEl } = ctx;
  const initData = readInitData();
  const controller = new AbortController();

  content.innerHTML = '';
  setBusy(content, true);
  dateEl.hidden = true;
  dateEl.textContent = '';
  if (titleEl) {
    titleEl.textContent = t('payment.title');
  }

  const card = document.createElement('section');
  card.className = 'payment-card';

  const heading = document.createElement('h2');
  heading.textContent = t('payment.title');
  heading.className = 'payment-heading';

  const amountEl = document.createElement('p');
  amountEl.className = 'payment-amount';
  amountEl.textContent = t('payment.loading');

  const noteEl = document.createElement('p');
  noteEl.className = 'payment-note';
  noteEl.textContent = t('payment.launch');

  const checkoutContainer = document.createElement('div');
  checkoutContainer.id = 'liqpay-checkout';
  checkoutContainer.className = 'payment-frame';
  checkoutContainer.setAttribute('aria-busy', 'true');

  const actions = document.createElement('div');
  actions.className = 'payment-actions';

  const openBtn = document.createElement('a');
  openBtn.className = 'primary-button';
  openBtn.target = '_blank';
  openBtn.rel = 'noreferrer noopener';
  openBtn.textContent = t('payment.open');
  openBtn.style.display = 'none';
  actions.appendChild(openBtn);

  card.append(heading, amountEl, noteEl, checkoutContainer, actions);
  content.appendChild(card);

  const cleanup: Cleanup = () => controller.abort();

  try {
    if (!orderId) {
      throw new HttpError(400, 'bad_request');
    }
    const payment = await getPaymentData(orderId, initData, controller.signal);
    await applyLang(payment.locale);
    if (titleEl) {
      titleEl.textContent = t('payment.title');
    }
    heading.textContent = t('payment.title');
    noteEl.textContent = t('payment.launch');
    openBtn.textContent = t('payment.open');

    amountEl.textContent = t('payment.amount', { amount: payment.amount, currency: payment.currency });
    noteEl.textContent = t('payment.launch');
    openBtn.href = payment.checkoutUrl;
    openBtn.style.display = 'block';

    await loadCheckoutScript();
    mountCheckout(checkoutContainer, payment.data, payment.signature);
  } catch (error) {
    if (controller.signal.aborted) {
      return cleanup;
    }
    let key = 'unexpected_error';
    if (error instanceof HttpError) {
      key = error.message;
    } else if (error instanceof Error && error.message === 'liqpay_unavailable') {
      key = 'payment.unavailable';
    }
    noteEl.textContent = t(key as Parameters<typeof t>[0]);
    checkoutContainer.remove();
  } finally {
    setBusy(content, false);
  }

  return cleanup;
}
