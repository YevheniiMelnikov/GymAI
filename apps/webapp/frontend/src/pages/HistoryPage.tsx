import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { renderSegmented, SegmentId } from '../components/Segmented';
import TopBar from '../components/TopBar';
import BottomNav from '../components/BottomNav';
import LoadingSpinner from '../components/LoadingSpinner';
import { applyLang, t } from '../i18n/i18n';
import {
    readInitData,
    readPreferredLocale,
    showBackButton,
    hideBackButton,
    onBackButtonClick,
    offBackButtonClick,
    tmeHapticImpact,
} from '../telegram';
import type { HistoryItem, HistoryResp, Locale } from '../api/types';
import { getProgram, getSubscription, HttpError } from '../api/http';
import { fmtDate, renderLegacyProgram, renderProgramDays, setProgramContext } from '../ui/render_program';
import { loadFavoriteIds, toggleFavoriteId } from '../utils/favorites';

const STATIC_PREFIX = ((window as any).__STATIC_PREFIX__ as string | undefined) ?? '/static/';
const STATIC_VERSION = ((window as any).__STATIC_VERSION__ as string | undefined) ?? '';

async function getHistory(locale: Locale): Promise<HistoryResp> {
    const headers: Record<string, string> = {};
    const initData = readInitData();
    if (initData) headers['X-Telegram-InitData'] = initData;
    // We need to construct the URL correctly.
    // Since we are in a SPA, window.location.href might be different.
    // But the API endpoint is relative to the root usually.
    // The original code used new URL('api/programs/', window.location.href).
    // We can just use '/api/programs/'.
    const url = new URL('/api/programs/', window.location.origin);
    url.searchParams.set('locale', locale);
    const resp = await fetch(url.toString(), { headers });
    if (!resp.ok) throw new Error('unexpected_error');
    return (await resp.json()) as HistoryResp;
}

const HistoryPage: React.FC = () => {
    const PROGRAM_FAVORITES_KEY = 'history_favorites_programs';
    const SUBSCRIPTION_FAVORITES_KEY = 'history_favorites_subscriptions';
    const navigate = useNavigate();
    const [searchParams, setSearchParams] = useSearchParams();
    const switcherRef = useRef<HTMLDivElement>(null);
    const detailRef = useRef<HTMLDivElement>(null);
    const fallbackIllustration =
        "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='360' height='260' viewBox='0 0 360 260' fill='none'><defs><linearGradient id='g1' x1='50' y1='30' x2='310' y2='210' gradientUnits='userSpaceOnUse'><stop stop-color='%23C7DFFF'/><stop offset='1' stop-color='%23E7EEFF'/></linearGradient><linearGradient id='g2' x1='120' y1='80' x2='240' y2='200' gradientUnits='userSpaceOnUse'><stop stop-color='%237AA7FF'/><stop offset='1' stop-color='%235B8BFF'/></linearGradient></defs><rect x='30' y='24' width='300' height='200' rx='28' fill='url(%23g1)'/><rect x='62' y='56' width='236' height='136' rx='18' fill='white' stroke='%23B8C7E6' stroke-width='3'/><path d='M90 174c18-30 42-30 60 0s42 30 60 0 42-30 60 0' stroke='%23A7B9DB' stroke-width='6' stroke-linecap='round' fill='none'/><circle cx='136' cy='106' r='16' fill='url(%23g2)'/><circle cx='216' cy='118' r='12' fill='%23E6ECFC'/><circle cx='248' cy='94' r='8' fill='%23E6ECFC'/></svg>";
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [data, setData] = useState<HistoryResp | null>(null);
    const [listLocale, setListLocale] = useState<Locale>('en');
    const [sortOrder, setSortOrder] = useState<'newest' | 'oldest'>('newest');
    const [showSavedOnly, setShowSavedOnly] = useState(false);
    const [isDropdownOpen, setIsDropdownOpen] = useState(false);
    const [detailLoading, setDetailLoading] = useState(false);
    const [detailError, setDetailError] = useState<string | null>(null);
    const [detailLocale, setDetailLocale] = useState<Locale>('en');
    const [detailDate, setDetailDate] = useState<string | number | null>(null);
    const [programFavorites, setProgramFavorites] = useState<Set<number>>(() => loadFavoriteIds(PROGRAM_FAVORITES_KEY));
    const [subscriptionFavorites, setSubscriptionFavorites] = useState<Set<number>>(
        () => loadFavoriteIds(SUBSCRIPTION_FAVORITES_KEY)
    );
    const [activeSegment, setActiveSegment] = useState<SegmentId>(() => {
        const segment = searchParams.get('segment');
        if (segment === 'subscriptions') {
            return 'subscriptions';
        }
        return 'program';
    });
    const dropdownRef = useRef<HTMLDivElement>(null);
    const paramLang = searchParams.get('lang') || undefined;
    const programId = searchParams.get('program_id') || searchParams.get('id') || '';
    const subscriptionId = searchParams.get('subscription_id') || '';
    const detailId = activeSegment === 'subscriptions' ? subscriptionId : programId;
    const detailOpen = Boolean(detailId);
    const activeItems = useMemo<HistoryItem[]>(
        () => (activeSegment === 'subscriptions' ? data?.subscriptions : data?.programs) ?? [],
        [activeSegment, data]
    );
    const activeFavorites = activeSegment === 'subscriptions' ? subscriptionFavorites : programFavorites;
    const canSort = activeItems.length > 1;
    const showControls = activeItems.length > 0 && !detailOpen;

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
        if (switcherRef.current) {
            return renderSegmented(switcherRef.current, activeSegment, (next) => {
                try {
                    const tg = (window as any).Telegram?.WebApp;
                    tg?.HapticFeedback?.impactOccurred('light');
                } catch {
                }
                setActiveSegment(next);
            });
        }
    }, []);

    useEffect(() => {
        const params = new URLSearchParams(searchParams.toString());
        if (activeSegment === 'program' && params.get('subscription_id')) {
            params.delete('subscription_id');
            params.delete('source');
            setSearchParams(params, { replace: true });
        }
        if (activeSegment === 'subscriptions' && (params.get('program_id') || params.get('id'))) {
            params.delete('program_id');
            params.delete('id');
            setSearchParams(params, { replace: true });
        }
    }, [activeSegment, searchParams, setSearchParams]);

    const clearDetail = useCallback(() => {
        const params = new URLSearchParams(searchParams.toString());
        params.delete('program_id');
        params.delete('id');
        params.delete('subscription_id');
        params.delete('source');
        setSearchParams(params);
    }, [searchParams, setSearchParams]);

    const handleBack = useCallback(() => {
        if (detailOpen) {
            clearDetail();
            return;
        }
        if (window.history.length > 1) {
            navigate(-1);
            return;
        }
        navigate('/');
    }, [clearDetail, detailOpen, navigate]);

    useEffect(() => {
        showBackButton();
        onBackButtonClick(handleBack);
        return () => {
            offBackButtonClick(handleBack);
            hideBackButton();
        };
    }, [handleBack]);

    useEffect(() => {
        const fetchData = async () => {
            setLoading(true);
            setError(null);
            try {
                const requestLocale = readPreferredLocale(paramLang);
                const historyData = await getHistory(requestLocale);
                const appliedLang = await applyLang(historyData.language ?? requestLocale);
                setListLocale(appliedLang);
                setData(historyData);
            } catch {
                setError(t('unexpected_error'));
            } finally {
                setLoading(false);
            }
        };
        fetchData();
    }, []);

    const visibleItems = useMemo(() => {
        const baseList = showSavedOnly ? activeItems.filter((item) => activeFavorites.has(item.id)) : activeItems;
        if (baseList.length === 0) {
            return [];
        }
        return [...baseList].sort((a, b) => {
            if (sortOrder === 'oldest') {
                return a.created_at - b.created_at;
            }
            return b.created_at - a.created_at;
        });
    }, [activeFavorites, activeItems, showSavedOnly, sortOrder]);
    const detailNumericId = detailId ? Number(detailId) : Number.NaN;
    const canFavoriteDetail = Number.isFinite(detailNumericId);
    const isDetailFavorite = canFavoriteDetail ? activeFavorites.has(detailNumericId) : false;

    const handleToggleFavorite = useCallback(
        (id: number) => {
            tmeHapticImpact('light');
            if (activeSegment === 'subscriptions') {
                setSubscriptionFavorites((prev) => toggleFavoriteId(SUBSCRIPTION_FAVORITES_KEY, prev, id));
                return;
            }
            setProgramFavorites((prev) => toggleFavoriteId(PROGRAM_FAVORITES_KEY, prev, id));
        },
        [activeSegment]
    );

    const handleProgramClick = (id: number) => {
        const params = new URLSearchParams(searchParams.toString());
        params.set('program_id', String(id));
        params.delete('subscription_id');
        params.delete('source');
        setSearchParams(params);
    };

    const handleSubscriptionClick = (id: number) => {
        const params = new URLSearchParams(searchParams.toString());
        params.set('subscription_id', String(id));
        params.delete('program_id');
        params.delete('id');
        params.set('source', 'subscription');
        setSearchParams(params);
    };

    useEffect(() => {
        if (!detailOpen) {
            setDetailLoading(false);
            setDetailError(null);
            setDetailDate(null);
            if (detailRef.current) {
                detailRef.current.innerHTML = '';
            }
            setProgramContext(null, null);
            return;
        }
        const initData = readInitData();
        if (!initData) {
            setDetailError(t('open_from_telegram'));
            setDetailLoading(false);
            return;
        }

        const controller = new AbortController();
        let active = true;
        setDetailLoading(true);
        setDetailError(null);
        if (detailRef.current) {
            detailRef.current.innerHTML = '';
        }
        setProgramContext(null, null);

        const renderProgram = (program: any) => {
            if (!detailRef.current) {
                return;
            }
            detailRef.current.innerHTML = '';
            const { fragment } = renderProgramDays(program);
            detailRef.current.appendChild(fragment);
            setProgramContext(String(program.id || detailId), activeSegment === 'subscriptions' ? 'subscription' : 'direct');
        };

        const renderLegacy = (text: string, locale: Locale) => {
            if (!detailRef.current) {
                return;
            }
            detailRef.current.innerHTML = '';
            const { fragment } = renderLegacyProgram(text, locale);
            detailRef.current.appendChild(fragment);
            setProgramContext(null, null);
        };

        const fetchDetail = async () => {
            try {
                if (activeSegment === 'program') {
                    const load = await getProgram(detailId, { initData, source: 'direct', signal: controller.signal });
                    const applied = await applyLang(load.locale);
                    if (!active) {
                        return;
                    }
                    if (load.kind === 'structured') {
                        console.info('history.detail.program', { id: detailId, days: load.program.days.length });
                    } else {
                        console.info('history.detail.legacy', { id: detailId, length: load.programText.length });
                    }
                    setDetailLocale(applied);
                    if (load.kind === 'structured') {
                        setDetailDate(load.program.created_at ?? null);
                        renderProgram(load.program);
                    } else {
                        setDetailDate(load.createdAt ?? null);
                        renderLegacy(load.programText, applied);
                    }
                    return;
                }

                const sub = await getSubscription(initData, detailId, controller.signal);
                const applied = await applyLang(sub.language ?? paramLang ?? listLocale);
                if (!active) {
                    return;
                }
                console.info('history.detail.subscription', {
                    id: detailId,
                    days: Array.isArray(sub.days) ? sub.days.length : null,
                    programLength: typeof sub.program === 'string' ? sub.program.length : null
                });
                setDetailLocale(applied);
                setDetailDate(sub.created_at ?? null);
                if (Array.isArray(sub.days) && sub.days.length > 0) {
                    renderProgram(
                        {
                            id: String(sub.id ?? detailId),
                            locale: applied,
                            created_at: sub.created_at ?? null,
                            days: sub.days,
                        },
                    );
                } else if (sub.program) {
                    renderLegacy(sub.program, applied);
                } else {
                    throw new Error('not_found');
                }
            } catch (err) {
                if (!active) {
                    return;
                }
                const messageKey = err instanceof HttpError ? (err.message as any) : ('unexpected_error' as any);
                setDetailError(t(messageKey));
            } finally {
                if (active) {
                    setDetailLoading(false);
                }
            }
        };

        fetchDetail();

        return () => {
            active = false;
            controller.abort();
        };
    }, [activeSegment, detailId, detailOpen, listLocale, paramLang, t]);

    return (
        <div className="page-container with-bottom-nav history-page">
            <TopBar title={t('page.history')} onBack={handleBack} />

            <div className="page-shell">
                <div id="content" aria-busy={loading}>
                    <div className="history-panel">
                        <div ref={switcherRef} id="segmented" className="segmented-container" />

                        {showControls && (
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

                        {error && <div className="error-block">{error}</div>}

                        <section className="diet-flow" data-view={detailOpen ? 'detail' : 'list'} aria-busy={loading}>
                            <div className="diet-flow__track">
                                <div className="diet-pane diet-pane--list">
                                    <div className="diet-list" style={{ border: 'none' }}>
                                        {loading && <LoadingSpinner />}
                                        {!loading && !error && visibleItems.length === 0 && (
                                            <div className="empty-state history-empty">
                                                <img
                                                    src={`${STATIC_PREFIX}images/404.png${STATIC_VERSION ? `?v=${STATIC_VERSION}` : ''}`}
                                                    alt={
                                                        showSavedOnly
                                                            ? activeSegment === 'subscriptions'
                                                                ? t('subscriptions.saved_empty')
                                                                : t('program.saved_empty')
                                                            : activeSegment === 'subscriptions'
                                                                ? t('subscriptions.title')
                                                                : t('no_programs')
                                                    }
                                                    className="history-empty__image"
                                                    onError={(ev) => {
                                                        const target = ev.currentTarget;
                                                        if (target.src !== fallbackIllustration) {
                                                            target.src = fallbackIllustration;
                                                        }
                                                    }}
                                                />
                                                <p className="history-empty__caption">
                                                    {showSavedOnly
                                                        ? activeSegment === 'subscriptions'
                                                            ? t('subscriptions.saved_empty')
                                                            : t('program.saved_empty')
                                                        : activeSegment === 'subscriptions'
                                                            ? t('subscriptions.empty')
                                                            : t('no_programs')}
                                                </p>
                                            </div>
                                        )}
                                        {!loading && !error && visibleItems.length > 0 && visibleItems.map((it) => (
                                            <button
                                                key={it.id}
                                                type="button"
                                                className="diet-row"
                                                onClick={() => {
                                                    if (activeSegment === 'subscriptions') {
                                                        handleSubscriptionClick(it.id);
                                                    } else {
                                                        handleProgramClick(it.id);
                                                    }
                                                }}
                                            >
                                                <div>
                                                    <p className="diet-row__value">
                                                        {t('program.created', { date: fmtDate(it.created_at, listLocale) })}
                                                    </p>
                                                </div>
                                                <span className="diet-row__actions">
                                                    <button
                                                        type="button"
                                                        className={`diet-row__favorite${activeFavorites.has(it.id) ? ' is-active' : ''}`}
                                                        onClick={(event) => {
                                                            event.stopPropagation();
                                                            handleToggleFavorite(it.id);
                                                        }}
                                                        aria-pressed={activeFavorites.has(it.id)}
                                                        aria-label={t('saved_label')}
                                                        title={t('saved_label')}
                                                    >
                                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                                            <path
                                                                d="M12 3.3l2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.9 6.8 19.3l1-5.8L3.6 9.4l5.8-.8L12 3.3Z"
                                                                stroke="currentColor"
                                                                strokeWidth="1.6"
                                                                strokeLinejoin="round"
                                                                fill={activeFavorites.has(it.id) ? 'currentColor' : 'none'}
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
                                        {detailLoading && <LoadingSpinner />}
                                        {detailError && <div className="error-block">{detailError}</div>}
                                        {detailOpen && !detailError && (
                                            <div className="history-detail">
                                                <div className="history-detail__meta">
                                                    {canFavoriteDetail && (
                                                        <button
                                                            type="button"
                                                            className={`diet-favorite${isDetailFavorite ? ' is-active' : ''}`}
                                                            onClick={() => handleToggleFavorite(detailNumericId)}
                                                            aria-pressed={isDetailFavorite}
                                                            aria-label={t('saved_label')}
                                                            title={t('saved_label')}
                                                        >
                                                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                                                <path
                                                                    d="M12 3.3l2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.9 6.8 19.3l1-5.8L3.6 9.4l5.8-.8L12 3.3Z"
                                                                    stroke="currentColor"
                                                                    strokeWidth="1.6"
                                                                    strokeLinejoin="round"
                                                                    fill={isDetailFavorite ? 'currentColor' : 'none'}
                                                                />
                                                            </svg>
                                                        </button>
                                                    )}
                                                    {detailDate && (
                                                        <div className="diet-date">
                                                            {t('program.created', { date: fmtDate(detailDate, detailLocale) })}
                                                        </div>
                                                    )}
                                                </div>
                                                <div ref={detailRef} className="history-detail__content" />
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </div>
                        </section>
                    </div>
                </div>
            </div>
            <BottomNav />
        </div>
    );
};

export default HistoryPage;
