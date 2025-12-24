import { useEffect } from 'react';

import { tmeReady, tmeExpand } from '../telegram';

export const useTelegramInit = (): void => {
    useEffect(() => {
        tmeReady();
        tmeExpand();
        const timer = window.setTimeout(() => {
            tmeExpand();
        }, 120);
        return () => {
            window.clearTimeout(timer);
        };
    }, []);
};
