import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
    createWorkoutPlan,
    getProfile,
    getSubscriptionStatus,
    getWorkoutPlanOptions,
    HttpError,
    type WorkoutPlanCreatePayload,
} from '../api/http';
import type { ProfileResp, SubscriptionPlanOption, WorkoutPlanKind, WorkoutPlanOptionsResp } from '../api/types';
import { applyLang, useI18n } from '../i18n/i18n';
import BottomNav from '../components/BottomNav';
import LoadingSpinner from '../components/LoadingSpinner';
import {
    closeWebApp,
    hideBackButton,
    onBackButtonClick,
    offBackButtonClick,
    readInitData,
    readPreferredLocale,
    showBackButton,
    tmeReady,
} from '../telegram';
import ProgressBar from '../components/ProgressBar';
import { useGenerationProgress } from '../hooks/useGenerationProgress';
import { waitForLatestWorkoutId } from '../utils/workouts';

const DEFAULT_SPLIT_NUMBER = 3;
const MIN_SPLIT_NUMBER = 1;
const MAX_SPLIT_NUMBER = 7;

const WorkoutFlowPage: React.FC = () => {
    const navigate = useNavigate();
    const { t } = useI18n();
    const [searchParams] = useSearchParams();
    const paramLang = searchParams.get('lang') || undefined;
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [profile, setProfile] = useState<ProfileResp | null>(null);
    const [options, setOptions] = useState<WorkoutPlanOptionsResp | null>(null);
    const [stepIndex, setStepIndex] = useState(0);
    const [splitNumber, setSplitNumber] = useState(DEFAULT_SPLIT_NUMBER);
    const [plan, setPlan] = useState<WorkoutPlanKind | null>(null);
    const planRef = useRef<WorkoutPlanKind | null>(null);
    const [selectedPeriod, setSelectedPeriod] = useState<SubscriptionPlanOption | null>(null);
    const [wishes, setWishes] = useState('');
    const [showTopupModal, setShowTopupModal] = useState(false);
    const [showSubscriptionConfirm, setShowSubscriptionConfirm] = useState(false);
    const [checkingSubscriptionStatus, setCheckingSubscriptionStatus] = useState(false);
    const [subscriptionStatus, setSubscriptionStatus] = useState<{ checked: boolean; active: boolean }>({
        checked: false,
        active: false,
    });
    const initData = readInitData();
    const [submitting, setSubmitting] = useState(false);
    const [tooltipOpen, setTooltipOpen] = useState(false);
    const tooltipRef = useRef<HTMLDivElement | null>(null);
    const progressHelper = useGenerationProgress('workout', (data: any) => {
        const resultId = data?.result_id ? String(data.result_id) : null;
        const params = new URLSearchParams(searchParams.toString());
        const storedPlan = window.localStorage.getItem('generation_plan_type_workout');
        const resolvedPlan = planRef.current ?? (storedPlan as WorkoutPlanKind | null);
        const isSubscription = resolvedPlan === 'subscription';
        const locale = readPreferredLocale(paramLang);

        const applyParams = (nextId?: string | null) => {
            if (isSubscription) {
                params.delete('program_id');
                params.delete('id');
                params.set('source', 'subscription');
                if (nextId) {
                    params.set('subscription_id', nextId);
                } else {
                    params.delete('subscription_id');
                }
            } else {
                params.delete('subscription_id');
                params.delete('source');
                if (nextId) {
                    params.set('program_id', nextId);
                } else {
                    params.delete('program_id');
                }
            }
        };

        const finalizeNavigate = () => {
            window.localStorage.removeItem('generation_plan_type_workout');
            const query = params.toString();
            navigate(query ? `/?${query}` : '/');
        };

        if (resultId) {
            applyParams(resultId);
            finalizeNavigate();
            return;
        }

        void (async () => {
            const latestId = await waitForLatestWorkoutId(initData, isSubscription ? 'subscription' : 'program', locale);
            applyParams(latestId ? String(latestId) : null);
            finalizeNavigate();
        })();
    });

    useEffect(() => {
        const preferred = readPreferredLocale(paramLang);
        void applyLang(preferred);
    }, [paramLang]);

    useEffect(() => {
        planRef.current = plan;
    }, [plan]);

    useEffect(() => {
        if (!profile?.language) {
            return;
        }
        void applyLang(profile.language);
    }, [profile?.language]);

    useEffect(() => {
        const initData = readInitData();
        if (!initData) {
            setError(t('open_from_telegram'));
            setLoading(false);
            return;
        }
        const controller = new AbortController();
        setLoading(true);
        setError(null);
        Promise.all([getProfile(initData, controller.signal), getWorkoutPlanOptions(initData, controller.signal)])
            .then(([profileData, optionsData]) => {
                setProfile(profileData);
                setOptions(optionsData);
                tmeReady();
            })
            .catch(() => {
                setError(t('unexpected_error'));
            })
            .finally(() => {
                setLoading(false);
            });
        return () => controller.abort();
    }, []);

    useEffect(() => {
        if (!tooltipOpen) {
            return;
        }
        const handleClick = (event: MouseEvent) => {
            if (!tooltipRef.current || tooltipRef.current.contains(event.target as Node)) {
                return;
            }
            setTooltipOpen(false);
        };
        const handleEscape = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setTooltipOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClick);
        document.addEventListener('keydown', handleEscape);
        return () => {
            document.removeEventListener('mousedown', handleClick);
            document.removeEventListener('keydown', handleEscape);
        };
    }, [tooltipOpen]);

    useEffect(() => {
        // Disable back button if generating content
        if (progressHelper.isActive) {
            hideBackButton();
            return;
        }

        const handleBack = () => {
            if (stepIndex > 0) {
                setStepIndex((prev) => Math.max(0, prev - 1));
                return;
            }
            if (window.history.length > 1) {
                navigate(-1);
                return;
            }
            navigate('/');
        };
        showBackButton();
        onBackButtonClick(handleBack);
        return () => {
            offBackButtonClick(handleBack);
            hideBackButton();
        };
    }, [navigate, stepIndex, progressHelper.isActive]);

    const steps = useMemo(() => ['plan', 'days', 'wishes'], []);
    const stepsCount = steps.length;
    const translatePercent = (100 / stepsCount) * stepIndex;
    const trackStyle: React.CSSProperties = {
        width: `${stepsCount * 100}%`,
        transform: `translateX(-${translatePercent}%)`,
    };
    const paneStyle: React.CSSProperties = {
        width: `${100 / stepsCount}%`,
    };

    const goToTopup = useCallback(() => {
        const query = searchParams.toString();
        navigate(query ? `/topup?${query}` : '/topup');
    }, [navigate, searchParams]);

    const incrementSplit = useCallback(() => {
        setSplitNumber((prev) => Math.min(MAX_SPLIT_NUMBER, prev + 1));
    }, []);

    const decrementSplit = useCallback(() => {
        setSplitNumber((prev) => Math.max(MIN_SPLIT_NUMBER, prev - 1));
    }, []);

    const handleSubscriptionSelect = useCallback(
        (option: SubscriptionPlanOption) => {
            const balance = profile?.credits ?? 0;
            if (balance < option.price) {
                setShowTopupModal(true);
                return;
            }
            setPlan('subscription');
            setSelectedPeriod(option);
        },
        [profile]
    );

    const handleProgramSelect = useCallback(() => {
        if (!options) {
            return;
        }
        const balance = profile?.credits ?? 0;
        if (balance < options.program_price) {
            setShowTopupModal(true);
            return;
        }
        setPlan('program');
    }, [options, profile]);

    const handleGenerate = useCallback(async () => {
        if (submitting) {
            return;
        }
        const initData = readInitData();
        if (!initData) {
            window.alert(t('open_from_telegram'));
            return;
        }
        if (!plan) {
            return;
        }
        if (plan === 'subscription' && !selectedPeriod) {
            window.alert(t('workout_flow.subscription.title'));
            return;
        }
        const payload: WorkoutPlanCreatePayload = {
            plan_type: plan,
            split_number: splitNumber,
            wishes,
        };
        if (plan === 'subscription' && selectedPeriod) {
            payload.period = selectedPeriod.period;
        }
        try {
            window.localStorage.setItem('generation_plan_type_workout', plan);
        } catch {
        }
        setSubmitting(true);
        try {
            const result = await createWorkoutPlan(payload, initData);
            if (result.task_id) {
                progressHelper.start(result.task_id);
            } else {
                // Fallback or error if task_id missing is unexpected
                console.error('Task ID missing from createWorkoutPlan response');
            }
        } catch (err) {
            if (err instanceof HttpError && err.message === 'not_enough_credits') {
                setShowTopupModal(true);
                return;
            }
            const messageKey = err instanceof HttpError ? (err.message as any) : ('program.action_error' as any);
            window.alert(t(messageKey));
        } finally {
            setSubmitting(false);
        }
    }, [plan, selectedPeriod, splitNumber, submitting, wishes, progressHelper]);

    const handlePlanNext = useCallback(async () => {
        if (checkingSubscriptionStatus || !plan) {
            return;
        }
        if (plan === 'subscription' && !selectedPeriod) {
            return;
        }
        if (plan !== 'subscription') {
            setStepIndex(1);
            return;
        }
        if (subscriptionStatus.checked) {
            if (subscriptionStatus.active) {
                setShowSubscriptionConfirm(true);
                return;
            }
            setStepIndex(1);
            return;
        }
        const initData = readInitData();
        if (!initData) {
            window.alert(t('open_from_telegram'));
            return;
        }
        setCheckingSubscriptionStatus(true);
        try {
            const status = await getSubscriptionStatus(initData);
            setSubscriptionStatus({ checked: true, active: status.active });
            if (status.active) {
                setShowSubscriptionConfirm(true);
                return;
            }
            setStepIndex(1);
        } catch (err) {
            console.error('subscription_status_failed', err);
            window.alert(t('program.action_error'));
        } finally {
            setCheckingSubscriptionStatus(false);
        }
    }, [checkingSubscriptionStatus, plan, selectedPeriod, subscriptionStatus]);

    const handleSubscriptionConfirm = useCallback(() => {
        setShowSubscriptionConfirm(false);
        setStepIndex(1);
    }, []);

    const handleSubscriptionCancel = useCallback(() => {
        setShowSubscriptionConfirm(false);
    }, []);

    const subscriptionTitleForPeriod = useCallback((period: SubscriptionPlanOption['period']) => {
        if (period === '1m') {
            return t('workout_flow.subscription.option.one_month');
        }
        if (period === '6m') {
            return t('workout_flow.subscription.option.six_months');
        }
        return t('workout_flow.subscription.option.twelve_months');
    }, []);

    if (loading) {
        return (
            <div className="page-container workout-flow-page">
                <div className="page-shell">
                    <LoadingSpinner />
                </div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="page-container workout-flow-page">
                <div className="page-shell">
                    <div className="error-block">{error}</div>
                </div>
            </div>
        );
    }

    return (
        <div className="page-container workout-flow-page">
            <div className="page-shell">
                {progressHelper.isActive ? (
                    <ProgressBar
                        progress={progressHelper.progress}
                        stage={progressHelper.stage}
                        onClose={closeWebApp}
                    />
                ) : (
                    <section className="workout-flow" aria-live="polite">
                        <div className="workout-flow__track" style={trackStyle}>
                            {options && (
                                <div className="workout-flow__pane" style={paneStyle}>
                                    <div className="workout-flow__pane-inner">
                                        <h2 className="workout-flow__title">{t('workout_flow.plan.title')}</h2>
                                        <div className="workout-flow__balance">
                                            <span className="workout-flow__balance-label">
                                                {t('profile.balance.title')}
                                            </span>
                                            <span className="workout-flow__balance-value">
                                                {t('profile.balance.label', { count: profile?.credits ?? 0 })}
                                            </span>
                                        </div>
                                        <div className="workout-flow__plan-blocks">
                                            <div className="plan-section">
                                                <div className="plan-section__title">
                                                    {t('workout_flow.plan.subscription_label')}
                                                </div>
                                                <div className="subscription-options">
                                                    {options.subscriptions.map((option) => {
                                                        const active =
                                                            plan === 'subscription' && selectedPeriod?.period === option.period;
                                                        return (
                                                            <button
                                                                key={option.period}
                                                                type="button"
                                                                className={`subscription-option ${active ? 'is-active' : ''}`}
                                                                onClick={() => handleSubscriptionSelect(option)}
                                                            >
                                                                <span className="subscription-option__title">
                                                                    {subscriptionTitleForPeriod(option.period)}
                                                                </span>
                                                                <span className="subscription-option__price">
                                                                    {t('profile.balance.label', { count: option.price })}
                                                                </span>
                                                            </button>
                                                        );
                                                    })}
                                                </div>
                                            </div>
                                            <div className="plan-section">
                                                <div className="plan-section__title">
                                                    {t('workout_flow.plan.program_label')}
                                                </div>
                                                <button
                                                    type="button"
                                                    className={`subscription-option ${plan === 'program' ? 'is-active' : ''}`}
                                                    onClick={handleProgramSelect}
                                                >
                                                    <span className="subscription-option__title">
                                                        {t('workout_flow.plan.program_option')}
                                                    </span>
                                                    <span className="subscription-option__price">
                                                        {t('profile.balance.label', { count: options.program_price })}
                                                    </span>
                                                </button>
                                            </div>
                                        </div>
                                        <button
                                            type="button"
                                            className="primary-button workout-flow__next"
                                            disabled={!plan || checkingSubscriptionStatus || (plan === 'subscription' && !selectedPeriod)}
                                            onClick={handlePlanNext}
                                        >
                                            {t('workout_flow.next')}
                                        </button>
                                    </div>
                                </div>
                            )}
                            <div className="workout-flow__pane" style={paneStyle}>
                                <div className="workout-flow__pane-inner">
                                    <h2 className="workout-flow__title">{t('workout_flow.days.title')}</h2>
                                    <div className="day-selector">
                                        <button
                                            type="button"
                                            className="day-selector__btn"
                                            onClick={decrementSplit}
                                            aria-label={t('workout_flow.days.decrease')}
                                        >
                                            -
                                        </button>
                                        <div className="day-selector__value">{splitNumber}</div>
                                        <button
                                            type="button"
                                            className="day-selector__btn"
                                            onClick={incrementSplit}
                                            aria-label={t('workout_flow.days.increase')}
                                        >
                                            +
                                        </button>
                                    </div>
                                    <button
                                        type="button"
                                        className="primary-button workout-flow__next"
                                        onClick={() => setStepIndex(2)}
                                    >
                                        {t('workout_flow.next')}
                                    </button>
                                </div>
                            </div>
                            <div className="workout-flow__pane" style={paneStyle}>
                                <div className="workout-flow__pane-inner">
                                    <div className="workout-flow__wishes-head">
                                        <h2 className="workout-flow__title">
                                            <span className="workout-flow__title-inline">
                                                {t('workout_flow.wishes.title')}
                                                {'\u00a0'}
                                                <span className="tooltip" ref={tooltipRef}>
                                                    <button
                                                        type="button"
                                                        className="tooltip__button"
                                                        aria-label={t('workout_flow.wishes.tooltip_label')}
                                                        onClick={() => setTooltipOpen((prev) => !prev)}
                                                        onMouseEnter={() => setTooltipOpen(true)}
                                                        onMouseLeave={() => setTooltipOpen(false)}
                                                    >
                                                        i
                                                    </button>
                                                    {tooltipOpen && (
                                                        <div className="tooltip__bubble" role="tooltip">
                                                            {t('workout_flow.wishes.tooltip')}
                                                        </div>
                                                    )}
                                                </span>
                                            </span>
                                        </h2>
                                    </div>
                                    <textarea
                                        className="workout-flow__textarea"
                                        rows={5}
                                        value={wishes}
                                        onChange={(event) => setWishes(event.target.value)}
                                    />
                                    <button
                                        type="button"
                                        className="primary-button workout-flow__generate"
                                        onClick={handleGenerate}
                                        disabled={submitting}
                                    >
                                        {submitting ? t('workout_flow.generating') : t('workout_flow.generate')}
                                    </button>
                                </div>
                            </div>
                        </div>
                    </section>
                )}

                {!showTopupModal && !showSubscriptionConfirm && (
                    <BottomNav activeKey="workouts" />
                )}
            </div>
            {showTopupModal && (
                <div role="dialog" aria-modal="true" className="subscription-confirm">
                    <div className="subscription-confirm__dialog">
                        <h3 className="subscription-confirm__title">{t('workout_flow.topup.title')}</h3>
                        <p className="subscription-confirm__body">{t('workout_flow.topup.body')}</p>
                        <div className="subscription-confirm__actions">
                            <button
                                type="button"
                                className="subscription-confirm__btn subscription-confirm__btn--confirm"
                                onClick={goToTopup}
                            >
                                {t('workout_flow.topup.cta')}
                            </button>
                        </div>
                    </div>
                </div>
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

export default WorkoutFlowPage;
