import { useEffect, useState } from 'react';

export const PHONE_QUERY = '(max-width: 600px), (max-width: 950px) and (max-height: 500px) and (pointer: coarse)';

/** The phone layout has a portrait-only variant (big fox / fox strip). */
export const PORTRAIT_QUERY = '(orientation: portrait)';

export function useViewport() {
  const [mobile, setMobile] = useState(() => window.matchMedia(PHONE_QUERY).matches);
  const [portrait, setPortrait] = useState(() => window.matchMedia(PORTRAIT_QUERY).matches);
  const [keyboard, setKeyboard] = useState(false);
  useEffect(() => {
    const media = window.matchMedia(PHONE_QUERY);
    const portraitMedia = window.matchMedia(PORTRAIT_QUERY);
    const viewport = window.visualViewport;
    let baseline = window.innerHeight;
    let width = window.innerWidth;
    let raf = 0;
    const update = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const phone = media.matches;
        setMobile(phone);
        setPortrait(portraitMedia.matches);
        // Zoom is an accessibility action, not the keyboard. Leave its viewport alone.
        if (viewport && Math.abs(viewport.scale - 1) > 0.05) return;
        const el = document.activeElement;
        const typing = el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement;
        const height = viewport?.height ?? window.innerHeight;
        if (Math.abs(width - window.innerWidth) > 80) {
          width = window.innerWidth;
          baseline = window.innerHeight;
        }
        if (!typing) baseline = Math.max(height, window.innerHeight);
        const open = phone && typing && baseline - height > 120;
        setKeyboard(open);
        const root = document.documentElement;
        root.style.setProperty('--ot-view-height', `${phone ? height : window.innerHeight}px`);
        root.style.setProperty('--ot-view-top', `${phone ? (viewport?.offsetTop ?? 0) : 0}px`);
      });
    };
    const events = ['resize', 'focusin', 'focusout'] as const;
    events.forEach((event) => window.addEventListener(event, update));
    media.addEventListener('change', update);
    portraitMedia.addEventListener('change', update);
    viewport?.addEventListener('resize', update);
    viewport?.addEventListener('scroll', update);
    update();
    return () => {
      cancelAnimationFrame(raf);
      events.forEach((event) => window.removeEventListener(event, update));
      media.removeEventListener('change', update);
      portraitMedia.removeEventListener('change', update);
      viewport?.removeEventListener('resize', update);
      viewport?.removeEventListener('scroll', update);
      document.documentElement.style.removeProperty('--ot-view-height');
      document.documentElement.style.removeProperty('--ot-view-top');
    };
  }, []);
  return { mobile, portrait, keyboard };
}
