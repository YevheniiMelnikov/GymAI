import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
// import './index.css'; // If we have global styles, we can import them here.
// For now, we assume existing styles are loaded via Django template or we'll migrate them later.

ReactDOM.createRoot(document.getElementById('app')!).render(
    <React.StrictMode>
        <App />
    </React.StrictMode>
);
