import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import 'katex/dist/katex.min.css';
import './styles.css';
import './mobile.css';
import App from './App';
import { consumeFamilyCodeFromUrl } from './useSession';

// Scrub ?kod= from the URL before anything else — analytics init included —
// so the family access code never reaches PostHog in $current_url.
consumeFamilyCodeFromUrl();

const root = document.getElementById('root');
if (!root) throw new Error('missing #root');
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
