import React from 'react';

interface LoadingSpinnerProps {
    className?: string;
}

const LoadingSpinner: React.FC<LoadingSpinnerProps> = ({ className }) => (
    <div className={`page-loading${className ? ` ${className}` : ''}`} aria-live="polite" aria-busy="true">
        <span className="button-spinner page-loading__spinner" aria-hidden="true" />
    </div>
);

export default LoadingSpinner;
