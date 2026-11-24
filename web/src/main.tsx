import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';
import './mobile.css';
import './bandStyles.css';
import './callChrome.css';
import './callStage.css';
import App from './App';

const root = document.getElementById('root');
if (!root) throw new Error('missing #root');
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
