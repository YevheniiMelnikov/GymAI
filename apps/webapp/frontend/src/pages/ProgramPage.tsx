import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
    getProgram,
    getSubscription,
    getSubscriptionStatus,
    HttpError,
    triggerWorkoutAction,
    WorkoutAction
} from '../api/http';
import { applyLang, t } from '../i18n/i18n';
import {
    EXERCISE_EDIT_SAVED_EVENT,
    fmtDate,
    renderLegacyProgram,
    renderProgramDays,
    setProgramContext,
} from '../ui/render_program';
import { readInitData, tmeReady } from '../telegram';
import type { Locale, Program } from '../api/types';
import { renderSegmented, SegmentId } from '../components/Segmented';
import TopBar from '../components/TopBar';

const LAST_WORKOUT_SEGMENT_KEY = 'gymbot.workouts.lastSegment';

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
    const [searchParams, setSearchParams] = useSearchParams();
    const navigate = useNavigate();
    const searchParamsKey = searchParams.toString();
    const contentRef = useRef<HTMLDivElement>(null);
    const switcherRef = useRef<HTMLDivElement>(null);
    const fallbackIllustration =
        "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='360' height='260' viewBox='0 0 360 260' fill='none'><defs><linearGradient id='g1' x1='50' y1='30' x2='310' y2='210' gradientUnits='userSpaceOnUse'><stop stop-color='%23C7DFFF'/><stop offset='1' stop-color='%23E7EEFF'/></linearGradient><linearGradient id='g2' x1='120' y1='80' x2='240' y2='200' gradientUnits='userSpaceOnUse'><stop stop-color='%237AA7FF'/><stop offset='1' stop-color='%235B8BFF'/></linearGradient></defs><rect x='30' y='24' width='300' height='200' rx='28' fill='url(%23g1)'/><rect x='62' y='56' width='236' height='136' rx='18' fill='white' stroke='%23B8C7E6' stroke-width='3'/><path d='M90 174c18-30 42-30 60 0s42 30 60 0 42-30 60 0' stroke='%23A7B9DB' stroke-width='6' stroke-linecap='round' fill='none'/><circle cx='136' cy='106' r='16' fill='url(%23g2)'/><circle cx='216' cy='118' r='12' fill='%23E6ECFC'/><circle cx='248' cy='94' r='8' fill='%23E6ECFC'/></svg>";
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [actionLoading, setActionLoading] = useState(false);
    const [fabPressed, setFabPressed] = useState(false);
    const [isExerciseEditOpen, setIsExerciseEditOpen] = useState(false);
    const [refreshKey, setRefreshKey] = useState(0);
    const [dateText, setDateText] = useState('');
    const [showSubscriptionConfirm, setShowSubscriptionConfirm] = useState(false);
    const [activeSegment, setActiveSegment] = useState<SegmentId>(() => {
        const source = searchParams.get('source');
        if (source === 'subscription') {
            return 'subscriptions';
        }
        return readLastWorkoutSegment();
    });

    const programId = searchParams.get('id') || '';
    const paramLang = searchParams.get('lang') || undefined;

    useEffect(() => {
        void applyLang(paramLang);
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
            setDateText('');
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
                    } else {
                        legacyText = load.programText;
                        createdAt = load.createdAt ?? null;
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
                            created_at: null,
                            days: sub.days
                        };
                    } else if (sub.program) {
                        legacyText = sub.program;
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

    const handleWorkoutAction = useCallback(
        async (nextAction: WorkoutAction | null) => {
            if (!nextAction) {
                return;
            }
            const initData = readInitData();
            const tg = (window as any).Telegram?.WebApp;
            if (!initData) {
                window.alert(t('open_from_telegram'));
                return;
            }
            setActionLoading(true);
            try {
                const payload =
                    nextAction === 'create_program' ? 'create_new_program' : 'create_new_subscription';
                try {
                    tg?.sendData(payload);
                } catch {
                }
                await triggerWorkoutAction(nextAction, initData);
                tg?.close();
            } catch (err) {
                const messageKey = err instanceof HttpError ? (err.message as any) : ('program.action_error' as any);
                const translated = t(messageKey);
                console.error('workouts_action_failed', err);
                window.alert(translated || t('program.action_error'));
            } finally {
                setActionLoading(false);
            }
        },
        []
    );

    const creationAction: WorkoutAction | null =
        activeSegment === 'program'
            ? 'create_program'
            : activeSegment === 'subscriptions'
            ? 'create_subscription'
            : null;

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
        await handleWorkoutAction(creationAction);
    }, [creationAction, handleWorkoutAction]);

    const handleSubscriptionConfirm = useCallback(async () => {
        setShowSubscriptionConfirm(false);
        await handleWorkoutAction('create_subscription');
    }, [handleWorkoutAction]);

    const handleSubscriptionCancel = useCallback(() => {
        setShowSubscriptionConfirm(false);
    }, []);

    const fabStyle: React.CSSProperties = {
        position: 'fixed',
        bottom: 30,
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

    const handleHistoryIconClick = useCallback(() => {
        const params = new URLSearchParams();
        params.set('segment', activeSegment);
        navigate(`/history?${params.toString()}`);
        const tg = (window as any).Telegram?.WebApp;
        try {
            tg?.HapticFeedback?.impactOccurred('medium');
        } catch {
        }
        try {
            tg?.sendData?.('view_history');
        } catch {
        }
    }, [activeSegment, navigate]);

    const historyIconStyle: React.CSSProperties = {
        background: 'none',
        border: 'none',
        color: 'currentColor',
        cursor: 'pointer',
        padding: 0,
        outline: 'none',
    };

    return (
        <div className="page-container">
            <TopBar title={t('program.title')}>
                <button
                    type="button"
                    onClick={handleHistoryIconClick}
                    aria-label={t('program.view_history')}
                    style={historyIconStyle}
                >
                    <span className="topbar__icon topbar__icon--archive" aria-hidden="true" />
                </button>
            </TopBar>

            <div className="page-shell">
                <div id="content" aria-busy={loading}>
                    <div className="history-panel program-panel">
                        <div ref={switcherRef} id="segmented" className="segmented-container" />

                        <div ref={contentRef} className="week centered" />
                        <div id="program-date" hidden={!dateText}>
                            {dateText}
                        </div>

                        {loading && <div aria-busy="true">Loading...</div>}
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
                            </div>
                        )}
                    </div>
                </div>

                <div className="history-footer" />
            </div>
            {creationAction && !isExerciseEditOpen && (
                <button
                    type="button"
                    style={fabStyle}
                    aria-label={t('program.create_new')}
                    onClick={handleFabClick}
                    onPointerDown={() => setFabPressed(true)}
                    onPointerUp={() => setFabPressed(false)}
                    onPointerLeave={() => setFabPressed(false)}
                    disabled={actionLoading}
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
        </div>
    );
};

export default ProgramPage;
