import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import { App } from '@app/App';
import { registerServiceWorker } from '@shared/pwa/register';
import '@shared/styles/global.css';
import '@fontsource-variable/outfit';
import '@fontsource/reenie-beanie/latin.css';

const container = document.getElementById('root');

if (!container) {
  throw new Error('Root container is missing.');
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

registerServiceWorker();
