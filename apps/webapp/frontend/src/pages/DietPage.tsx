import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import TopBar from '../components/TopBar';
import BottomNav from '../components/BottomNav';
import LoadingSpinner from '../components/LoadingSpinner';
import ProgressBar from '../components/ProgressBar';
import { applyLang, useI18n } from '../i18n/i18n';
import { getDietPlan, getDietPlans, HttpError } from '../api/http';
import { fmtDate } from '../ui/render_program';
import {
    readInitData,
    readPreferredLocale,
    showBackButton,
    hideBackButton,
    onBackButtonClick,
    offBackButtonClick,
    tmeHapticImpact,
} from '../telegram';
import type { DietPlan, DietPlanSummary, Locale } from '../api/types';
import { useGenerationProgress } from '../hooks/useGenerationProgress';
import { triggerFavoriteAnimation } from '../utils/animations';
import { loadFavoriteIds, toggleFavoriteId } from '../utils/favorites';
import { waitForLatestDietId } from '../utils/diets';

const STATIC_PREFIX = ((window as any).__STATIC_PREFIX__ as string | undefined) ?? '/static/';
const STATIC_VERSION = ((window as any).__STATIC_VERSION__ as string | undefined) ?? '';
const fallbackIllustration =
    "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='360' height='260' viewBox='0 0 360 260' fill='none'><defs><linearGradient id='g1' x1='50' y1='30' x2='310' y2='210' gradientUnits='userSpaceOnUse'><stop stop-color='%23C7DFFF'/><stop offset='1' fill-opacity='0'/><stop offset='1' stop-color='%23E7EEFF'/></linearGradient><linearGradient id='g2' x1='120' y1='80' x2='240' y2='200' gradientUnits='userSpaceOnUse'><stop stop-color='%237AA7FF'/><stop offset='1' stop-color='%235B8BFF'/></linearGradient></defs><rect x='30' y='24' width='300' height='200' rx='28' fill='url(%23g1)'/><rect x='62' y='56' width='236' height='136' rx='18' fill='white' stroke='%23B8C7E6' stroke-width='3'/><path d='M90 174c18-30 42-30 60 0s42 30 60 0 42-30 60 0' stroke='%23A7B9DB' stroke-width='6' stroke-linecap='round' fill='none'/><circle cx='136' cy='106' r='16' fill='url(%23g2)'/><circle cx='216' cy='118' r='12' fill='%23E6ECFC'/><circle cx='248' cy='94' r='8' fill='%23E6ECFC'/></svg>";
const FAVORITES_KEY = 'diet_favorites';

const formatFloat = (value: number): string => {
    const fixed = value.toFixed(1);
    return fixed.replace(/\.0$/, '').replace(/\.$/, '');
};

const formatDietPlanText = (plan: DietPlan | null, t: any): string => {
    if (!plan) {
        return '';
    }
    const lines: string[] = [];
    plan.meals.forEach((meal) => {
        if (meal.name) {
            lines.push(meal.name);
        }
        meal.items.forEach((item) => {
            lines.push(`• ${item.name} — ${item.grams} ${t('diet.grams_unit')}`);
        });
        lines.push('');
    });
    if (plan.notes && plan.notes.length > 0) {
        lines.push('');
        lines.push(`${t('diet.notes')}:`);
        plan.notes.forEach((note) => {
            if (note) {
                lines.push(`• ${note}`);
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
    const { t } = useI18n();
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
    const [detailLoading, setDetailLoading] = useState(false);
    const [sortOrder, setSortOrder] = useState<'newest' | 'oldest'>('newest');
    const [showSavedOnly, setShowSavedOnly] = useState(false);
    const [isDropdownOpen, setIsDropdownOpen] = useState(false);
    const dropdownRef = useRef<HTMLDivElement>(null);
    const [favoriteIds, setFavoriteIds] = useState<Set<number>>(() => loadFavoriteIds(FAVORITES_KEY));
    const [shouldPulseFab, setShouldPulseFab] = useState(false);

    const [refreshKey, setRefreshKey] = useState(0);

    const progressHelper = useGenerationProgress('diet', (data: any) => {
        const query = searchParams.toString();
        const createdId = data?.result_id;
        if (createdId) {
            navigate(query ? `/diets?diet_id=${createdId}&${query}` : `/diets?diet_id=${createdId}`);
            return;
        }
        void (async () => {
            const latestId = await waitForLatestDietId(initData);
            if (latestId) {
                navigate(query ? `/diets?diet_id=${latestId}&${query}` : `/diets?diet_id=${latestId}`);
                return;
            }
            setRefreshKey(Date.now());
        })();
    });

    const dietId = searchParams.get('diet_id') || '';
    const paramLang = searchParams.get('lang') || undefined;
    const initData = readInitData();

    useEffect(() => {
        const preferred = readPreferredLocale(paramLang);
        void applyLang(preferred);
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
    }, [initData, refreshKey]);

    useEffect(() => {
        if (!dietId) {
            setDetailPlan(null);
            setDetailDate(null);
            setDetailLoading(false);
            return;
        }
        const controller = new AbortController();
        let active = true;
        setError(null);
        setDetailLoading(true);
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
            })
            .finally(() => {
                if (active) setDetailLoading(false);
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

    const detailText = useMemo(() => formatDietPlanText(detailPlan, t), [detailPlan, t]);
    const visibleDiets = useMemo(() => {
        const baseList = showSavedOnly ? diets.filter((diet) => favoriteIds.has(diet.id)) : diets;
        if (baseList.length === 0) return [];
        const sorted = [...baseList].sort((a, b) => {
            if (sortOrder === 'oldest') {
                return a.created_at - b.created_at;
            }
            return b.created_at - a.created_at;
        });
        return sorted;
    }, [diets, favoriteIds, showSavedOnly, sortOrder]);
    const canSort = diets.length > 1;
    const showControls = diets.length > 0;
    const isFavorite = dietId ? favoriteIds.has(Number(dietId)) : false;
    const isListEmpty = !loading && !progressHelper.isActive && visibleDiets.length === 0;
    const isEmptyList = isListEmpty && !dietId;
    const emptyCaption = showSavedOnly ? t('diet.saved_empty') : t('diet.empty');
    const emptyImageSrc = `${STATIC_PREFIX}images/404.png${STATIC_VERSION ? `?v=${STATIC_VERSION}` : ''}`;

    const handleToggleFavorite = useCallback(() => {
        if (!dietId) {
            return;
        }
        tmeHapticImpact('light');
        const numericId = Number(dietId);
        setFavoriteIds((prev) => toggleFavoriteId(FAVORITES_KEY, prev, numericId));
    }, [dietId]);

    const handleToggleFavoriteId = useCallback((id: number) => {
        tmeHapticImpact('light');
        setFavoriteIds((prev) => toggleFavoriteId(FAVORITES_KEY, prev, id));
    }, []);

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
                setIsDropdownOpen(false);
            }
        };
        const handleEscape = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setIsDropdownOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        document.addEventListener('keydown', handleEscape);
        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
            document.removeEventListener('keydown', handleEscape);
        };
    }, []);

    useEffect(() => {
        if (!canSort) {
            setIsDropdownOpen(false);
        }
    }, [canSort]);

    useEffect(() => {
        if (!isEmptyList || progressHelper.isActive) {
            return;
        }
        try {
            const seen = window.localStorage.getItem('diet_fab_pulse_seen');
            if (seen) {
                return;
            }
            window.localStorage.setItem('diet_fab_pulse_seen', '1');
            setShouldPulseFab(true);
        } catch {
            setShouldPulseFab(true);
        }
    }, [isEmptyList, progressHelper.isActive]);

    const handleCopy = useCallback(async () => {
        if (!detailText) return;
        try {
            await navigator.clipboard.writeText(detailText);
            setCopyState('done');
            tmeHapticImpact('light');
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

    const showProgress = progressHelper.isActive;

    return (
        <div className="page-container with-bottom-nav diet-page">
            <TopBar title={dietId ? t('diet.detail.title') : t('diet.title')} onBack={dietId ? handleBack : undefined} />

            <div className="page-shell">
                {showProgress ? (
                    <ProgressBar progress={progressHelper.progress} stage={progressHelper.stage} onClose={() => {}} />
                ) : (
                    <>
                        {error && <div className="error-block">{error}</div>}
                        {!dietId && showControls && (
                            <div className="history-controls" ref={dropdownRef}>
                                <div className="history-controls__filters">
                                    <label className="filter-toggle">
                                        <span
                                            className={`filter-toggle__icon${showSavedOnly ? ' filter-toggle__icon--active' : ''}`}
                                            aria-hidden="true"
                                        >
                                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                                                <path
                                                    d="M12 3.3l2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.9 6.8 19.3l1-5.8L3.6 9.4l5.8-.8L12 3.3Z"
                                                    stroke="currentColor"
                                                    strokeWidth="1.6"
                                                    strokeLinejoin="round"
                                                    fill="currentColor"
                                                />
                                            </svg>
                                        </span>
                                        <input
                                            type="checkbox"
                                            checked={showSavedOnly}
                                            onChange={(event) => setShowSavedOnly(event.target.checked)}
                                            aria-label={t('saved_label')}
                                        />
                                        <span className="filter-toggle__track" aria-hidden="true">
                                            <span className="filter-toggle__thumb" />
                                        </span>
                                        <span className="sr-only">{t('saved_label')}</span>
                                    </label>
                                </div>
                                <div className="sort-menu">
                                    <button
                                        type="button"
                                        className="sort-trigger"
                                        aria-haspopup="listbox"
                                        aria-expanded={isDropdownOpen}
                                        onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                                    >
                                        <span className="sort-trigger__icon" aria-hidden="true">
                                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                                                <path
                                                    d="M12 3L8.5 6.5H11V13h2V6.5h2.5L12 3Z"
                                                    stroke="currentColor"
                                                    strokeWidth="1.6"
                                                    strokeLinecap="round"
                                                    strokeLinejoin="round"
                                                    fill="none"
                                                />
                                                <path
                                                    d="M12 21l3.5-3.5H13V11h-2v6.5H8.5L12 21Z"
                                                    stroke="currentColor"
                                                    strokeWidth="1.6"
                                                    strokeLinecap="round"
                                                    strokeLinejoin="round"
                                                    fill="none"
                                                />
                                            </svg>
                                        </span>
                                        <span>{sortOrder === 'newest' ? t('sort_newest') : t('sort_oldest')}</span>
                                        <span className="sort-trigger__chevron" aria-hidden="true">
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

                                    {isDropdownOpen && (
                                        <div className="sort-dropdown" role="listbox">
                                            <button
                                                type="button"
                                                className={`sort-option ${sortOrder === 'newest' ? 'is-active' : ''}`}
                                                onClick={() => {
                                                    setSortOrder('newest');
                                                    setIsDropdownOpen(false);
                                                }}
                                            >
                                                {t('sort_newest')}
                                            </button>
                                            <button
                                                type="button"
                                                className={`sort-option ${sortOrder === 'oldest' ? 'is-active' : ''}`}
                                                onClick={() => {
                                                    setSortOrder('oldest');
                                                    setIsDropdownOpen(false);
                                                }}
                                            >
                                                {t('sort_oldest')}
                                            </button>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}
                        <section className="diet-flow" data-view={dietId ? 'detail' : 'list'} aria-busy={loading}>
                            <div className="diet-flow__track">
                                <div className="diet-pane diet-pane--list">
                                    <div className="diet-list" style={{ border: 'none' }}>
                                        {loading && <LoadingSpinner />}
                                        {isListEmpty && (
                                            <div className="empty-state history-empty">
                                                <img
                                                    src={emptyImageSrc}
                                                    alt={emptyCaption}
                                                    className="history-empty__image"
                                                    onError={(ev) => {
                                                        const target = ev.currentTarget;
                                                        if (target.src !== fallbackIllustration) {
                                                            target.src = fallbackIllustration;
                                                        }
                                                    }}
                                                />
                                                <p className="history-empty__caption">{emptyCaption}</p>
                                                <p className="history-empty__hint">{t('diet.empty_hint')}</p>
                                            </div>
                                        )}
                                        {!loading && visibleDiets.length > 0 &&
                                            visibleDiets.map((diet) => (
                                                <button
                                                    key={diet.id}
                                                    type="button"
                                                    className="diet-row"
                                                    onClick={() => handleOpenDiet(diet.id)}
                                                >
                                                    <div>
                                                        <p className="diet-row__value">
                                                            {t('diet.created', {
                                                                date: fmtDate(diet.created_at, listLocale),
                                                            })}
                                                        </p>
                                                    </div>
                                                    <span className="diet-row__actions">
                                                        <button
                                                            type="button"
                                                            className={`diet-row__favorite${favoriteIds.has(diet.id) ? ' is-active' : ''}`}
                                                            onClick={(event) => {
                                                                event.stopPropagation();
                                                                triggerFavoriteAnimation(event.currentTarget);
                                                                handleToggleFavoriteId(diet.id);
                                                            }}
                                                            aria-pressed={favoriteIds.has(diet.id)}
                                                            aria-label={t('saved_label')}
                                                            title={t('saved_label')}
                                                        >
                                                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                                                <path
                                                                    d="M12 3.3l2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.9 6.8 19.3l1-5.8L3.6 9.4l5.8-.8L12 3.3Z"
                                                                    stroke="currentColor"
                                                                    strokeWidth="1.6"
                                                                    strokeLinejoin="round"
                                                                    fill={favoriteIds.has(diet.id) ? 'currentColor' : 'none'}
                                                                />
                                                            </svg>
                                                        </button>
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
                                                    </span>
                                                </button>
                                            ))}
                                    </div>
                                </div>

                                <div className="diet-pane diet-pane--detail">
                                    <div className="diet-detail" aria-busy={detailLoading}>
                                        {detailLoading && !detailPlan && (
                                            <LoadingSpinner />
                                        )}
                                        {detailPlan && (
                                            <>
                                                <div className="diet-detail__actions">
                                                    <button
                                                        type="button"
                                                        className={`diet-favorite${isFavorite ? ' is-active' : ''}`}
                                                        onClick={(event) => {
                                                            triggerFavoriteAnimation(event.currentTarget);
                                                            handleToggleFavorite();
                                                        }}
                                                        aria-pressed={isFavorite}
                                                        aria-label={t('saved_label')}
                                                        title={t('saved_label')}
                                                    >
                                                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                                            <path
                                                                d="M12 3.3l2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.9 6.8 19.3l1-5.8L3.6 9.4l5.8-.8L12 3.3Z"
                                                                stroke="currentColor"
                                                                strokeWidth="1.6"
                                                                strokeLinejoin="round"
                                                                fill={isFavorite ? 'currentColor' : 'none'}
                                                            />
                                                        </svg>
                                                    </button>
                                                    <button
                                                        type="button"
                                                        className="diet-copy"
                                                        onClick={handleCopy}
                                                        aria-label={copyState === 'done' ? t('diet.copy.done') : t('diet.copy')}
                                                        title={copyState === 'done' ? t('diet.copy.done') : t('diet.copy')}
                                                    >
                                                        {copyState === 'done' ? (
                                                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                                                <path
                                                                    d="M20 6L9 17l-5-5"
                                                                    stroke="currentColor"
                                                                    strokeWidth="2"
                                                                    strokeLinecap="round"
                                                                    strokeLinejoin="round"
                                                                />
                                                            </svg>
                                                        ) : (
                                                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                                                <rect
                                                                    x="9"
                                                                    y="9"
                                                                    width="10"
                                                                    height="10"
                                                                    rx="2"
                                                                    stroke="currentColor"
                                                                    strokeWidth="1.6"
                                                                />
                                                                <path
                                                                    d="M6 15H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1"
                                                                    stroke="currentColor"
                                                                    strokeWidth="1.6"
                                                                    strokeLinecap="round"
                                                                    strokeLinejoin="round"
                                                                />
                                                            </svg>
                                                        )}
                                                    </button>
                                                </div>
                                                {detailDate && (
                                                    <div className="diet-date">{t('diet.created', { date: fmtDate(detailDate, detailLocale) })}</div>
                                                )}
                                                <div className="diet-detail__content">
                                                    {detailPlan.meals.map((meal, mealIndex) => (
                                                        <div key={`${mealIndex}-${meal.name ?? 'meal'}`} className="diet-detail__section">
                                                            {meal.name && (
                                                                <h4 className="diet-detail__title">{meal.name}</h4>
                                                            )}
                                                            <ul className="diet-detail__list">
                                                                {meal.items.map((item, itemIndex) => (
                                                                    <li key={`${mealIndex}-${itemIndex}`}>
                                                                        {item.name} — {item.grams} {t('diet.grams_unit')}
                                                                    </li>
                                                                ))}
                                                            </ul>
                                                        </div>
                                                    ))}
                                                    {detailPlan.notes && detailPlan.notes.length > 0 && (
                                                        <div className="diet-detail__section">
                                                            <h4 className="diet-detail__title">{t('diet.notes')}</h4>
                                                            <ul className="diet-detail__list">
                                                                {detailPlan.notes.filter(Boolean).map((note, noteIndex) => (
                                                                    <li key={`note-${noteIndex}`}>{note}</li>
                                                                ))}
                                                            </ul>
                                                        </div>
                                                    )}
                                                    <div className="diet-summary">
                                                        <div className="diet-summary__title">{t('diet.summary')}</div>
                                                        <table className="diet-summary__table">
                                                            <tbody>
                                                                <tr>
                                                                    <th scope="row">{t('diet.calories')}</th>
                                                                    <td>{detailPlan.totals.calories} {t('diet.kcal_unit')}</td>
                                                                </tr>
                                                                <tr>
                                                                    <th scope="row">{t('diet.protein')}</th>
                                                                    <td>{formatFloat(detailPlan.totals.protein_g)} {t('diet.grams_unit')}</td>
                                                                </tr>
                                                                <tr>
                                                                    <th scope="row">{t('diet.fat')}</th>
                                                                    <td>{formatFloat(detailPlan.totals.fat_g)} {t('diet.grams_unit')}</td>
                                                                </tr>
                                                                <tr>
                                                                    <th scope="row">{t('diet.carbs')}</th>
                                                                    <td>{formatFloat(detailPlan.totals.carbs_g)} {t('diet.grams_unit')}</td>
                                                                </tr>
                                                            </tbody>
                                                        </table>
                                                    </div>
                                                </div>
                                            </>
                                        )}
                                    </div>
                                </div>
                            </div>
                        </section>
                    </>
                )}
            </div>

            {!dietId && !progressHelper.isActive && (
                <button
                    type="button"
                    style={fabStyle}
                    className={shouldPulseFab ? 'fab-button--pulse' : undefined}
                    aria-label={t('diet.flow.create')}
                    onClick={handleCreate}
                    onPointerDown={() => setFabPressed(true)}
                    onPointerUp={() => setFabPressed(false)}
                    onPointerLeave={() => setFabPressed(false)}
                    onAnimationEnd={() => setShouldPulseFab(false)}
                >
                    +
                </button>
            )}
            <BottomNav activeKey="diets" />
        </div>
    );
};

export default DietPage;
