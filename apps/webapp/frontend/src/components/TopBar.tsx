import React, { useEffect, useRef } from 'react';

type TopBarProps = {
    title: string;
    onBack?: () => void;
};

const TopBar: React.FC<React.PropsWithChildren<TopBarProps>> = ({ title, onBack, children }) => {
    const swipeRef = useRef({
        startX: 0,
        startY: 0,
        lastX: 0,
        lastTime: 0,
        dragging: false,
    });

    useEffect(() => {
        if (!onBack) {
            return;
        }
        const getMain = () => document.querySelector('main#app') as HTMLElement | null;
        const handleTouchStart = (event: TouchEvent) => {
            const touch = event.touches[0];
            if (!touch) {
                return;
            }
            if (touch.clientX > 24) {
                return;
            }
            swipeRef.current = {
                startX: touch.clientX,
                startY: touch.clientY,
                lastX: touch.clientX,
                lastTime: Date.now(),
                dragging: true,
            };
        };
        const handleTouchMove = (event: TouchEvent) => {
            const touch = event.touches[0];
            if (!touch) {
                return;
            }
            const state = swipeRef.current;
            if (!state.dragging) {
                return;
            }
            const deltaX = touch.clientX - state.startX;
            const deltaY = Math.abs(touch.clientY - state.startY);
            if (deltaX < 0 || deltaY > 50) {
                return;
            }
            event.preventDefault();
            const main = getMain();
            if (!main) {
                return;
            }
            main.style.transition = 'none';
            const clampedX = Math.min(deltaX, window.innerWidth);
            main.style.transform = `translateX(${clampedX}px)`;
            const now = Date.now();
            if (now > state.lastTime) {
                state.lastTime = now;
                state.lastX = touch.clientX;
            }
        };
        const handleTouchEnd = (event: TouchEvent) => {
            const state = swipeRef.current;
            if (!state.dragging) {
                return;
            }
            state.dragging = false;
            const touch = event.changedTouches[0];
            if (!touch) {
                return;
            }
            const deltaX = touch.clientX - state.startX;
            const deltaY = Math.abs(touch.clientY - state.startY);
            const main = getMain();
            if (!main) {
                return;
            }
            if (deltaX <= 0 || deltaY > 60) {
                main.style.transition = 'transform 180ms ease';
                main.style.transform = 'translateX(0)';
                return;
            }
            const elapsed = Math.max(Date.now() - state.lastTime, 1);
            const velocity = (touch.clientX - state.lastX) / elapsed;
            const shouldComplete = deltaX > window.innerWidth * 0.25 || velocity > 0.6;
            if (shouldComplete) {
                main.style.transition = 'transform 200ms ease';
                main.style.transform = 'translateX(100%)';
                window.setTimeout(() => {
                    onBack();
                }, 210);
            } else {
                main.style.transition = 'transform 180ms ease';
                main.style.transform = 'translateX(0)';
            }
        };
        window.addEventListener('touchstart', handleTouchStart, { passive: true });
        window.addEventListener('touchmove', handleTouchMove, { passive: false });
        window.addEventListener('touchend', handleTouchEnd, { passive: true });
        window.addEventListener('touchcancel', handleTouchEnd, { passive: true });
        return () => {
            window.removeEventListener('touchstart', handleTouchStart);
            window.removeEventListener('touchmove', handleTouchMove);
            window.removeEventListener('touchend', handleTouchEnd);
            window.removeEventListener('touchcancel', handleTouchEnd);
            const main = getMain();
            if (main) {
                main.style.transition = '';
                main.style.transform = '';
            }
        };
    }, [onBack]);

    return (
        <header className="topbar" role="banner">
            <div className="topbar__leading">
                <span aria-hidden="true" className="topbar__spacer" />
            </div>

            <h1 id="page-title" className="topbar__title">
                {title}
            </h1>

            <div className="topbar__actions" aria-hidden={!children}>
                {children ?? <span aria-hidden="true" className="topbar__spacer" />}
            </div>
        </header>
    );
};

export default TopBar;
