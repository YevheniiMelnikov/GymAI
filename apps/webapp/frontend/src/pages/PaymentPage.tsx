import React, { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { getPaymentData, HttpError } from '../api/http';
import { applyLang, t } from '../i18n/i18n';
import { readInitData, tmeReady } from '../telegram';

const LIQPAY_SCRIPT_ID = 'liqpay-checkout-script';
const LIQPAY_SCRIPT_SRC = 'https://static.liqpay.ua/libjs/checkout.js';

let liqpayLoader: Promise<void> | null = null;

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

const PaymentPage: React.FC = () => {
    const [searchParams] = useSearchParams();
    const orderId = searchParams.get('order_id');
    const checkoutRef = useRef<HTMLDivElement>(null);

    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [paymentData, setPaymentData] = useState<{ amount: string; currency: string; checkoutUrl: string } | null>(null);

    useEffect(() => {
        const controller = new AbortController();
        const initData = readInitData();

        const fetchData = async () => {
            setLoading(true);
            setError(null);

            if (!orderId) {
                setError(t('unexpected_error')); // Or bad request
                setLoading(false);
                return;
            }

            try {
                const payment = await getPaymentData(orderId, initData, controller.signal);
                await applyLang(payment.locale);

                setPaymentData({
                    amount: payment.amount,
                    currency: payment.currency,
                    checkoutUrl: payment.checkoutUrl,
                });

                await loadCheckoutScript();
                if (checkoutRef.current) {
                    mountCheckout(checkoutRef.current, payment.data, payment.signature);
                }
            } catch (e) {
                if (controller.signal.aborted) return;

                let key = 'unexpected_error';
                if (e instanceof HttpError) {
                    key = e.message;
                } else if (e instanceof Error && e.message === 'liqpay_unavailable') {
                    key = 'payment.unavailable';
                }
                setError(t(key as any));
            } finally {
                setLoading(false);
            }
        };

        fetchData();

        return () => {
            controller.abort();
        };
    }, [orderId]);

    return (
        <div className="page-container">
            <h1 id="page-title">{t('payment.title')}</h1>

            <div id="content" aria-busy={loading}>
                <section className="payment-card">
                    <h2 className="payment-heading">{t('payment.title')}</h2>

                    <p className="payment-amount">
                        {paymentData
                            ? t('payment.amount', { amount: paymentData.amount, currency: paymentData.currency })
                            : t('payment.loading')}
                    </p>

                    <p className="payment-note">
                        {error ? error : t('payment.launch')}
                    </p>

                    {!error && (
                        <div
                            id="liqpay-checkout"
                            className="payment-frame"
                            ref={checkoutRef}
                            aria-busy="true"
                        />
                    )}

                    <div className="payment-actions">
                        {paymentData && (
                            <a
                                className="primary-button"
                                target="_blank"
                                rel="noreferrer noopener"
                                href={paymentData.checkoutUrl}
                                style={{ display: 'block' }}
                            >
                                {t('payment.open')}
                            </a>
                        )}
                    </div>
                </section>
            </div>
        </div>
    );
};

export default PaymentPage;
