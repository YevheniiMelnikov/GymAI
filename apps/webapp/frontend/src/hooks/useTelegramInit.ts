import { useEffect } from 'react';

import { tmeDisableVerticalSwipes, tmeEnterFullscreen, tmeExpand, tmeForceDarkTheme } from '../telegram';

export const useTelegramInit = (): void => {
    useEffect(() => {
        tmeForceDarkTheme();
        tmeEnterFullscreen();
        const timer = window.setTimeout(() => {
            tmeExpand();
        }, 120);

        const refreshTheme = (): void => {
            tmeForceDarkTheme();
        };

        const handleVisibilityChange = (): void => {
            if (document.visibilityState === 'visible') {
                refreshTheme();
            }
        };

        const handleFirstInteraction = (): void => {
            refreshTheme();
            tmeEnterFullscreen();
            tmeDisableVerticalSwipes();
        };

        document.addEventListener('click', handleFirstInteraction, { once: true, passive: true });
        document.addEventListener('touchstart', handleFirstInteraction, { once: true, passive: true });
        document.addEventListener('visibilitychange', handleVisibilityChange);
        window.addEventListener('pageshow', refreshTheme);
        window.addEventListener('focus', refreshTheme);

        return () => {
            window.clearTimeout(timer);
            document.removeEventListener('click', handleFirstInteraction);
            document.removeEventListener('touchstart', handleFirstInteraction);
            document.removeEventListener('visibilitychange', handleVisibilityChange);
            window.removeEventListener('pageshow', refreshTheme);
            window.removeEventListener('focus', refreshTheme);
        };
    }, []);

    useEffect(() => {
        const viewport = window.visualViewport;
        if (!viewport) {
            return;
        }

        const updateKeyboardState = () => {
            const ratio = viewport.height / window.innerHeight;
            const isKeyboardOpen = ratio < 0.8;
            if (isKeyboardOpen) {
                document.body.dataset.keyboard = 'open';
            } else {
                delete document.body.dataset.keyboard;
            }
        };

        updateKeyboardState();
        viewport.addEventListener('resize', updateKeyboardState);
        window.addEventListener('orientationchange', updateKeyboardState);

        return () => {
            viewport.removeEventListener('resize', updateKeyboardState);
            window.removeEventListener('orientationchange', updateKeyboardState);
            delete document.body.dataset.keyboard;
        };
    }, []);
};
