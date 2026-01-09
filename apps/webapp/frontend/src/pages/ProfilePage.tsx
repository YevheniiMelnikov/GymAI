import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import TopBar from '../components/TopBar';
import BottomNav from '../components/BottomNav';
import { applyLang, t, type LangCode, type TranslationKey } from '../i18n/i18n';
import {
    closeWebApp,
    readInitData,
    readPreferredLocale,
    showBackButton,
    hideBackButton,
    onBackButtonClick,
    offBackButtonClick
} from '../telegram';
import { deleteProfile, getProfile, HttpError, updateProfile } from '../api/http';
import type {
    DietProduct,
    ProfileResp,
    ProfileUpdatePayload,
    WorkoutExperience,
    WorkoutLocation
} from '../api/types';

type EditableField =
    | 'weight'
    | 'height'
    | 'workout_experience'
    | 'workout_goals'
    | 'workout_location'
    | 'health_notes'
    | 'diet_allergies'
    | 'diet_products'
    | 'language';

type DraftState = {
    weight?: string;
    height?: string;
    workout_experience?: WorkoutExperience | '';
    workout_goals?: string;
    workout_location?: WorkoutLocation | '';
    health_notes?: string;
    diet_allergies?: string;
    diet_products?: DietProduct[];
    language?: string;
};

const DIET_PRODUCT_OPTIONS: Array<{ value: DietProduct; labelKey: TranslationKey }> = [
    { value: 'plant_food', labelKey: 'profile.diet_products.plant_food' },
    { value: 'meat', labelKey: 'profile.diet_products.meat' },
    { value: 'fish_seafood', labelKey: 'profile.diet_products.fish_seafood' },
    { value: 'eggs', labelKey: 'profile.diet_products.eggs' },
    { value: 'dairy', labelKey: 'profile.diet_products.dairy' },
];

const EXPERIENCE_OPTIONS: Array<{ value: WorkoutExperience; labelKey: TranslationKey }> = [
    { value: 'beginner', labelKey: 'profile.workout_experience.beginner' },
    { value: 'amateur', labelKey: 'profile.workout_experience.amateur' },
    { value: 'advanced', labelKey: 'profile.workout_experience.advanced' },
    { value: 'pro', labelKey: 'profile.workout_experience.pro' },
];

const LOCATION_OPTIONS: Array<{ value: WorkoutLocation; labelKey: TranslationKey }> = [
    { value: 'gym', labelKey: 'profile.workout_location.gym' },
    { value: 'home', labelKey: 'profile.workout_location.home' },
];

const LANGUAGE_OPTIONS: Array<{ value: string; labelKey: TranslationKey }> = [
    { value: 'ua', labelKey: 'profile.language.ua' },
    { value: 'ru', labelKey: 'profile.language.ru' },
    { value: 'eng', labelKey: 'profile.language.eng' },
];

const ProfilePage: React.FC = () => {
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const [lang, setLang] = useState<LangCode>('en');
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [profile, setProfile] = useState<ProfileResp | null>(null);
    const [editingField, setEditingField] = useState<EditableField | null>(null);
    const [view, setView] = useState<'list' | 'edit'>('list');
    const [draft, setDraft] = useState<DraftState>({});
    const [savingField, setSavingField] = useState<EditableField | null>(null);
    const [isDeleteOpen, setIsDeleteOpen] = useState(false);
    const [isDeleting, setIsDeleting] = useState(false);
    const [balancePressed, setBalancePressed] = useState(false);
    const [openDropdown, setOpenDropdown] = useState<'workout_experience' | 'workout_location' | 'language' | null>(null);
    const dropdownRef = useRef<HTMLDivElement>(null);
    const paramLang = searchParams.get('lang') || undefined;

    const initData = readInitData();

    const handleBack = useCallback(() => {
        if (view === 'edit') {
            setView('list');
            setEditingField(null);
            return;
        }
        closeWebApp();
        navigate(-1);
    }, [navigate, view]);

    useEffect(() => {
        const preferred = readPreferredLocale(paramLang);
        void applyLang(preferred).then((resolved) => setLang(resolved));
    }, [paramLang]);

    useEffect(() => {
        if (view !== 'edit') {
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
    }, [handleBack, view]);

    useEffect(() => {
        const controller = new AbortController();
        const fetchData = async () => {
            setLoading(true);
            setError(null);
            if (!initData) {
                setError(t('open_from_telegram'));
                setLoading(false);
                return;
            }
            try {
                const data = await getProfile(initData, controller.signal);
                const preferred = readPreferredLocale(paramLang);
                const appliedLang = await applyLang(data.language ?? preferred);
                setLang(appliedLang);
                setProfile(data);
            } catch (err) {
                const messageKey: TranslationKey = err instanceof HttpError ? (err.message as TranslationKey) : 'unexpected_error';
                setError(t(messageKey));
            } finally {
                setLoading(false);
            }
        };
        fetchData();
        return () => controller.abort();
    }, [initData, paramLang]);

    const startEdit = useCallback((field: EditableField) => {
        if (!profile) return;
        const nextDraft: DraftState = { ...draft };
        if (field === 'diet_products') {
            nextDraft.diet_products = profile.diet_products ?? [];
        } else if (field === 'language') {
            nextDraft.language = profile.language ?? '';
        } else if (field === 'weight') {
            nextDraft.weight = profile.weight !== null && profile.weight !== undefined ? String(profile.weight) : '';
        } else if (field === 'height') {
            nextDraft.height = profile.height !== null && profile.height !== undefined ? String(profile.height) : '';
        } else if (field === 'workout_experience') {
            nextDraft.workout_experience = profile.workout_experience ?? '';
        } else if (field === 'workout_location') {
            nextDraft.workout_location = profile.workout_location ?? '';
        } else if (field === 'workout_goals') {
            nextDraft.workout_goals = profile.workout_goals ?? '';
        } else if (field === 'health_notes') {
            nextDraft.health_notes = profile.health_notes ?? '';
        } else if (field === 'diet_allergies') {
            nextDraft.diet_allergies = profile.diet_allergies ?? '';
        }
        setDraft(nextDraft);
        setEditingField(field);
        setView('edit');
        setOpenDropdown(null);
    }, [draft, profile]);

    const stopEdit = useCallback(() => {
        setEditingField(null);
        setView('list');
        setOpenDropdown(null);
    }, []);

    const parseNumber = (value: string | undefined): number | null => {
        if (!value) return null;
        const parsed = Number.parseInt(value, 10);
        if (Number.isNaN(parsed)) {
            return null;
        }
        return parsed;
    };

    const handleSave = useCallback(async () => {
        if (!editingField || !profile) {
            return;
        }
        if (!initData) {
            setError(t('open_from_telegram'));
            return;
        }
        const payload: ProfileUpdatePayload = {};

        if (editingField === 'weight') {
            const parsed = parseNumber(draft.weight);
            if (draft.weight && parsed === null) {
                setError(t('profile.error.invalid_number'));
                return;
            }
            payload.weight = parsed;
        } else if (editingField === 'height') {
            const parsed = parseNumber(draft.height);
            if (draft.height && parsed === null) {
                setError(t('profile.error.invalid_number'));
                return;
            }
            payload.height = parsed;
        } else if (editingField === 'workout_experience') {
            payload.workout_experience = draft.workout_experience ? draft.workout_experience : null;
        } else if (editingField === 'workout_location') {
            payload.workout_location = draft.workout_location ? draft.workout_location : null;
        } else if (editingField === 'workout_goals') {
            payload.workout_goals = draft.workout_goals ? draft.workout_goals.trim() : null;
        } else if (editingField === 'health_notes') {
            payload.health_notes = draft.health_notes ? draft.health_notes.trim() : null;
        } else if (editingField === 'diet_allergies') {
            payload.diet_allergies = draft.diet_allergies ? draft.diet_allergies.trim() : null;
        } else if (editingField === 'diet_products') {
            payload.diet_products = draft.diet_products ?? [];
        } else if (editingField === 'language') {
            payload.language = draft.language ? draft.language : null;
        }

        setSavingField(editingField);
        setError(null);
        try {
            const updated = await updateProfile(payload, initData);
            setProfile(updated);
            if (editingField === 'language' && updated.language) {
                const appliedLang = await applyLang(updated.language);
                setLang(appliedLang);
            }
            setEditingField(null);
            setView('list');
            setOpenDropdown(null);
        } catch (err) {
            const messageKey: TranslationKey = err instanceof HttpError ? (err.message as TranslationKey) : 'unexpected_error';
            setError(t(messageKey));
        } finally {
            setSavingField(null);
        }
    }, [draft, editingField, initData, profile]);

    const handleBalance = useCallback(async () => {
        if (!initData) {
            setError(t('open_from_telegram'));
            return;
        }
        setBalancePressed(true);
        window.setTimeout(() => setBalancePressed(false), 180);
        const query = new URLSearchParams(searchParams);
        if (!query.get('lang')) {
            query.set('lang', lang);
        }
        const queryString = query.toString();
        navigate(queryString ? `/topup?${queryString}` : '/topup');
    }, [initData, lang, navigate, searchParams]);

    const handleDelete = useCallback(async () => {
        if (!initData) {
            setError(t('open_from_telegram'));
            return;
        }
        setIsDeleting(true);
        try {
            await deleteProfile(initData);
            closeWebApp();
        } catch (err) {
            const messageKey: TranslationKey = err instanceof HttpError ? (err.message as TranslationKey) : 'unexpected_error';
            setError(t(messageKey));
        } finally {
            setIsDeleting(false);
            setIsDeleteOpen(false);
        }
    }, [initData]);

    const renderValue = (value: string | number | null | undefined, unitKey?: TranslationKey): string => {
        if (value === null || value === undefined || value === '') {
            return t('profile.empty');
        }
        if (unitKey) {
            return `${value} ${t(unitKey)}`;
        }
        return String(value);
    };

    const experienceLabel = useMemo(() => {
        if (!profile?.workout_experience) {
            return t('profile.empty');
        }
        const option = EXPERIENCE_OPTIONS.find((item) => item.value === profile.workout_experience);
        return option ? t(option.labelKey) : profile.workout_experience;
    }, [profile]);

    const locationLabel = useMemo(() => {
        if (!profile?.workout_location) {
            return t('profile.empty');
        }
        const option = LOCATION_OPTIONS.find((item) => item.value === profile.workout_location);
        return option ? t(option.labelKey) : profile.workout_location;
    }, [profile]);

    const languageLabel = useMemo(() => {
        if (!profile?.language) {
            return t('profile.empty');
        }
        const option = LANGUAGE_OPTIONS.find((item) => item.value === profile.language);
        return option ? t(option.labelKey) : profile.language;
    }, [profile]);

    const dietLabel = useMemo(() => {
        if (!profile?.diet_products || profile.diet_products.length === 0) {
            return t('profile.empty');
        }
        return profile.diet_products
            .map((item) => {
                const option = DIET_PRODUCT_OPTIONS.find((entry) => entry.value === item);
                return option ? t(option.labelKey) : item;
            })
            .join(', ');
    }, [profile]);

    const renderActions = (field: EditableField) => (
        <div className="profile-edit__actions">
            <button
                type="button"
                className="button-ghost"
                onClick={stopEdit}
                disabled={savingField === field}
            >
                {t('profile.cancel')}
            </button>
            <button
                type="button"
                className="primary-button"
                onClick={handleSave}
                disabled={savingField === field}
            >
                {savingField === field ? t('program.exercise.edit_dialog.saving') : t('profile.save')}
            </button>
        </div>
    );

    const resolveDropdownLabel = useCallback(
        (
            value: WorkoutExperience | WorkoutLocation | string | '' | null | undefined,
            options: Array<{ value: WorkoutExperience | WorkoutLocation | string; labelKey: TranslationKey }>
        ) => {
            if (!value) {
                return t('profile.empty');
            }
            const option = options.find((item) => item.value === value);
            return option ? t(option.labelKey) : value;
        },
        []
    );

    useEffect(() => {
        if (!openDropdown) return;
        const handleClickOutside = (event: MouseEvent) => {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
                setOpenDropdown(null);
            }
        };
        const handleEscape = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setOpenDropdown(null);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        document.addEventListener('keydown', handleEscape);
        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
            document.removeEventListener('keydown', handleEscape);
        };
    }, [openDropdown]);

    return (
        <div className="page-container with-bottom-nav" data-lang={lang}>
            <TopBar
                title={view === 'edit' ? t('profile.edit') : t('profile.title')}
                onBack={view === 'edit' ? handleBack : undefined}
            />

            <main className="page-shell">
                {view === 'list' && (
                    <section className="profile-balance">
                        <div className="profile-balance__header">
                            <div>
                                <p className="profile-balance__title">{t('profile.balance.title')}</p>
                                <p className="profile-balance__value">
                                    {t('profile.balance.label', { count: profile?.credits ?? 0 })}
                                </p>
                            </div>
                            <button
                                type="button"
                                className={`primary-button profile-balance__button ${balancePressed ? 'is-pressed' : ''}`}
                                onClick={handleBalance}
                            >
                                {t('profile.balance.topup')}
                            </button>
                        </div>
                    </section>
                )}

                {error && <div className="error-block">{error}</div>}

                <section className="profile-flow" data-view={view} aria-busy={loading}>
                    <div className="profile-flow__track">
                        <div className="profile-pane profile-pane--list">
                            <div className="profile-list">
                                <button type="button" className="profile-row" onClick={() => startEdit('workout_goals')}>
                                    <div>
                                        <p className="profile-row__label">{t('profile.field.workout_goals')}</p>
                                        <p className="profile-row__value">{renderValue(profile?.workout_goals)}</p>
                                    </div>
                                    <span className="profile-row__chevron" aria-hidden="true">
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
                                <button type="button" className="profile-row" onClick={() => startEdit('workout_location')}>
                                    <div>
                                        <p className="profile-row__label">{t('profile.field.workout_location')}</p>
                                        <p className="profile-row__value">{locationLabel}</p>
                                    </div>
                                    <span className="profile-row__chevron" aria-hidden="true">
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
                                <button type="button" className="profile-row" onClick={() => startEdit('weight')}>
                                    <div>
                                        <p className="profile-row__label">{t('profile.field.weight')}</p>
                                        <p className="profile-row__value">
                                            {renderValue(profile?.weight ?? null, 'profile.unit.kg')}
                                        </p>
                                    </div>
                                    <span className="profile-row__chevron" aria-hidden="true">
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
                                <button type="button" className="profile-row" onClick={() => startEdit('height')}>
                                    <div>
                                        <p className="profile-row__label">{t('profile.field.height')}</p>
                                        <p className="profile-row__value">
                                            {renderValue(profile?.height ?? null, 'profile.unit.cm')}
                                        </p>
                                    </div>
                                    <span className="profile-row__chevron" aria-hidden="true">
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
                                <button type="button" className="profile-row" onClick={() => startEdit('workout_experience')}>
                                    <div>
                                        <p className="profile-row__label">{t('profile.field.workout_experience')}</p>
                                        <p className="profile-row__value">{experienceLabel}</p>
                                    </div>
                                    <span className="profile-row__chevron" aria-hidden="true">
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
                                <button type="button" className="profile-row" onClick={() => startEdit('health_notes')}>
                                    <div>
                                        <p className="profile-row__label">{t('profile.field.health_notes')}</p>
                                        <p className="profile-row__value">{renderValue(profile?.health_notes)}</p>
                                    </div>
                                    <span className="profile-row__chevron" aria-hidden="true">
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
                                <button type="button" className="profile-row" onClick={() => startEdit('diet_allergies')}>
                                    <div>
                                        <p className="profile-row__label">{t('profile.field.diet_allergies')}</p>
                                        <p className="profile-row__value">{renderValue(profile?.diet_allergies)}</p>
                                    </div>
                                    <span className="profile-row__chevron" aria-hidden="true">
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
                                <button type="button" className="profile-row" onClick={() => startEdit('diet_products')}>
                                    <div>
                                        <p className="profile-row__label">{t('profile.field.diet_products')}</p>
                                        <p className="profile-row__value">{dietLabel}</p>
                                    </div>
                                    <span className="profile-row__chevron" aria-hidden="true">
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
                                <button type="button" className="profile-row" onClick={() => startEdit('language')}>
                                    <div>
                                        <p className="profile-row__label">{t('profile.field.language')}</p>
                                        <p className="profile-row__value">{languageLabel}</p>
                                    </div>
                                    <span className="profile-row__chevron" aria-hidden="true">
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
                            </div>
                        </div>
                        <div className="profile-pane profile-pane--edit">
                            {editingField && (
                                <div className="profile-edit">
                                    <p className="profile-edit__title">{t(`profile.field.${editingField}` as TranslationKey)}</p>
                                    {editingField === 'weight' && (
                                        <>
                                            <input
                                                type="number"
                                                inputMode="numeric"
                                                className="profile-edit__input"
                                                value={draft.weight ?? ''}
                                                onChange={(event) => setDraft((prev) => ({ ...prev, weight: event.target.value }))}
                                                placeholder={t('profile.field.weight')}
                                            />
                                            {renderActions('weight')}
                                        </>
                                    )}
                                    {editingField === 'height' && (
                                        <>
                                            <input
                                                type="number"
                                                inputMode="numeric"
                                                className="profile-edit__input"
                                                value={draft.height ?? ''}
                                                onChange={(event) => setDraft((prev) => ({ ...prev, height: event.target.value }))}
                                                placeholder={t('profile.field.height')}
                                            />
                                            {renderActions('height')}
                                        </>
                                    )}
                                    {editingField === 'workout_experience' && (
                                        <>
                                            <div className="sort-menu profile-select" ref={dropdownRef}>
                                                <button
                                                    type="button"
                                                    className="sort-trigger profile-select__trigger"
                                                    onClick={() =>
                                                        setOpenDropdown((prev) =>
                                                            prev === 'workout_experience' ? null : 'workout_experience'
                                                        )
                                                    }
                                                >
                                                    <span>
                                                        {resolveDropdownLabel(
                                                            draft.workout_experience ?? profile?.workout_experience,
                                                            EXPERIENCE_OPTIONS
                                                        )}
                                                    </span>
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
                                                {openDropdown === 'workout_experience' && (
                                                    <div className="sort-dropdown profile-select__dropdown" role="listbox">
                                                        <button
                                                            type="button"
                                                            className={`sort-option ${
                                                                !(draft.workout_experience ?? profile?.workout_experience) ? 'is-active' : ''
                                                            }`}
                                                            onClick={() => {
                                                                setDraft((prev) => ({ ...prev, workout_experience: '' }));
                                                                setOpenDropdown(null);
                                                            }}
                                                        >
                                                            {t('profile.empty')}
                                                        </button>
                                                        {EXPERIENCE_OPTIONS.map((item) => (
                                                            <button
                                                                key={item.value}
                                                                type="button"
                                                                className={`sort-option ${
                                                                    (draft.workout_experience ?? profile?.workout_experience) === item.value
                                                                        ? 'is-active'
                                                                        : ''
                                                                }`}
                                                                onClick={() => {
                                                                    setDraft((prev) => ({ ...prev, workout_experience: item.value }));
                                                                    setOpenDropdown(null);
                                                                }}
                                                            >
                                                                {t(item.labelKey)}
                                                            </button>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                            {renderActions('workout_experience')}
                                        </>
                                    )}
                                    {editingField === 'workout_location' && (
                                        <>
                                            <div className="sort-menu profile-select" ref={dropdownRef}>
                                                <button
                                                    type="button"
                                                    className="sort-trigger profile-select__trigger"
                                                    onClick={() =>
                                                        setOpenDropdown((prev) =>
                                                            prev === 'workout_location' ? null : 'workout_location'
                                                        )
                                                    }
                                                >
                                                    <span>
                                                        {resolveDropdownLabel(
                                                            draft.workout_location ?? profile?.workout_location,
                                                            LOCATION_OPTIONS
                                                        )}
                                                    </span>
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
                                                {openDropdown === 'workout_location' && (
                                                    <div className="sort-dropdown profile-select__dropdown" role="listbox">
                                                        <button
                                                            type="button"
                                                            className={`sort-option ${
                                                                !(draft.workout_location ?? profile?.workout_location) ? 'is-active' : ''
                                                            }`}
                                                            onClick={() => {
                                                                setDraft((prev) => ({ ...prev, workout_location: '' }));
                                                                setOpenDropdown(null);
                                                            }}
                                                        >
                                                            {t('profile.empty')}
                                                        </button>
                                                        {LOCATION_OPTIONS.map((item) => (
                                                            <button
                                                                key={item.value}
                                                                type="button"
                                                                className={`sort-option ${
                                                                    (draft.workout_location ?? profile?.workout_location) === item.value
                                                                        ? 'is-active'
                                                                        : ''
                                                                }`}
                                                                onClick={() => {
                                                                    setDraft((prev) => ({ ...prev, workout_location: item.value }));
                                                                    setOpenDropdown(null);
                                                                }}
                                                            >
                                                                {t(item.labelKey)}
                                                            </button>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                            {renderActions('workout_location')}
                                        </>
                                    )}
                                    {editingField === 'workout_goals' && (
                                        <>
                                            <textarea
                                                className="profile-edit__input profile-edit__textarea"
                                                rows={4}
                                                value={draft.workout_goals ?? ''}
                                                onChange={(event) => setDraft((prev) => ({ ...prev, workout_goals: event.target.value }))}
                                                placeholder={t('profile.field.workout_goals')}
                                            />
                                            {renderActions('workout_goals')}
                                        </>
                                    )}
                                    {editingField === 'health_notes' && (
                                        <>
                                            <textarea
                                                className="profile-edit__input profile-edit__textarea"
                                                rows={4}
                                                value={draft.health_notes ?? ''}
                                                onChange={(event) => setDraft((prev) => ({ ...prev, health_notes: event.target.value }))}
                                                placeholder={t('profile.field.health_notes')}
                                            />
                                            {renderActions('health_notes')}
                                        </>
                                    )}
                                    {editingField === 'diet_allergies' && (
                                        <>
                                            <textarea
                                                className="profile-edit__input profile-edit__textarea"
                                                rows={4}
                                                value={draft.diet_allergies ?? ''}
                                                onChange={(event) => setDraft((prev) => ({ ...prev, diet_allergies: event.target.value }))}
                                                placeholder={t('profile.field.diet_allergies')}
                                            />
                                            {renderActions('diet_allergies')}
                                        </>
                                    )}
                                    {editingField === 'diet_products' && (
                                        <>
                                            <div className="profile-checklist">
                                                {DIET_PRODUCT_OPTIONS.map((item) => {
                                                    const selected = draft.diet_products ?? [];
                                                    const isChecked = selected.includes(item.value);
                                                    return (
                                                        <label key={item.value} className="profile-checklist__item">
                                                            <input
                                                                type="checkbox"
                                                                checked={isChecked}
                                                                onChange={() => {
                                                                    setDraft((prev) => {
                                                                        const current = prev.diet_products ?? [];
                                                                        const next = current.includes(item.value)
                                                                            ? current.filter((value) => value !== item.value)
                                                                            : [...current, item.value];
                                                                        return { ...prev, diet_products: next };
                                                                    });
                                                                }}
                                                            />
                                                            <span>{t(item.labelKey)}</span>
                                                        </label>
                                                    );
                                                })}
                                            </div>
                                            {renderActions('diet_products')}
                                        </>
                                    )}
                                    {editingField === 'language' && (
                                        <>
                                            <div className="sort-menu profile-select" ref={dropdownRef}>
                                                <button
                                                    type="button"
                                                    className="sort-trigger profile-select__trigger"
                                                    onClick={() => setOpenDropdown((prev) => (prev === 'language' ? null : 'language'))}
                                                >
                                                    <span>
                                                        {resolveDropdownLabel(
                                                            draft.language ?? profile?.language,
                                                            LANGUAGE_OPTIONS
                                                        )}
                                                    </span>
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
                                                {openDropdown === 'language' && (
                                                    <div className="sort-dropdown profile-select__dropdown" role="listbox">
                                                        {LANGUAGE_OPTIONS.map((item) => (
                                                            <button
                                                                key={item.value}
                                                                type="button"
                                                                className={`sort-option ${
                                                                    (draft.language ?? profile?.language) === item.value ? 'is-active' : ''
                                                                }`}
                                                                onClick={() => {
                                                                    setDraft((prev) => ({ ...prev, language: item.value }));
                                                                    setOpenDropdown(null);
                                                                }}
                                                            >
                                                                {t(item.labelKey)}
                                                            </button>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                            {renderActions('language')}
                                        </>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                </section>

                {view === 'list' && (
                    <section className="profile-danger">
                        <button
                            type="button"
                            className="profile-danger__button"
                            onClick={() => setIsDeleteOpen(true)}
                        >
                            {t('profile.delete.button')}
                        </button>
                    </section>
                )}
            </main>
            <BottomNav />

            {isDeleteOpen && (
                <div className="subscription-confirm" onClick={() => setIsDeleteOpen(false)}>
                    <div
                        className="subscription-confirm__dialog"
                        onClick={(event) => event.stopPropagation()}
                    >
                        <h3 className="subscription-confirm__title">{t('profile.delete.title')}</h3>
                        <p className="subscription-confirm__body">{t('profile.delete.body')}</p>
                        <div className="subscription-confirm__actions">
                            <button
                                type="button"
                                className="subscription-confirm__btn subscription-confirm__btn--cancel"
                                onClick={() => setIsDeleteOpen(false)}
                                disabled={isDeleting}
                            >
                                {t('profile.cancel')}
                            </button>
                            <button
                                type="button"
                                className="subscription-confirm__btn subscription-confirm__btn--confirm"
                                onClick={handleDelete}
                                disabled={isDeleting}
                            >
                                {isDeleting ? t('program.exercise.edit_dialog.saving') : t('profile.delete.confirm')}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default ProfilePage;
