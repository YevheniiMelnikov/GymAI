import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import TopBar from '../components/TopBar';
import BottomNav from '../components/BottomNav';
import { applyLang, LANG_CHANGED_EVENT, t, type TranslationKey } from '../i18n/i18n';
import { HttpError, initPayment } from '../api/http';
import {
    closeWebApp,
    hideBackButton,
    offBackButtonClick,
    onBackButtonClick,
    openTelegramLink,
    readInitData,
    readLocale,
    showBackButton,
} from '../telegram';

const STATIC_PREFIX = ((window as any).__STATIC_PREFIX__ as string | undefined) ?? '/static/';

type PackageCard = {
    id: 'start' | 'optimum' | 'max';
    src: string;
};

const PACKAGES: PackageCard[] = [
    { id: 'start', src: `${STATIC_PREFIX}images/pricing/start.png` },
    { id: 'optimum', src: `${STATIC_PREFIX}images/pricing/optimum.png` },
    { id: 'max', src: `${STATIC_PREFIX}images/pricing/max.png` },
];

const DEFAULT_INDEX = 1;

const TopupPage: React.FC = () => {
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const paramLang = searchParams.get('lang') || undefined;
    const viewportRef = useRef<HTMLDivElement>(null);
    const cardRefs = useRef<Array<HTMLDivElement | null>>([]);

    const [activeIndex, setActiveIndex] = useState(DEFAULT_INDEX);
    const activeIndexRef = useRef(activeIndex);
    const initDoneRef = useRef(false);
    const hapticEnabledRef = useRef(false);
    const [loadedCount, setLoadedCount] = useState(0);
    const dotsRef = useRef<HTMLDivElement>(null);
    const ctaRef = useRef<HTMLDivElement>(null);
    const dotsTopRef = useRef<number | null>(null);
    const [dotsTop, setDotsTop] = useState<number | null>(null);
    const pointerStartRef = useRef<{ x: number; y: number } | null>(null);
    const pointerMovedRef = useRef(false);
    const swipeStartRef = useRef<{ x: number; y: number } | null>(null);
    const swipeStartIndexRef = useRef<number | null>(null);
    const [paying, setPaying] = useState(false);
    const [payError, setPayError] = useState<string | null>(null);

    const [, setLangCode] = useState<string | null>(null);
    const lockedLang = useMemo(() => {
        let stored: string | null = null;
        try {
            stored = window.sessionStorage.getItem('app:lang');
        } catch {
        }
        const docLang = document.documentElement.lang || undefined;
        return paramLang ?? stored ?? docLang ?? readLocale();
    }, [paramLang]);

    useEffect(() => {
        void applyLang(lockedLang).then((resolved) => {
            setLangCode(resolved);
        });
    }, [lockedLang]);

    useEffect(() => {
        const handleLangChange = () => {
            if (document.documentElement.lang !== lockedLang) {
                void applyLang(lockedLang).then((resolved) => {
                    setLangCode(resolved);
                });
            } else {
                setLangCode(lockedLang);
            }
        };
        window.addEventListener(LANG_CHANGED_EVENT, handleLangChange);
        return () => {
            window.removeEventListener(LANG_CHANGED_EVENT, handleLangChange);
        };
    }, [lockedLang]);

    const cards = useMemo(() => PACKAGES, []);

    useEffect(() => {
        activeIndexRef.current = activeIndex;
    }, [activeIndex]);

    useEffect(() => {
        if (!initDoneRef.current || !hapticEnabledRef.current) {
            return;
        }
        try {
            const tg = (window as any).Telegram?.WebApp;
            tg?.HapticFeedback?.selectionChanged?.();
        } catch {
        }
    }, [activeIndex]);

    const scrollToIndex = useCallback((index: number, behavior: ScrollBehavior) => {
        const viewport = viewportRef.current;
        const card = cardRefs.current[index];
        if (!viewport || !card) {
            return false;
        }
        const target = card.offsetLeft - (viewport.clientWidth - card.clientWidth) / 2;
        const maxScroll = Math.max(0, viewport.scrollWidth - viewport.clientWidth);
        const next = Math.max(0, Math.min(target, maxScroll));
        try {
            viewport.scrollTo({ left: next, behavior });
        } catch {
            viewport.scrollLeft = next;
        }
        return true;
    }, []);

    const trySetDefault = useCallback(() => {
        const viewport = viewportRef.current;
        const card = cardRefs.current[DEFAULT_INDEX];
        if (!viewport || !card) {
            return false;
        }
        const scrolled = scrollToIndex(DEFAULT_INDEX, 'auto');
        if (!scrolled) {
            return false;
        }
        if (!initDoneRef.current) {
            setActiveIndex(DEFAULT_INDEX);
            activeIndexRef.current = DEFAULT_INDEX;
            initDoneRef.current = true;
        }
        return true;
    }, [scrollToIndex]);

    const measure = useCallback(() => {
        if (!initDoneRef.current) {
            trySetDefault();
            return;
        }
        scrollToIndex(activeIndexRef.current, 'auto');
    }, [scrollToIndex, trySetDefault]);

    const updateDotsPosition = useCallback(() => {
        const viewport = viewportRef.current;
        const dots = dotsRef.current;
        const cta = ctaRef.current;
        const activeCard = cardRefs.current[activeIndexRef.current];
        if (!viewport || !dots || !cta || !activeCard) {
            return;
        }
        const cardRect = activeCard.getBoundingClientRect();
        const ctaRect = cta.getBoundingClientRect();
        const dotsRect = dots.getBoundingClientRect();
        const center = cardRect.bottom + (ctaRect.top - cardRect.bottom) * 0.35;
        const minTop = cardRect.bottom + 2;
        const maxTop = ctaRect.top - dotsRect.height - 8;
        let nextTop = center - dotsRect.height / 2;
        if (maxTop >= minTop) {
            nextTop = Math.min(Math.max(nextTop, minTop), maxTop);
        } else {
            nextTop = Math.max(0, maxTop);
        }
        nextTop = Math.max(0, nextTop);
        if (dotsTopRef.current !== null && Math.abs(nextTop - dotsTopRef.current) < 0.5) {
            return;
        }
        dotsTopRef.current = nextTop;
        setDotsTop(nextTop);
    }, []);

    useEffect(() => {
        let frame: number | null = null;
        let attempts = 0;
        const tick = () => {
            if (initDoneRef.current) {
                return;
            }
            if (trySetDefault()) {
                return;
            }
            attempts += 1;
            if (attempts < 12) {
                frame = window.requestAnimationFrame(tick);
            }
        };
        frame = window.requestAnimationFrame(tick);
        return () => {
            if (frame !== null) {
                window.cancelAnimationFrame(frame);
            }
        };
    }, [trySetDefault]);

    useEffect(() => {
        if (loadedCount < cards.length) {
            return;
        }
        if (!initDoneRef.current) {
            trySetDefault();
            window.setTimeout(() => {
                if (!initDoneRef.current) {
                    trySetDefault();
                }
            }, 120);
        }
        measure();
    }, [cards.length, loadedCount, measure, trySetDefault]);

    useEffect(() => {
        const handleResize = () => measure();
        window.addEventListener('resize', handleResize);
        return () => {
            window.removeEventListener('resize', handleResize);
        };
    }, [measure]);

    useEffect(() => {
        const main = document.querySelector('main#app') as HTMLElement | null;
        const prevBodyOverflow = document.body.style.overflow;
        const prevHtmlOverflow = document.documentElement.style.overflow;
        const prevBodyPosition = document.body.style.position;
        const prevBodyWidth = document.body.style.width;
        const prevBodyHeight = document.body.style.height;
        const prevMainOverflow = main?.style.overflow ?? '';
        document.body.style.overflow = 'hidden';
        document.documentElement.style.overflow = 'hidden';
        document.body.style.position = 'fixed';
        document.body.style.width = '100%';
        document.body.style.height = '100%';
        if (main) {
            main.style.overflow = 'hidden';
        }
        return () => {
            document.body.style.overflow = prevBodyOverflow;
            document.documentElement.style.overflow = prevHtmlOverflow;
            document.body.style.position = prevBodyPosition;
            document.body.style.width = prevBodyWidth;
            document.body.style.height = prevBodyHeight;
            if (main) {
                main.style.overflow = prevMainOverflow;
            }
        };
    }, []);

    useEffect(() => {
        let frame: number | null = null;
        const schedule = () => {
            if (frame !== null) {
                return;
            }
            frame = window.requestAnimationFrame(() => {
                frame = null;
                updateDotsPosition();
            });
        };
        schedule();
        window.addEventListener('resize', schedule);
        window.addEventListener('scroll', schedule, { passive: true });
        return () => {
            window.removeEventListener('resize', schedule);
            window.removeEventListener('scroll', schedule);
            if (frame !== null) {
                window.cancelAnimationFrame(frame);
            }
        };
    }, [updateDotsPosition]);

    useEffect(() => {
        updateDotsPosition();
    }, [activeIndex, updateDotsPosition]);


    const ensureLang = useCallback(() => {
        if (document.documentElement.lang !== lockedLang) {
            void applyLang(lockedLang);
        }
    }, [lockedLang]);

    const handleDotClick = useCallback(
        (index: number) => {
            ensureLang();
            initDoneRef.current = true;
            hapticEnabledRef.current = true;
            setActiveIndex(index);
            scrollToIndex(index, 'auto');
        },
        [ensureLang, scrollToIndex]
    );

    const handleCardClick = useCallback(
        (index: number) => {
            ensureLang();
            initDoneRef.current = true;
            hapticEnabledRef.current = true;
            setActiveIndex(index);
            scrollToIndex(index, 'auto');
        },
        [ensureLang, scrollToIndex]
    );

    const handleCardPointerDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
        pointerStartRef.current = { x: event.clientX, y: event.clientY };
        pointerMovedRef.current = false;
    }, []);

    const handleCardPointerMove = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
        const start = pointerStartRef.current;
        if (!start) {
            return;
        }
        const dx = Math.abs(event.clientX - start.x);
        const dy = Math.abs(event.clientY - start.y);
        if (dx > 8 || dy > 8) {
            pointerMovedRef.current = true;
        }
    }, []);

    const handleCardPointerUp = useCallback(
        (index: number, event: React.PointerEvent<HTMLDivElement>) => {
            const start = pointerStartRef.current;
            pointerStartRef.current = null;
            if (!start) {
                handleCardClick(index);
                return;
            }
            const dx = Math.abs(event.clientX - start.x);
            const dy = Math.abs(event.clientY - start.y);
            if (dx <= 8 && dy <= 8 && !pointerMovedRef.current) {
                handleCardClick(index);
            }
            pointerMovedRef.current = false;
        },
        [handleCardClick]
    );

    const handleViewportPointerDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
        swipeStartRef.current = { x: event.clientX, y: event.clientY };
        swipeStartIndexRef.current = activeIndexRef.current;
    }, []);

    const handleViewportPointerUp = useCallback(
        (event: React.PointerEvent<HTMLDivElement>) => {
            const start = swipeStartRef.current;
            const startIndex = swipeStartIndexRef.current;
            swipeStartRef.current = null;
            swipeStartIndexRef.current = null;
            if (!start || startIndex === null) {
                return;
            }
            const dx = event.clientX - start.x;
            const dy = event.clientY - start.y;
            if (Math.abs(dx) <= 18 || Math.abs(dx) <= Math.abs(dy)) {
                return;
            }
            const direction = dx > 0 ? -1 : 1;
            const targetIndex = Math.max(0, Math.min(cards.length - 1, startIndex + direction));
            if (targetIndex === startIndex) {
                return;
            }
            ensureLang();
            initDoneRef.current = true;
            hapticEnabledRef.current = true;
            setActiveIndex(targetIndex);
            scrollToIndex(targetIndex, 'auto');
        },
        [cards.length, ensureLang, scrollToIndex]
    );

    const handleViewportClick = useCallback(
        (event: React.MouseEvent<HTMLDivElement>) => {
            const viewport = viewportRef.current;
            if (!viewport) {
                return;
            }
            const x = event.clientX;
            let closestIndex = 0;
            let closestDistance = Number.POSITIVE_INFINITY;
            cardRefs.current.forEach((card, index) => {
                if (!card) {
                    return;
                }
                const rect = card.getBoundingClientRect();
                const center = rect.left + rect.width / 2;
                const distance = Math.abs(center - x);
                if (distance < closestDistance) {
                    closestDistance = distance;
                    closestIndex = index;
                }
            });
            handleCardClick(closestIndex);
        },
        [handleCardClick]
    );

    const handlePayClick = useCallback(async () => {
        const selected = cards[activeIndex] ?? cards[DEFAULT_INDEX];
        if (!selected || paying) {
            return;
        }
        const initData = readInitData();
        if (!initData) {
            setPayError(t('open_from_telegram'));
            return;
        }
        setPaying(true);
        setPayError(null);
        try {
            const payment = await initPayment(selected.id, initData);
            openTelegramLink(payment.checkoutUrl);
            closeWebApp();
        } catch (err) {
            const messageKey: TranslationKey = err instanceof HttpError ? (err.message as TranslationKey) : 'payment.unavailable';
            setPayError(t(messageKey));
        } finally {
            setPaying(false);
        }
    }, [activeIndex, cards, paying]);

    const handleSystemBack = useCallback(() => {
        const query = searchParams.toString();
        navigate(query ? `/profile?${query}` : '/profile');
    }, [navigate, searchParams]);

    useEffect(() => {
        showBackButton();
        onBackButtonClick(handleSystemBack);
        return () => {
            offBackButtonClick(handleSystemBack);
            hideBackButton();
        };
    }, [handleSystemBack]);

    return (
        <div className="page-container with-bottom-nav topup-page">
            <TopBar title={t('topup.title')} />
            <main className="page-shell topup-page-shell">
                <section className="topup-shell">
                    <div
                        className="topup-carousel"
                        ref={viewportRef}
                        onPointerDown={() => {
                            hapticEnabledRef.current = true;
                        }}
                        onPointerDownCapture={handleViewportPointerDown}
                        onPointerUp={handleViewportPointerUp}
                        onPointerCancel={() => {
                            swipeStartRef.current = null;
                            swipeStartIndexRef.current = null;
                        }}
                        onClick={handleViewportClick}
                    >
                        {cards.map((card, index) => (
                            <div
                                className={`topup-carousel__card ${index === activeIndex ? 'is-active' : ''}`}
                                key={card.id}
                                data-index={index}
                                data-id={card.id}
                                role="button"
                                tabIndex={0}
                                onPointerDown={handleCardPointerDown}
                                onPointerMove={handleCardPointerMove}
                                onPointerUp={(event) => handleCardPointerUp(index, event)}
                                onPointerCancel={() => {
                                    pointerStartRef.current = null;
                                    pointerMovedRef.current = false;
                                }}
                                onClick={() => handleCardClick(index)}
                                onKeyDown={(event) => {
                                    if (event.key === 'Enter' || event.key === ' ') {
                                        event.preventDefault();
                                        handleCardClick(index);
                                    }
                                }}
                                ref={(node) => {
                                    cardRefs.current[index] = node;
                                }}
                            >
                                <img
                                    className="topup-carousel__image"
                                    src={card.src}
                                    alt=""
                                    aria-hidden="true"
                                    draggable={false}
                                    onLoad={() => {
                                        setLoadedCount((prev) => Math.min(cards.length, prev + 1));
                                        measure();
                                        updateDotsPosition();
                                    }}
                                />
                            </div>
                        ))}
                    </div>

                    <div
                        className="topup-carousel__dots"
                        role="tablist"
                        aria-label={t('topup.title')}
                        ref={dotsRef}
                        style={dotsTop === null ? undefined : { top: `${dotsTop}px` }}
                    >
                        {cards.map((item, index) => (
                            <button
                                key={item.id}
                                type="button"
                                className={`topup-carousel__dot ${index === activeIndex ? 'is-active' : ''}`}
                                onClick={() => handleDotClick(index)}
                                aria-label={`${index + 1}`}
                                aria-current={index === activeIndex ? 'true' : undefined}
                            />
                        ))}
                    </div>

                    <div className="topup-cta" ref={ctaRef}>
                        {payError && <div className="error-block">{payError}</div>}
                        <button
                            type="button"
                            className="primary-button topup-pay"
                            onClick={handlePayClick}
                            disabled={paying}
                        >
                            {t('topup.pay')}
                        </button>
                    </div>
                </section>
            </main>
            <BottomNav activeKey="profile" />
        </div>
    );
};

export default TopupPage;
