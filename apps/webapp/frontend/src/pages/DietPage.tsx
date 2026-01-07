import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import TopBar from '../components/TopBar';
import BottomNav from '../components/BottomNav';
import { applyLang, t } from '../i18n/i18n';
import { getDietPlan, getDietPlans, HttpError } from '../api/http';
import { fmtDate } from '../ui/render_program';
import { readInitData, showBackButton, hideBackButton, onBackButtonClick, offBackButtonClick } from '../telegram';
import type { DietPlan, DietPlanSummary, Locale } from '../api/types';

const STATIC_PREFIX = ((window as any).__STATIC_PREFIX__ as string | undefined) ?? '/static/';
const fallbackIllustration =
    "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='360' height='260' viewBox='0 0 360 260' fill='none'><defs><linearGradient id='g1' x1='50' y1='30' x2='310' y2='210' gradientUnits='userSpaceOnUse'><stop stop-color='%23C7DFFF'/><stop offset='1' fill-opacity='0'/><stop offset='1' stop-color='%23E7EEFF'/></linearGradient><linearGradient id='g2' x1='120' y1='80' x2='240' y2='200' gradientUnits='userSpaceOnUse'><stop stop-color='%237AA7FF'/><stop offset='1' stop-color='%235B8BFF'/></linearGradient></defs><rect x='30' y='24' width='300' height='200' rx='28' fill='url(%23g1)'/><rect x='62' y='56' width='236' height='136' rx='18' fill='white' stroke='%23B8C7E6' stroke-width='3'/><path d='M90 174c18-30 42-30 60 0s42 30 60 0 42-30 60 0' stroke='%23A7B9DB' stroke-width='6' stroke-linecap='round' fill='none'/><circle cx='136' cy='106' r='16' fill='url(%23g2)'/><circle cx='216' cy='118' r='12' fill='%23E6ECFC'/><circle cx='248' cy='94' r='8' fill='%23E6ECFC'/></svg>";

const formatFloat = (value: number): string => {
    const fixed = value.toFixed(1);
    return fixed.replace(/\.0$/, '').replace(/\.$/, '');
};

const formatDietPlanText = (plan: DietPlan | null): string => {
    if (!plan) {
        return '';
    }
    const lines: string[] = [];
    plan.meals.forEach((meal) => {
        if (meal.name) {
            lines.push(meal.name);
        }
        meal.items.forEach((item) => {
            lines.push(`- ${item.name} — ${item.grams} ${t('diet.grams_unit')}`);
        });
        lines.push('');
    });
    if (plan.notes && plan.notes.length > 0) {
        lines.push('');
        lines.push(`${t('diet.notes')}:`);
        plan.notes.forEach((note) => {
            if (note) {
                lines.push(`- ${note}`);
            }
        });
    }
    while (lines.length > 0 && !lines[lines.length - 1].trim()) {
        lines.pop();
    }
    lines.push('');
    lines.push(`${t('diet.summary')}:`);
    lines.push(`${t('diet.calories')}: ${plan.totals.calories} ${t('diet.kcal_unit')}`);
    lines.push(`${t('diet.protein')}: ${formatFloat(plan.totals.protein_g)} ${t('diet.grams_unit')}`);
    lines.push(`${t('diet.fat')}: ${formatFloat(plan.totals.fat_g)} ${t('diet.grams_unit')}`);
    lines.push(`${t('diet.carbs')}: ${formatFloat(plan.totals.carbs_g)} ${t('diet.grams_unit')}`);
    return lines.join('\n');
};

const DietPage: React.FC = () => {
    const navigate = useNavigate();
    const [searchParams, setSearchParams] = useSearchParams();
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [diets, setDiets] = useState<DietPlanSummary[]>([]);
    const [detailPlan, setDetailPlan] = useState<DietPlan | null>(null);
    const [detailDate, setDetailDate] = useState<string | null>(null);
    const [detailLocale, setDetailLocale] = useState<Locale>('en');
    const [listLocale, setListLocale] = useState<Locale>('en');
    const [copyState, setCopyState] = useState<'idle' | 'done'>('idle');
    const [fabPressed, setFabPressed] = useState(false);

    const dietId = searchParams.get('diet_id') || '';
    const paramLang = searchParams.get('lang') || undefined;
    const initData = readInitData();

    useEffect(() => {
        void applyLang(paramLang);
    }, [paramLang]);

    useEffect(() => {
        const controller = new AbortController();
        let active = true;
        setLoading(true);
        setError(null);
        getDietPlans(initData, controller.signal)
            .then((data) => {
                if (!active) return;
                void applyLang(data.locale);
                setListLocale(data.locale);
                setDiets(data.diets);
            })
            .catch((err) => {
                if (!active) return;
                if (err instanceof HttpError) {
                    setError(t(err.message as any));
                    return;
                }
                setError(t('unexpected_error'));
            })
            .finally(() => {
                if (!active) return;
                setLoading(false);
            });
        return () => {
            active = false;
            controller.abort();
        };
    }, [initData]);

    useEffect(() => {
        if (!dietId) {
            setDetailPlan(null);
            setDetailDate(null);
            return;
        }
        const controller = new AbortController();
        let active = true;
        setError(null);
        getDietPlan(initData, dietId, controller.signal)
            .then((data) => {
                if (!active) return;
                void applyLang(data.locale);
                setDetailLocale(data.locale);
                setDetailPlan(data.plan ?? null);
                setDetailDate(data.createdAt ?? null);
            })
            .catch((err) => {
                if (!active) return;
                if (err instanceof HttpError) {
                    setError(t(err.message as any));
                    return;
                }
                setError(t('unexpected_error'));
            });
        return () => {
            active = false;
            controller.abort();
        };
    }, [dietId, initData]);

    const handleOpenDiet = useCallback(
        (id: number) => {
            try {
                const tg = (window as any).Telegram?.WebApp;
                tg?.HapticFeedback?.impactOccurred?.('light');
            } catch {
            }
            const params = new URLSearchParams(searchParams.toString());
            params.set('diet_id', String(id));
            setSearchParams(params);
        },
        [searchParams, setSearchParams]
    );

    const handleBack = useCallback(() => {
        const params = new URLSearchParams(searchParams.toString());
        params.delete('diet_id');
        setSearchParams(params);
    }, [searchParams, setSearchParams]);

    useEffect(() => {
        if (!dietId) {
            hideBackButton();
            offBackButtonClick(handleBack);
            return;
        }
        showBackButton();
        onBackButtonClick(handleBack);
        return () => {
            offBackButtonClick(handleBack);
            hideBackButton();
        };
    }, [dietId, handleBack]);

    const handleCreate = useCallback(() => {
        try {
            const tg = (window as any).Telegram?.WebApp;
            tg?.HapticFeedback?.impactOccurred?.('light');
        } catch {
        }
        const query = searchParams.toString();
        navigate(query ? `/diet-flow?${query}` : '/diet-flow');
    }, [navigate, searchParams]);

    const detailText = useMemo(() => formatDietPlanText(detailPlan), [detailPlan]);

    const handleCopy = useCallback(async () => {
        if (!detailText) return;
        try {
            await navigator.clipboard.writeText(detailText);
            setCopyState('done');
            const tg = (window as any).Telegram?.WebApp;
            tg?.HapticFeedback?.impactOccurred?.('light');
            window.setTimeout(() => setCopyState('idle'), 1400);
        } catch {
        }
    }, [detailText]);

    const fabStyle: React.CSSProperties = {
        position: 'fixed',
        bottom: 'calc(56px + var(--bottom-nav-offset, 0px))',
        right: 20,
        width: 68,
        height: 68,
        borderRadius: '50%',
        backgroundColor: 'var(--accent)',
        color: 'var(--accent-contrast)',
        border: 'none',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 38,
        boxShadow: '0 8px 16px rgba(0, 0, 0, 0.25)',
        zIndex: 1000,
        cursor: 'pointer',
        transform: fabPressed ? 'scale(0.94)' : 'scale(1)',
        transition: 'transform 120ms ease, box-shadow 120ms ease',
    };

    return (
        <div className="page-container with-bottom-nav">
            <TopBar title={dietId ? t('diet.detail.title') : t('diet.title')} onBack={dietId ? handleBack : undefined} />

            <div className="page-shell">
                {error && <div className="error-block">{error}</div>}
                <section className="diet-flow" data-view={dietId ? 'detail' : 'list'} aria-busy={loading}>
                    <div className="diet-flow__track">
                        <div className="diet-pane diet-pane--list">
                            <div className="diet-list" style={{ border: 'none' }}>
                                {loading && <div className="diet-empty">{t('workout_flow.loading')}</div>}
                                {!loading && diets.length === 0 && (
                                    <div className="empty-state history-empty">
                                        <img
                                            src={`${STATIC_PREFIX}images/404.png`}
                                            alt={t('diet.empty')}
                                            className="history-empty__image"
                                            onError={(ev) => {
                                                const target = ev.currentTarget;
                                                if (target.src !== fallbackIllustration) {
                                                    target.src = fallbackIllustration;
                                                }
                                            }}
                                        />
                                        <p className="history-empty__caption">{t('diet.empty')}</p>
                                    </div>
                                )}
                                {!loading && diets.length > 0 &&
                                    diets.map((diet) => (
                                        <button
                                            key={diet.id}
                                            type="button"
                                            className="diet-row"
                                            onClick={() => handleOpenDiet(diet.id)}
                                        >
                                            <div>
                                                <p className="diet-row__label">{t('diet.title')}</p>
                                                <p className="diet-row__value">
                                                    {t('diet.created', {
                                                        date: fmtDate(new Date(diet.created_at * 1000).toISOString(), listLocale),
                                                    })}
                                                </p>
                                            </div>
                                            <span className="diet-row__chevron" aria-hidden="true">
                                                <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                                                    <path
                                                        d="M7 10l5 5 5-5"
                                                        stroke="currentColor"
                                                        strokeWidth="1.6"
                                                        strokeLinecap="round"
                                                        strokeLinejoin="round"
                                                    />
                                                </svg>
                                            </span>
                                        </button>
                                    ))}
                            </div>
                        </div>

                        <div className="diet-pane diet-pane--detail">
                            <div className="diet-detail">
                                {detailPlan && (
                                    <>
                                        <button type="button" className="diet-copy" onClick={handleCopy}>
                                            {copyState === 'done' ? t('diet.copy.done') : t('diet.copy')}
                                        </button>
                                        {detailDate && (
                                            <div className="diet-date">{t('diet.created', { date: fmtDate(detailDate, detailLocale) })}</div>
                                        )}
                                        <pre className="diet-detail__text">{detailText}</pre>
                                    </>
                                )}
                            </div>
                        </div>
                    </div>
                </section>
            </div>

            {!dietId && (
                <button
                    type="button"
                    style={fabStyle}
                    aria-label={t('diet.flow.create')}
                    onClick={handleCreate}
                    onPointerDown={() => setFabPressed(true)}
                    onPointerUp={() => setFabPressed(false)}
                    onPointerLeave={() => setFabPressed(false)}
                >
                    +
                </button>
            )}
            <BottomNav activeKey="diets" />
        </div>
    );
};

export default DietPage;
