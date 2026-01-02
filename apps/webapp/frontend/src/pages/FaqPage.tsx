import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import TopBar from '../components/TopBar';
import BottomNav from '../components/BottomNav';
import { applyLang, t } from '../i18n/i18n';
import {
    closeWebApp,
    openTelegramLink,
    readInitData,
    readLocale,
    showBackButton,
    hideBackButton,
    onBackButtonClick,
    offBackButtonClick,
} from '../telegram';
import { getSupportContact } from '../api/http';
import type { LangCode, TranslationKey } from '../i18n/i18n';

type FaqAnswer =
    | {
          kind: 'single';
          answerKey: TranslationKey;
      }
    | {
          kind: 'double';
          firstLabelKey: TranslationKey;
          firstBodyKey: TranslationKey;
          secondLabelKey: TranslationKey;
          secondBodyKey: TranslationKey;
      };

type FaqItem = {
    id: string;
    questionKey: TranslationKey;
    answer: FaqAnswer;
};

const FAQ_ITEMS: FaqItem[] = [
    {
        id: 'program-subscription',
        questionKey: 'faq.q1.question',
        answer: {
            kind: 'double',
            firstLabelKey: 'faq.q1.program.label',
            firstBodyKey: 'faq.q1.program.body',
            secondLabelKey: 'faq.q1.subscription.label',
            secondBodyKey: 'faq.q1.subscription.body'
        }
    },
    {
        id: 'exercise-replace',
        questionKey: 'faq.q2.question',
        answer: {
            kind: 'single',
            answerKey: 'faq.q2.answer'
        }
    },
    {
        id: 'goals-experience',
        questionKey: 'faq.q3.question',
        answer: {
            kind: 'single',
            answerKey: 'faq.q3.answer'
        }
    },
    {
        id: 'payment',
        questionKey: 'faq.q4.question',
        answer: {
            kind: 'single',
            answerKey: 'faq.q4.answer'
        }
    },
    {
        id: 'ai-trust',
        questionKey: 'faq.q5.question',
        answer: {
            kind: 'single',
            answerKey: 'faq.q5.answer'
        }
    },
    {
        id: 'difference',
        questionKey: 'faq.q6.question',
        answer: {
            kind: 'single',
            answerKey: 'faq.q6.answer'
        }
    }
];

const FaqPage: React.FC = () => {
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const [lang, setLang] = useState<LangCode>('en');
    const [supportUrl, setSupportUrl] = useState<string>('');
    const paramLang = searchParams.get('lang') || undefined;

    const handleBack = useCallback(() => {
        closeWebApp();
        navigate(-1);
    }, [navigate]);

    useEffect(() => {
        void applyLang(paramLang ?? readLocale()).then((resolved) => setLang(resolved));
    }, [paramLang]);

    useEffect(() => {
        const controller = new AbortController();
        const initData = readInitData();
        const fetchSupport = async () => {
            try {
                const data = await getSupportContact(initData, controller.signal);
                setSupportUrl(data.url || '');
            } catch {
            }
        };
        fetchSupport();
        return () => controller.abort();
    }, []);

    useEffect(() => {
        showBackButton();
        onBackButtonClick(handleBack);
        return () => {
            offBackButtonClick(handleBack);
            hideBackButton();
        };
    }, [handleBack]);

    const renderAnswer = (answer: FaqAnswer): React.ReactNode => {
        if (answer.kind === 'single') {
            return <p>{t(answer.answerKey)}</p>;
        }
        return (
            <>
                <p>
                    <strong>{t(answer.firstLabelKey)}</strong> {t(answer.firstBodyKey)}
                </p>
                <p>
                    <strong>{t(answer.secondLabelKey)}</strong> {t(answer.secondBodyKey)}
                </p>
            </>
        );
    };

    return (
        <div className="page-container with-bottom-nav" data-lang={lang}>
            <TopBar title={t('faq.title')} />
            <main className="page-shell">
                <section className="program-panel">
                    <div className="week">
                        {FAQ_ITEMS.map((item) => (
                            <details className="program-day" key={item.id}>
                                <summary className="program-day-summary">{t(item.questionKey)}</summary>
                                <div className="program-day-list faq-answer">{renderAnswer(item.answer)}</div>
                            </details>
                        ))}
                    </div>
                </section>
                {supportUrl && (
                    <div className="faq-support">
                        <button
                            type="button"
                            className="primary-button faq-support__button"
                            onClick={() => {
                                openTelegramLink(supportUrl);
                                closeWebApp();
                            }}
                        >
                            {t('faq.support')}
                        </button>
                    </div>
                )}
            </main>
            <BottomNav />
        </div>
    );
};

export default FaqPage;
