import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import TopBar from '../components/TopBar';
import BottomNav from '../components/BottomNav';
import LoadingSpinner from '../components/LoadingSpinner';
import { applyLang, useI18n, type TranslationKey } from '../i18n/i18n';
import {
    createDietPlan,
    getDietPlanOptions,
    getProfile,
    HttpError,
    updateProfile
} from '../api/http';
import {
    readInitData,
    readPreferredLocale,
    showBackButton,
    hideBackButton,
    onBackButtonClick,
    offBackButtonClick,
    closeWebApp
} from '../telegram';
import type { DietProduct, ProfileResp } from '../api/types';
import ProgressBar from '../components/ProgressBar';
import { useGenerationProgress } from '../hooks/useGenerationProgress';
import { waitForLatestDietId } from '../utils/diets';

const DIET_PRODUCT_OPTIONS: Array<{ value: DietProduct; labelKey: TranslationKey }> = [
    { value: 'plant_food', labelKey: 'profile.diet_products.plant_food' },
    { value: 'meat', labelKey: 'profile.diet_products.meat' },
    { value: 'fish_seafood', labelKey: 'profile.diet_products.fish_seafood' },
    { value: 'eggs', labelKey: 'profile.diet_products.eggs' },
    { value: 'dairy', labelKey: 'profile.diet_products.dairy' },
];

type FlowStep = 'allergies' | 'products' | 'confirm';

const DietFlowPage: React.FC = () => {
    const navigate = useNavigate();
    const { t } = useI18n();
    const [searchParams] = useSearchParams();
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [profile, setProfile] = useState<ProfileResp | null>(null);
    const [price, setPrice] = useState<number>(0);
    const [step, setStep] = useState<FlowStep>('confirm');
    const [dietAllergies, setDietAllergies] = useState('');
    const [dietProducts, setDietProducts] = useState<DietProduct[]>([]);
    const [savingPrefs, setSavingPrefs] = useState(false);
    const [creating, setCreating] = useState(false);
    const [showTopup, setShowTopup] = useState(false);
    const initData = readInitData();
    const paramLang = searchParams.get('lang') || undefined;
    const progressHelper = useGenerationProgress('diet', (data: any) => {
        const query = searchParams.toString();
        const dietId = data?.result_id;
        if (dietId) {
            navigate(query ? `/diets?diet_id=${dietId}&${query}` : `/diets?diet_id=${dietId}`);
            return;
        }
        void (async () => {
            const latestId = await waitForLatestDietId(initData);
            if (latestId) {
                navigate(query ? `/diets?diet_id=${latestId}&${query}` : `/diets?diet_id=${latestId}`);
                return;
            }
            navigate(query ? `/diets?${query}` : '/diets');
        })();
    });

    useEffect(() => {
        const preferred = readPreferredLocale(paramLang);
        void applyLang(preferred);
    }, [paramLang]);

    useEffect(() => {
        const controller = new AbortController();
        let active = true;
        setLoading(true);
        setError(null);
        Promise.all([
            getProfile(initData, controller.signal),
            getDietPlanOptions(initData, controller.signal),
        ])
            .then(([profileData, options]) => {
                if (!active) return;
                const preferred = readPreferredLocale(paramLang);
                void applyLang(profileData.language || preferred);
                setProfile(profileData);
                setPrice(options.price);
                setDietAllergies(profileData.diet_allergies ?? '');
                setDietProducts(profileData.diet_products ?? []);
                setStep(profileData.diet_products == null ? 'allergies' : 'confirm');
            })
            .catch((err) => {
                if (!active) return;
                console.error('Failed to load diet flow data', err);
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
    }, [initData, paramLang]);

    const steps = useMemo(() => {
        if (profile?.diet_products == null) {
            return ['allergies', 'products', 'confirm'] as FlowStep[];
        }
        return ['confirm'] as FlowStep[];
    }, [profile]);

    const stepIndex = useMemo(() => steps.indexOf(step), [steps, step]);

    const handleBack = useCallback(() => {
        // If progress is active, back button should likely be disabled or handle specific logic
        // But here we rely on hideBackButton in useEffect if progress active
        if (stepIndex > 0) {
            setStep(steps[stepIndex - 1]);
            return;
        }
        const query = searchParams.toString();
        navigate(query ? `/diets?${query}` : '/diets');
    }, [navigate, searchParams, stepIndex, steps]);

    useEffect(() => {
        if (progressHelper.isActive) {
            hideBackButton();
            return;
        }
        showBackButton();
        onBackButtonClick(handleBack);
        return () => {
            offBackButtonClick(handleBack);
            hideBackButton();
        };
    }, [handleBack, progressHelper.isActive]);

    const handleNextAllergies = useCallback(() => {
        setStep('products');
    }, []);

    const handleSavePreferences = useCallback(async () => {
        if (dietProducts.length === 0) {
            return;
        }
        setSavingPrefs(true);
        try {
            const updated = await updateProfile(
                {
                    diet_allergies: dietAllergies.trim() ? dietAllergies.trim() : null,
                    diet_products: dietProducts,
                },
                initData
            );
            setProfile(updated);
            setStep('confirm');
        } catch (err) {
            if (err instanceof HttpError) {
                setError(t(err.message as any));
            } else {
                setError(t('unexpected_error'));
            }
        } finally {
            setSavingPrefs(false);
        }
    }, [dietAllergies, dietProducts, initData]);

    const handleCreate = useCallback(async () => {
        if (creating) {
            return;
        }
        setCreating(true);
        try {
            const result = await createDietPlan(initData);
            if (result.task_id) {
                progressHelper.start(result.task_id);
            }
        } catch (err) {
            if (err instanceof HttpError) {
                if (err.message === 'not_enough_credits') {
                    setShowTopup(true);
                } else if (err.message === 'diet_preferences_required') {
                    setStep('allergies');
                } else {
                    setError(t(err.message as any));
                }
            } else {
                setError(t('unexpected_error'));
            }
        } finally {
            setCreating(false);
        }
    }, [creating, initData, progressHelper]);

    const handleTopup = useCallback(() => {
        const query = searchParams.toString();
        navigate(query ? `/topup?${query}` : '/topup');
    }, [navigate, searchParams]);

    const paneStyle: React.CSSProperties = {
        width: `${100 / steps.length}%`,
    };
    const trackStyle: React.CSSProperties = {
        width: `${steps.length * 100}%`,
        transform: `translateX(-${(stepIndex * 100) / steps.length}%)`,
    };

    return (
        <div className="page-container diet-flow-page">
            <TopBar title={t('diet.flow.title')} onBack={handleBack} />
            <div className="page-shell">
                {error && <div className="error-block">{error}</div>}
                {loading && <LoadingSpinner />}

                {progressHelper.isActive && !loading && !error && (
                    <ProgressBar
                        progress={progressHelper.progress}
                        stage={progressHelper.stage}
                        onClose={closeWebApp}
                    />
                )}

                {!loading && !error && !progressHelper.isActive && (
                    <section className="workout-flow" aria-live="polite">
                        <div className="workout-flow__track" style={trackStyle}>
                            {steps.includes('allergies') && (
                                <div className="workout-flow__pane" style={paneStyle}>
                                    <div className="workout-flow__pane-inner">
                                        <h2 className="workout-flow__title">{t('diet.flow.allergies.title')}</h2>
                                        <textarea
                                            className="workout-flow__textarea"
                                            rows={4}
                                            value={dietAllergies}
                                            onChange={(event) => setDietAllergies(event.target.value)}
                                            placeholder={t('diet.flow.allergies.placeholder')}
                                        />
                                        <button
                                            type="button"
                                            className="primary-button workout-flow__next"
                                            onClick={handleNextAllergies}
                                        >
                                            {t('workout_flow.next')}
                                        </button>
                                    </div>
                                </div>
                            )}
                            {steps.includes('products') && (
                                <div className="workout-flow__pane" style={paneStyle}>
                                    <div className="workout-flow__pane-inner">
                                        <h2 className="workout-flow__title">{t('diet.flow.products.title')}</h2>
                                        <p className="diet-flow__hint">{t('diet.flow.products.hint')}</p>
                                        <div className="profile-checklist">
                                            {DIET_PRODUCT_OPTIONS.map((option) => {
                                                const selected = dietProducts.includes(option.value);
                                                return (
                                                    <label key={option.value} className="profile-checklist__item">
                                                        <input
                                                            type="checkbox"
                                                            checked={selected}
                                                            onChange={() => {
                                                                setDietProducts((prev) =>
                                                                    prev.includes(option.value)
                                                                        ? prev.filter((item) => item !== option.value)
                                                                        : [...prev, option.value]
                                                                );
                                                            }}
                                                        />
                                                        <span>{t(option.labelKey)}</span>
                                                    </label>
                                                );
                                            })}
                                        </div>
                                        <button
                                            type="button"
                                            className="primary-button workout-flow__next"
                                            onClick={handleSavePreferences}
                                            disabled={dietProducts.length === 0 || savingPrefs}
                                        >
                                            {savingPrefs ? t('program.exercise.edit_dialog.saving') : t('workout_flow.next')}
                                        </button>
                                    </div>
                                </div>
                            )}
                            <div className="workout-flow__pane" style={paneStyle}>
                                <div className="workout-flow__pane-inner">
                                    <div className="workout-flow__balance">
                                        <span className="workout-flow__balance-label">{t('profile.balance.title')}</span>
                                        <span className="workout-flow__balance-value">
                                            {t('profile.balance.label', { count: profile?.credits ?? 0 })}
                                        </span>
                                    </div>
                                    <div className="workout-flow__plan-blocks">
                                        <div className="plan-section">
                                            <div className="plan-section__title">{t('diet.flow.plan.title')}</div>
                                            <div className="subscription-option is-active">
                                                <span className="subscription-option__title">{t('diet.flow.plan.option')}</span>
                                                <span className="subscription-option__price">
                                                    {t('profile.balance.label', { count: price })}
                                                </span>
                                            </div>
                                        </div>
                                    </div>
                                    <button
                                        type="button"
                                        className="primary-button workout-flow__generate"
                                        onClick={handleCreate}
                                        disabled={creating}
                                    >
                                        {creating ? t('workout_flow.generating') : t('diet.flow.create')}
                                    </button>
                                </div>
                            </div>
                        </div>
                    </section>
                )}
            </div>
            {showTopup && (
                <div role="dialog" aria-modal="true" className="subscription-confirm">
                    <div className="subscription-confirm__dialog">
                        <h3 className="subscription-confirm__title">{t('workout_flow.topup.title')}</h3>
                        <p className="subscription-confirm__body">{t('workout_flow.topup.body')}</p>
                        <div className="subscription-confirm__actions">
                            <button
                                type="button"
                                className="subscription-confirm__btn subscription-confirm__btn--confirm"
                                onClick={handleTopup}
                            >
                                {t('workout_flow.topup.cta')}
                            </button>
                        </div>
                    </div>
                </div>
            )}
            {!showTopup && !progressHelper.isActive && <BottomNav activeKey="diets" />}
            {progressHelper.isActive && <BottomNav activeKey="diets" />}
        </div>
    );
};

export default DietFlowPage;
