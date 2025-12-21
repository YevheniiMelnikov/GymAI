import React, { useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import TopBar from '../components/TopBar';
import { applyLang, t } from '../i18n/i18n';
import { closeWebApp, readLocale, showBackButton, hideBackButton, onBackButtonClick, offBackButtonClick } from '../telegram';

const FaqPage: React.FC = () => {
    const navigate = useNavigate();

    const handleBack = useCallback(() => {
        closeWebApp();
        navigate(-1);
    }, [navigate]);

    useEffect(() => {
        applyLang(readLocale());
    }, []);

    useEffect(() => {
        showBackButton();
        onBackButtonClick(handleBack);
        return () => {
            offBackButtonClick(handleBack);
            hideBackButton();
        };
    }, [handleBack]);

    return (
        <div className="page-container">
            <TopBar title={t('faq.title')} onBack={handleBack} />
            <main className="page-shell">
                <section className="notice">
                    <h2>{t('faq.placeholder.title')}</h2>
                    <p>{t('faq.placeholder.body')}</p>
                </section>
            </main>
        </div>
    );
};

export default FaqPage;
