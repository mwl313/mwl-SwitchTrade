import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import Home from './app/page';
import './app/globals.css';

const root = document.getElementById('root');
if (!root) throw new Error('SwitchTrade UI root is missing');

createRoot(root).render(
  <StrictMode>
    <Home />
  </StrictMode>,
);
