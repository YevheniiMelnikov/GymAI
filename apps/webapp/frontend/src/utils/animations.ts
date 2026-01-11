const FAVORITE_ANIMATION_CLASS = 'is-animating';
const FAVORITE_ANIMATION_MS = 520;

export const triggerFavoriteAnimation = (element: HTMLElement | null): void => {
    if (!element) {
        return;
    }
    element.classList.remove(FAVORITE_ANIMATION_CLASS);
    void element.offsetWidth;
    element.classList.add(FAVORITE_ANIMATION_CLASS);
    window.setTimeout(() => {
        element.classList.remove(FAVORITE_ANIMATION_CLASS);
    }, FAVORITE_ANIMATION_MS);
};
