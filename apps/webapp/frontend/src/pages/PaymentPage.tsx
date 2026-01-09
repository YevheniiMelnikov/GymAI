import React, { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getPaymentData, HttpError, initPayment, PaymentData, PaymentInitData } from '../api/http';
import { applyLang, t, type TranslationKey } from '../i18n/i18n';
import { closeWebApp, openTelegramLink, readInitData, readPreferredLocale } from '../telegram';
import TopBar from '../components/TopBar';
import BottomNav from '../components/BottomNav';

type PaymentView = {
  checkoutUrl: string;
  amount: string;
  currency: string;
};

const PaymentPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const orderIdParam = searchParams.get('order_id') ?? searchParams.get('orderId');
  const packageIdParam = searchParams.get('package_id') ?? searchParams.get('packageId');

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [payment, setPayment] = useState<PaymentView | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const initData = readInitData();

    const fetchData = async () => {
      setLoading(true);
      setError(null);

      if (!orderIdParam && !packageIdParam) {
        setError(t('unexpected_error'));
        setLoading(false);
        return;
      }
      if (!initData) {
        setError(t('open_from_telegram'));
        setLoading(false);
        return;
      }

      try {
        let payload: PaymentData | PaymentInitData;
        if (orderIdParam) {
          payload = await getPaymentData(orderIdParam, initData, controller.signal);
        } else {
          payload = await initPayment(packageIdParam ?? '', initData, controller.signal);
        }
        const preferred = readPreferredLocale(payload.locale);
        await applyLang(preferred);
        setPayment({
          checkoutUrl: payload.checkoutUrl,
          amount: payload.amount,
          currency: payload.currency,
        });
      } catch (err) {
        const messageKey: TranslationKey = err instanceof HttpError ? (err.message as TranslationKey) : 'unexpected_error';
        setError(t(messageKey));
      } finally {
        setLoading(false);
      }
    };

    void fetchData();

    return () => {
      controller.abort();
    };
  }, [orderIdParam, packageIdParam]);

  const handleOpen = useCallback(() => {
    if (!payment) {
      return;
    }
    openTelegramLink(payment.checkoutUrl);
    closeWebApp();
  }, [payment]);

  return (
    <div className="page-container with-bottom-nav">
      <TopBar title={t('payment.title')} />
      <div className="page-shell">
        <section className="payment-card" aria-busy={loading}>
          <h2 className="payment-heading">{t('payment.title')}</h2>
          <p className="payment-amount">
            {payment
              ? t('payment.amount', { amount: payment.amount, currency: payment.currency })
              : t('payment.loading')}
          </p>
          {error && <p className="payment-note">{error}</p>}
          {!error && (
            <div className="payment-actions">
              <button type="button" className="primary-button" onClick={handleOpen} disabled={!payment}>
                {t('payment.open')}
              </button>
            </div>
          )}
        </section>
      </div>
      <BottomNav activeKey="profile" />
    </div>
  );
};

export default PaymentPage;
