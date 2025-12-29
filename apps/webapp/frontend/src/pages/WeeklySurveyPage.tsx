import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ExerciseSetPayload, HttpError, getSubscription, statusToMessage, submitWeeklySurvey } from '../api/http';
import type { Day, Exercise, WorkoutDay } from '../api/types';
import { applyLang, t } from '../i18n/i18n';
import type { TranslationKey } from '../i18n/i18n';
import TopBar from '../components/TopBar';
import {
    closeWebApp,
    hideBackButton,
    onBackButtonClick,
    offBackButtonClick,
    readInitData,
    showBackButton,
    tmeReady
} from '../telegram';
import { openExerciseEditDialog, setProgramContext } from '../ui/render_program';

type SurveyDay = {
    id: string;
    title: string | null;
    exercises: Exercise[];
};

type EditedExerciseSets = {
    exerciseId: string;
    sets: ExerciseSetPayload[];
    weightUnit: string | null;
};

const DEFAULT_SLIDER_VALUE = 50;

const getSurveyDays = (days: Day[]): SurveyDay[] => {
    const weeks = [{ index: 1, days }];
    const workoutDays: SurveyDay[] = [];
    weeks.forEach((week) => {
        week.days.forEach((day) => {
            if (day.type !== 'workout') {
                return;
            }
            const workout = day as WorkoutDay;
            workoutDays.push({
                id: workout.id || `week-${week.index}-day-${workout.index}`,
                title: workout.title ?? null,
                exercises: workout.exercises
            });
        });
    });
    return workoutDays;
};

const intensityColor = (value: number): string => {
    const clamped = Math.max(0, Math.min(100, value));
    const hue = 120 - (clamped / 100) * 120;
    return `hsl(${hue} 70% 45%)`;
};

const buildExerciseKey = (dayId: string, exerciseId: string): string => `${dayId}:${exerciseId}`;

const WeeklySurveyPage: React.FC = () => {
    const [searchParams] = useSearchParams();
    const paramLang = searchParams.get('lang') || undefined;
    const subscriptionId = searchParams.get('subscription_id') || '';
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [surveyDays, setSurveyDays] = useState<SurveyDay[]>([]);
    const [activeIndex, setActiveIndex] = useState(0);
    const [intensityValues, setIntensityValues] = useState<Record<string, number>>({});
    const [commentValues, setCommentValues] = useState<Record<string, string>>({});
    const [commentOpen, setCommentOpen] = useState<Record<string, boolean>>({});
    const [skippedDays, setSkippedDays] = useState<Record<string, boolean>>({});
    const [editedSets, setEditedSets] = useState<Record<string, EditedExerciseSets>>({});
    const [submitting, setSubmitting] = useState(false);

    useEffect(() => {
        void applyLang(paramLang);
    }, [paramLang]);

    useEffect(() => {
        const controller = new AbortController();
        const initData = readInitData();

        const fetchData = async () => {
            setLoading(true);
            setError(null);
            setSurveyDays([]);
            setProgramContext(null, null);
            try {
                const subscription = await getSubscription(initData, subscriptionId, controller.signal);
                await applyLang(subscription.language || paramLang);
                if (!subscription.days) {
                    setError(t('weekly_survey.no_data'));
                    return;
                }
                const days = getSurveyDays(subscription.days);
                setSurveyDays(days);
                if (days.length === 0) {
                    setError(t('weekly_survey.no_workouts'));
                    return;
                }
            } catch (e) {
                const key = e instanceof HttpError ? statusToMessage(e.status) : 'unexpected_error';
                setError(t(key as TranslationKey));
            } finally {
                setLoading(false);
                tmeReady();
            }
        };

        fetchData();
        return () => controller.abort();
    }, [paramLang, subscriptionId]);

    useEffect(() => {
        const initialValues: Record<string, number> = {};
        surveyDays.forEach((day) => {
            day.exercises.forEach((exercise) => {
                initialValues[buildExerciseKey(day.id, exercise.id)] = DEFAULT_SLIDER_VALUE;
            });
        });
        setIntensityValues(initialValues);
        setCommentValues({});
        setCommentOpen({});
        setSkippedDays({});
        setEditedSets({});
        setActiveIndex(0);
    }, [surveyDays]);

    useEffect(() => {
        if (surveyDays.length === 0) {
            return;
        }
        setActiveIndex((current) => Math.min(current, surveyDays.length - 1));
    }, [surveyDays.length]);

    const handleBack = useCallback(() => {
        if (activeIndex > 0) {
            setActiveIndex((current) => Math.max(0, current - 1));
            return;
        }
        closeWebApp();
    }, [activeIndex]);

    useEffect(() => {
        showBackButton();
        onBackButtonClick(handleBack);
        return () => {
            offBackButtonClick(handleBack);
            hideBackButton();
        };
    }, [handleBack]);

    const handleSubmit = useCallback(async () => {
        if (submitting) {
            return;
        }
        const initData = readInitData();
        if (!initData) {
            window.alert(t('open_from_telegram'));
            return;
        }
        if (!subscriptionId) {
            window.alert(t('unexpected_error'));
            return;
        }
        setSubmitting(true);
        try {
            const payload = {
                subscription_id: Number(subscriptionId),
                days: surveyDays.map((day) => ({
                    id: day.id,
                    title: day.title,
                    skipped: skippedDays[day.id] ?? false,
                    exercises: day.exercises.map((exercise) => {
                        const key = buildExerciseKey(day.id, exercise.id);
                        const stored = editedSets[key];
                        return {
                            id: exercise.id,
                            name: exercise.name,
                            difficulty: intensityValues[key] ?? DEFAULT_SLIDER_VALUE,
                            comment: commentValues[key] ?? '',
                            sets_detail: stored
                                ? stored.sets.map((set) => ({
                                    reps: set.reps,
                                    weight: set.weight,
                                    weight_unit: stored.weightUnit
                                }))
                                : undefined
                        };
                    })
                }))
            };
            await submitWeeklySurvey(payload, initData);
            closeWebApp();
        } catch (e) {
            const key = e instanceof HttpError ? statusToMessage(e.status) : 'unexpected_error';
            window.alert(t(key as TranslationKey));
        } finally {
            setSubmitting(false);
        }
    }, [commentValues, editedSets, intensityValues, skippedDays, submitting, subscriptionId, surveyDays]);

    const handleNext = useCallback(() => {
        if (activeIndex < surveyDays.length - 1) {
            setActiveIndex((current) => Math.min(surveyDays.length - 1, current + 1));
            return;
        }
        handleSubmit();
    }, [activeIndex, handleSubmit, surveyDays.length]);

    const handleEditExercise = useCallback((dayId: string, exercise: Exercise) => {
        const key = buildExerciseKey(dayId, exercise.id);
        openExerciseEditDialog(exercise, {
            allowReplace: false,
            onSave: (_, sets) => {
                const weightUnit =
                    exercise.weight?.unit ?? exercise.sets_detail?.[0]?.weight_unit ?? null;
                setEditedSets((current) => ({
                    ...current,
                    [key]: { exerciseId: exercise.id, sets, weightUnit }
                }));
            }
        });
    }, []);

    const handleSkipDay = useCallback(() => {
        const currentDay = surveyDays[activeIndex];
        if (!currentDay) {
            return;
        }
        setSkippedDays((current) => ({ ...current, [currentDay.id]: true }));
        if (activeIndex < surveyDays.length - 1) {
            setActiveIndex((current) => Math.min(surveyDays.length - 1, current + 1));
        }
    }, [activeIndex, surveyDays]);

    const activeDayLabel = useMemo(() => {
        if (surveyDays.length === 0) {
            return '';
        }
        return t('weekly_survey.day_title', { n: activeIndex + 1 });
    }, [activeIndex, surveyDays.length]);

    const isLastDay = activeIndex >= surveyDays.length - 1;
    const trackStyle: React.CSSProperties = {
        transform: `translateX(-${activeIndex * 100}%)`
    };

    return (
        <div className="page-container">
            <TopBar title={t('weekly_survey.title')} onBack={handleBack} />

            <div className="page-shell weekly-survey">
                {loading && (
                    <div className="notice weekly-survey__notice" aria-busy="true">
                        {t('weekly_survey.loading')}
                    </div>
                )}

                {!loading && error && (
                    <div className="notice weekly-survey__notice">
                        {error}
                    </div>
                )}

                {!loading && !error && surveyDays.length > 0 && (
                    <>
                        <div className="weekly-survey__header">
                            <div className="weekly-survey__title">{activeDayLabel}</div>
                            <div className="weekly-survey__subtitle">{t('weekly_survey.context')}</div>
                        </div>

                        <div className="weekly-survey__viewport" aria-live="polite">
                            <div className="weekly-survey__track" style={trackStyle}>
                                {surveyDays.map((day) => (
                                    <section className="weekly-survey__day" key={day.id}>
                                        <div className="weekly-survey__card">
                                            {day.exercises.map((exercise) => {
                                                const key = buildExerciseKey(day.id, exercise.id);
                                                const value = intensityValues[key] ?? DEFAULT_SLIDER_VALUE;
                                                const comment = commentValues[key] ?? '';
                                                const isCommentOpen = commentOpen[key] ?? comment.length > 0;
                                                const sliderStyle: React.CSSProperties = {
                                                    '--slider-color': intensityColor(value)
                                                } as React.CSSProperties;
                                                return (
                                                    <div className="weekly-survey__exercise" key={exercise.id}>
                                                        <div className="weekly-survey__exercise-head">
                                                            <div className="weekly-survey__exercise-name">
                                                                {exercise.name}
                                                            </div>
                                                            <button
                                                                type="button"
                                                                className="weekly-survey__edit"
                                                                aria-label={t('weekly_survey.edit_exercise')}
                                                                onClick={() => handleEditExercise(day.id, exercise)}
                                                            >
                                                                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                                                                    <path
                                                                        d="M12 20h9"
                                                                        stroke="currentColor"
                                                                        strokeWidth="2"
                                                                        strokeLinecap="round"
                                                                        strokeLinejoin="round"
                                                                    />
                                                                    <path
                                                                        d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5Z"
                                                                        stroke="currentColor"
                                                                        strokeWidth="2"
                                                                        strokeLinecap="round"
                                                                        strokeLinejoin="round"
                                                                    />
                                                                </svg>
                                                            </button>
                                                        </div>
                                                        <div className="weekly-survey__slider-wrap">
                                                            <input
                                                                className="weekly-survey__slider"
                                                                type="range"
                                                                min="0"
                                                                max="100"
                                                                step="1"
                                                                value={value}
                                                                style={sliderStyle}
                                                                aria-label={t('weekly_survey.exercise_difficulty')}
                                                                onChange={(event) => {
                                                                    const nextValue = Number(event.target.value);
                                                                    setIntensityValues((current) => ({
                                                                        ...current,
                                                                        [key]: nextValue
                                                                    }));
                                                                }}
                                                            />
                                                            <div className="weekly-survey__scale">
                                                                <span>{t('weekly_survey.scale.easy')}</span>
                                                                <span>{t('weekly_survey.scale.hard')}</span>
                                                            </div>
                                                        </div>
                                                        <div className="weekly-survey__comment">
                                                            <button
                                                                type="button"
                                                                className="weekly-survey__comment-btn"
                                                                onClick={() =>
                                                                    setCommentOpen((current) => ({
                                                                        ...current,
                                                                        [key]: !isCommentOpen
                                                                    }))
                                                                }
                                                            >
                                                                {comment.length > 0
                                                                    ? t('weekly_survey.comment.edit')
                                                                    : t('weekly_survey.comment.add')}
                                                            </button>
                                                            {isCommentOpen && (
                                                                <textarea
                                                                    className="weekly-survey__comment-input"
                                                                    value={comment}
                                                                    placeholder={t('weekly_survey.comment.placeholder')}
                                                                    onChange={(event) => {
                                                                        const nextValue = event.target.value;
                                                                        setCommentValues((current) => ({
                                                                            ...current,
                                                                            [key]: nextValue
                                                                        }));
                                                                    }}
                                                                    rows={3}
                                                                />
                                                            )}
                                                        </div>
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    </section>
                                ))}
                            </div>
                        </div>

                        <div className="weekly-survey__footer">
                            <button
                                type="button"
                                className="button-ghost weekly-survey__skip"
                                onClick={handleSkipDay}
                                disabled={submitting}
                            >
                                {t('weekly_survey.skip_day')}
                            </button>
                            <button
                                type="button"
                                className="primary-button weekly-survey__next"
                                onClick={isLastDay ? handleSubmit : handleNext}
                                disabled={submitting}
                            >
                                {submitting ? t('weekly_survey.sending') : isLastDay ? t('weekly_survey.send') : t('weekly_survey.next_day')}
                            </button>
                        </div>
                    </>
                )}
            </div>
        </div>
    );
};

export default WeeklySurveyPage;
