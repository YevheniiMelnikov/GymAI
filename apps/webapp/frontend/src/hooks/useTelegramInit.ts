import { useEffect } from 'react';

import { tmeDisableVerticalSwipes, tmeEnterFullscreen, tmeExpand, tmeForceDarkTheme } from '../telegram';

export const useTelegramInit = (): void => {
    useEffect(() => {
        tmeForceDarkTheme();
        tmeEnterFullscreen();
        const timer = window.setTimeout(() => {
            tmeExpand();
        }, 120);

        const handleFirstInteraction = (): void => {
            tmeForceDarkTheme();
            tmeEnterFullscreen();
            tmeDisableVerticalSwipes();
        };

        document.addEventListener('click', handleFirstInteraction, { once: true, passive: true });
        document.addEventListener('touchstart', handleFirstInteraction, { once: true, passive: true });

        return () => {
            window.clearTimeout(timer);
            document.removeEventListener('click', handleFirstInteraction);
            document.removeEventListener('touchstart', handleFirstInteraction);
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
