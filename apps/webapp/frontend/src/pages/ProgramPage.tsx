import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
    getProgram,
    getSubscription,
    getSubscriptionStatus,
    HttpError,
    WorkoutAction
} from '../api/http';
import { applyLang, useI18n } from '../i18n/i18n';
import {
    EXERCISE_EDIT_SAVED_EVENT,
    EXERCISE_TECHNIQUE_EVENT,
    fmtDate,
    renderLegacyProgram,
    renderProgramDays,
    setProgramContext,
} from '../ui/render_program';
import { readInitData, readPreferredLocale, tmeHapticImpact, tmeReady } from '../telegram';
import type { Locale, Program } from '../api/types';
import { renderSegmented, SegmentId } from '../components/Segmented';
import TopBar from '../components/TopBar';
import BottomNav from '../components/BottomNav';
import LoadingSpinner from '../components/LoadingSpinner';
import { triggerFavoriteAnimation } from '../utils/animations';
import { loadFavoriteIds, toggleFavoriteId } from '../utils/favorites';
import { useGenerationProgress } from '../hooks/useGenerationProgress';

const LAST_WORKOUT_SEGMENT_KEY = 'gymbot.workouts.lastSegment';
const INTRO_SEEN_KEY = 'gymbot.webapp.introSeen';

const readLastWorkoutSegment = (): SegmentId => {
    if (typeof window === 'undefined') {
        return 'program';
    }
    try {
        const stored = window.localStorage.getItem(LAST_WORKOUT_SEGMENT_KEY);
        if (stored === 'subscriptions') {
            return 'subscriptions';
        }
    } catch {
        // ignore
    }
    return 'program';
};

const storeLastWorkoutSegment = (segment: SegmentId): void => {
    if (typeof window === 'undefined') {
        return;
    }
    try {
        window.localStorage.setItem(LAST_WORKOUT_SEGMENT_KEY, segment);
    } catch {
        // ignore
    }
};

const ProgramPage: React.FC = () => {
    const PROGRAM_FAVORITES_KEY = 'history_favorites_programs';
    const SUBSCRIPTION_FAVORITES_KEY = 'history_favorites_subscriptions';
    const navigate = useNavigate();
    const { t } = useI18n();
    const [searchParams, setSearchParams] = useSearchParams();
    const searchParamsKey = searchParams.toString();
    const contentRef = useRef<HTMLDivElement>(null);
    const switcherRef = useRef<HTMLDivElement>(null);
    const fallbackIllustration =
        "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='360' height='260' viewBox='0 0 360 260' fill='none'><defs><linearGradient id='g1' x1='50' y1='30' x2='310' y2='210' gradientUnits='userSpaceOnUse'><stop stop-color='%23C7DFFF'/><stop offset='1' stop-color='%23E7EEFF'/></linearGradient><linearGradient id='g2' x1='120' y1='80' x2='240' y2='200' gradientUnits='userSpaceOnUse'><stop stop-color='%237AA7FF'/><stop offset='1' stop-color='%235B8BFF'/></linearGradient></defs><rect x='30' y='24' width='300' height='200' rx='28' fill='url(%23g1)'/><rect x='62' y='56' width='236' height='136' rx='18' fill='white' stroke='%23B8C7E6' stroke-width='3'/><path d='M90 174c18-30 42-30 60 0s42 30 60 0 42-30 60 0' stroke='%23A7B9DB' stroke-width='6' stroke-linecap='round' fill='none'/><circle cx='136' cy='106' r='16' fill='url(%23g2)'/><circle cx='216' cy='118' r='12' fill='%23E6ECFC'/><circle cx='248' cy='94' r='8' fill='%23E6ECFC'/></svg>";
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [actionLoading, setActionLoading] = useState(false);
    const [fabPressed, setFabPressed] = useState(false);
    const [shouldPulseFab, setShouldPulseFab] = useState(false);
    const [isEmptyState, setIsEmptyState] = useState(false);
    const [isExerciseEditOpen, setIsExerciseEditOpen] = useState(false);
    const [isTechniqueOpen, setIsTechniqueOpen] = useState(false);
    const [refreshKey, setRefreshKey] = useState(0);
    const [dateText, setDateText] = useState('');
    const [showSubscriptionConfirm, setShowSubscriptionConfirm] = useState(false);
    const [showIntro, setShowIntro] = useState(false);
    const [currentItemId, setCurrentItemId] = useState<number | null>(null);
    const [programFavorites, setProgramFavorites] = useState<Set<number>>(() => loadFavoriteIds(PROGRAM_FAVORITES_KEY));
    const [subscriptionFavorites, setSubscriptionFavorites] = useState<Set<number>>(
        () => loadFavoriteIds(SUBSCRIPTION_FAVORITES_KEY)
    );
    const [activeSegment, setActiveSegment] = useState<SegmentId>(() => {
        const source = searchParams.get('source');
        if (source === 'subscription') {
            return 'subscriptions';
        }
        return readLastWorkoutSegment();
    });

    const progressHelper = useGenerationProgress('workout', () => {
        setRefreshKey(Date.now());
    });

    const programId = searchParams.get('program_id') || searchParams.get('id') || '';
    const paramLang = searchParams.get('lang') || undefined;
    const isSubscriptionView = activeSegment === 'subscriptions';
    const activeFavorites = isSubscriptionView ? subscriptionFavorites : programFavorites;
    const isCurrentFavorite = currentItemId !== null ? activeFavorites.has(currentItemId) : false;

    useEffect(() => {
        const preferred = readPreferredLocale(paramLang);
        void applyLang(preferred);
    }, [paramLang]);

    const prevSourceRef = useRef(searchParams.get('source'));

    useEffect(() => {
        const params = new URLSearchParams(searchParamsKey);
        const sourceParam = params.get('source');
        if (sourceParam === 'subscription') {
            if (activeSegment !== 'subscriptions') {
                setActiveSegment('subscriptions');
            }
        } else if (prevSourceRef.current === 'subscription' && sourceParam !== 'subscription') {
            if (activeSegment !== 'program') {
                setActiveSegment('program');
            }
        }
        prevSourceRef.current = sourceParam;
    }, [searchParamsKey, activeSegment]);

    useEffect(() => {
        storeLastWorkoutSegment(activeSegment);
    }, [activeSegment]);

    useEffect(() => {
        const handleEditDialog = (event: Event) => {
            const detail = (event as CustomEvent<{ open?: boolean }>).detail;
            setIsExerciseEditOpen(Boolean(detail?.open));
        };
        window.addEventListener('exercise-edit-dialog', handleEditDialog);
        return () => {
            window.removeEventListener('exercise-edit-dialog', handleEditDialog);
        };
    }, []);

    useEffect(() => {
        const handleTechniqueDialog = (event: Event) => {
            const detail = (event as CustomEvent<{ open?: boolean }>).detail;
            setIsTechniqueOpen(Boolean(detail?.open));
        };
        window.addEventListener(EXERCISE_TECHNIQUE_EVENT, handleTechniqueDialog);
        return () => {
            window.removeEventListener(EXERCISE_TECHNIQUE_EVENT, handleTechniqueDialog);
        };
    }, []);

    useEffect(() => {
        const handleSaved = () => {
            setRefreshKey(Date.now());
        };
        window.addEventListener(EXERCISE_EDIT_SAVED_EVENT, handleSaved);
        return () => {
            window.removeEventListener(EXERCISE_EDIT_SAVED_EVENT, handleSaved);
        };
    }, []);

    useEffect(() => {
        if (!switcherRef.current) return;
        return renderSegmented(switcherRef.current, activeSegment, (next) => {
            try {
                const tg = (window as any).Telegram?.WebApp;
                tg?.HapticFeedback?.impactOccurred('light');
            } catch {
            }
            setActiveSegment(next);
            const nextParams = new URLSearchParams(searchParamsKey);
            if (next === 'subscriptions') {
                nextParams.set('source', 'subscription');
            } else {
                nextParams.delete('source');
            }
            setSearchParams(nextParams, { replace: true });
        });
    }, [activeSegment, searchParamsKey, setSearchParams]);

    useEffect(() => {
        const controller = new AbortController();
        const initData = readInitData();

        const fetchData = async () => {
            setLoading(true);
            setError(null);
            setIsEmptyState(false);
            setDateText('');
            setCurrentItemId(null);
            if (contentRef.current) contentRef.current.innerHTML = '';

            try {
                let appliedLocale: Locale = 'en';
                let programData: Program | null = null;
                let legacyText: string | null = null;
                let createdAt: string | null = null;

                if (activeSegment === 'program') {
                    const load = await getProgram(programId, { initData, source: 'direct', signal: controller.signal });
                    appliedLocale = await applyLang(load.locale || paramLang);

                    if (load.kind === 'structured') {
                        programData = load.program;
                        if (programData.id) {
                            const numericId = Number(programData.id);
                            if (Number.isFinite(numericId)) {
                                setCurrentItemId(numericId);
                            }
                        }
                    } else {
                        legacyText = load.programText;
                        createdAt = load.createdAt ?? null;
                        if (programId) {
                            const numericId = Number(programId);
                            if (Number.isFinite(numericId)) {
                                setCurrentItemId(numericId);
                            }
                        }
                    }
                } else {
                    // Subscriptions
                    const subscriptionId = searchParams.get('subscription_id') || '';
                    const sub = await getSubscription(initData, subscriptionId, controller.signal);
                    appliedLocale = await applyLang(sub.language || paramLang);

                    if (sub.days) {
                        programData = {
                            id: sub.id || 'sub',
                            locale: appliedLocale,
                            created_at: sub.created_at ?? null,
                            days: sub.days
                        };
                        if (sub.id) {
                            const numericId = Number(sub.id);
                            if (Number.isFinite(numericId)) {
                                setCurrentItemId(numericId);
                            }
                        }
                    } else if (sub.program) {
                        legacyText = sub.program;
                        if (subscriptionId) {
                            const numericId = Number(subscriptionId);
                            if (Number.isFinite(numericId)) {
                                setCurrentItemId(numericId);
                            }
                        }
                    } else {
                        throw new Error('no_programs');
                    }
                }

                // Render content
                if (contentRef.current) {
                    contentRef.current.innerHTML = '';
                    if (programData) {
                        setProgramContext(
                            programData.id ? String(programData.id) : null,
                            activeSegment === 'program' ? 'direct' : 'subscription'
                        );
                        if (programData.created_at) {
                            setDateText(t('program.created', { date: fmtDate(programData.created_at, appliedLocale) }));
                        }
                        const { fragment } = renderProgramDays(programData);
                        contentRef.current.appendChild(fragment);
                    } else if (legacyText) {
                        setProgramContext(null, null);
                        if (createdAt) {
                            setDateText(t('program.created', { date: fmtDate(createdAt, appliedLocale) }));
                        }
                        const { fragment } = renderLegacyProgram(legacyText, appliedLocale);
                        contentRef.current.appendChild(fragment);
                    }
                }
                tmeReady();
            } catch (e) {
                let key = 'unexpected_error';
                if (e instanceof HttpError) {
                    if (e.status === 404) {
                        key = activeSegment === 'subscriptions' ? 'subscriptions.empty' : 'no_programs';
                    } else {
                        key = e.message;
                    }
                } else if (e instanceof Error && e.message === 'no_programs') {
                    key = 'subscriptions.empty';
                }
                setIsEmptyState(key === 'no_programs' || key === 'subscriptions.empty');
                setError(t(key as any));
            } finally {
                setLoading(false);
            }
        };

        fetchData();

        return () => {
            controller.abort();
        };
    }, [programId, activeSegment, paramLang, refreshKey]);

    const navigateToFlow = useCallback(
        (plan: 'program' | 'subscription') => {
            const nextParams = new URLSearchParams(searchParamsKey);
            nextParams.delete('id');
            nextParams.delete('subscription_id');
            nextParams.delete('source');
            nextParams.set('plan', plan);
            const query = nextParams.toString();
            navigate(query ? `/workout-flow?${query}` : '/workout-flow');
        },
        [navigate, searchParamsKey]
    );

    const creationAction: WorkoutAction | null =
        activeSegment === 'program'
            ? 'create_program'
            : activeSegment === 'subscriptions'
                ? 'create_subscription'
                : null;

    useEffect(() => {
        if (!isEmptyState || !creationAction || progressHelper.isActive) {
            return;
        }
        try {
            const seen = window.localStorage.getItem('workout_fab_pulse_seen');
            if (seen) {
                return;
            }
            window.localStorage.setItem('workout_fab_pulse_seen', '1');
            setShouldPulseFab(true);
        } catch {
            setShouldPulseFab(true);
        }
    }, [isEmptyState, creationAction, progressHelper.isActive]);

    const handleFabClick = useCallback(async () => {
        if (!creationAction) {
            return;
        }
        const tg = (window as any).Telegram?.WebApp;
        try {
            tg?.HapticFeedback?.impactOccurred('medium');
        } catch {
        }
        if (creationAction === 'create_subscription') {
            const initData = readInitData();
            if (!initData) {
                window.alert(t('open_from_telegram'));
                return;
            }
            setActionLoading(true);
            try {
                const status = await getSubscriptionStatus(initData);
                if (status.active) {
                    setShowSubscriptionConfirm(true);
                    return;
                }
            } catch (err) {
                console.error('subscription_status_failed', err);
                window.alert(t('program.action_error'));
                return;
            } finally {
                setActionLoading(false);
            }
        }
        navigateToFlow(creationAction === 'create_program' ? 'program' : 'subscription');
    }, [creationAction, navigateToFlow]);

    const handleSubscriptionConfirm = useCallback(async () => {
        setShowSubscriptionConfirm(false);
        navigateToFlow('subscription');
    }, [navigateToFlow]);

    const handleSubscriptionCancel = useCallback(() => {
        setShowSubscriptionConfirm(false);
    }, []);

    useEffect(() => {
        let existing: string | null = null;
        try {
            existing = window.localStorage.getItem(INTRO_SEEN_KEY);
        } catch {
            return;
        }
        if (existing) {
            return;
        }
        const initData = readInitData();
        if (!initData) {
            return;
        }
        const controller = new AbortController();
        let active = true;

        const checkEmptyState = async () => {
            try {
                const locale = readPreferredLocale(paramLang);
                const url = new URL('/api/programs/', window.location.origin);
                url.searchParams.set('locale', locale);
                const headers: Record<string, string> = { 'X-Telegram-InitData': initData };
                const resp = await fetch(url.toString(), { headers, signal: controller.signal });
                if (!resp.ok) {
                    return;
                }
                const data = (await resp.json()) as { programs?: unknown[]; subscriptions?: unknown[] };
                const programs = Array.isArray(data.programs) ? data.programs : [];
                const subscriptions = Array.isArray(data.subscriptions) ? data.subscriptions : [];
                if (active && programs.length === 0 && subscriptions.length === 0) {
                    setShowIntro(true);
                }
            } catch {
            }
        };

        void checkEmptyState();
        return () => {
            active = false;
            controller.abort();
        };
    }, []);

    const handleIntroClose = useCallback(() => {
        try {
            window.localStorage.setItem(INTRO_SEEN_KEY, '1');
        } catch {
        }
        setShowIntro(false);
    }, []);

    const handleToggleFavorite = useCallback(() => {
        if (currentItemId === null) {
            return;
        }
        tmeHapticImpact('light');
        if (activeSegment === 'subscriptions') {
            setSubscriptionFavorites((prev) => toggleFavoriteId(SUBSCRIPTION_FAVORITES_KEY, prev, currentItemId));
            return;
        }
        setProgramFavorites((prev) => toggleFavoriteId(PROGRAM_FAVORITES_KEY, prev, currentItemId));
    }, [activeSegment, currentItemId]);

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
            <TopBar title={t('program.title')} />

            <div className="page-shell">
                <>
                    <div id="content" aria-busy={loading}>
                        <div className="history-panel program-panel">
                            <div ref={switcherRef} id="segmented" className="segmented-container" />

                                {(currentItemId !== null || dateText) && (
                                    <div className="program-meta">
                                        {currentItemId !== null && (
                                            <button
                                                type="button"
                                                className={`diet-favorite${isCurrentFavorite ? ' is-active' : ''}`}
                                                onClick={(event) => {
                                                    triggerFavoriteAnimation(event.currentTarget);
                                                    handleToggleFavorite();
                                                }}
                                                aria-pressed={isCurrentFavorite}
                                                aria-label={t('saved_label')}
                                                title={t('saved_label')}
                                            >
                                                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                                    <path
                                                        d="M12 3.3l2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.9 6.8 19.3l1-5.8L3.6 9.4l5.8-.8L12 3.3Z"
                                                        stroke="currentColor"
                                                        strokeWidth="1.6"
                                                        strokeLinejoin="round"
                                                        fill={isCurrentFavorite ? 'currentColor' : 'none'}
                                                    />
                                                </svg>
                                            </button>
                                        )}
                                        {dateText && <div className="diet-date">{dateText}</div>}
                                    </div>
                                )}

                                <div ref={contentRef} className="week centered" />

                                {loading && <LoadingSpinner />}
                                {error && (
                                    <div className="empty-state history-empty">
                                        <img
                                            src="/static/images/404.png"
                                            alt={t('no_programs')}
                                            className="history-empty__image"
                                            onError={(ev) => {
                                                const target = ev.currentTarget;
                                                if (target.src !== fallbackIllustration) {
                                                    target.src = fallbackIllustration;
                                                }
                                            }}
                                        />
                                        <p className="history-empty__caption">{error}</p>
                                        {isEmptyState && (
                                            <p className="history-empty__hint">{t('program.empty_hint')}</p>
                                        )}
                                    </div>
                                )}
                            </div>
                        </div>

                        <div className="history-footer" />
                </>
            </div>
            {creationAction && !isExerciseEditOpen && !isTechniqueOpen && !progressHelper.isActive && (
                <button
                    type="button"
                    style={fabStyle}
                    className={shouldPulseFab ? 'fab-button--pulse' : undefined}
                    aria-label={t('program.create_new')}
                    onClick={handleFabClick}
                    onPointerDown={() => setFabPressed(true)}
                    onPointerUp={() => setFabPressed(false)}
                    onPointerLeave={() => setFabPressed(false)}
                    disabled={actionLoading}
                    onAnimationEnd={() => setShouldPulseFab(false)}
                >
                    +
                </button>
            )}
            {showSubscriptionConfirm && (
                <div role="dialog" aria-modal="true" className="subscription-confirm">
                    <div className="subscription-confirm__dialog">
                        <h3 className="subscription-confirm__title">{t('subscriptions.replace_confirm.title')}</h3>
                        <p className="subscription-confirm__body">{t('subscriptions.replace_confirm.body')}</p>
                        <div className="subscription-confirm__actions">
                            <button
                                type="button"
                                onClick={handleSubscriptionCancel}
                                className="subscription-confirm__btn subscription-confirm__btn--cancel"
                            >
                                {t('subscriptions.replace_confirm.cancel')}
                            </button>
                            <button
                                type="button"
                                onClick={handleSubscriptionConfirm}
                                className="subscription-confirm__btn subscription-confirm__btn--confirm"
                            >
                                {t('subscriptions.replace_confirm.confirm')}
                            </button>
                        </div>
                    </div>
                </div>
            )}
            {showIntro && (
                <div
                    role="dialog"
                    aria-modal="true"
                    className="intro-modal"
                    onClick={handleIntroClose}
                >
                    <div
                        className="intro-modal__dialog"
                        onClick={(event) => {
                            event.stopPropagation();
                        }}
                    >
                        <h3 className="intro-modal__title">{t('intro.title')}</h3>
                        <p className="intro-modal__text">
                            {t('intro.program')}
                        </p>
                        <p className="intro-modal__text">
                            {t('intro.subscription')}
                        </p>
                        <button type="button" className="intro-modal__btn" onClick={handleIntroClose}>
                            {t('intro.ok')}
                        </button>
                    </div>
                </div>
            )}
            {!isTechniqueOpen && <BottomNav />}
        </div>
    );
};

export default ProgramPage;
