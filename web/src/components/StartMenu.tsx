import { useEffect, useRef, useState } from 'react';
import { t } from '../locales/sv';

type Props = {
  /** Switch-student entry (bands 1-2) or switch-person entry (band 3). */
  switchLabel: string;
  /** Return to the nameless first-visit page. */
  onSwitch: () => void;
};

/** Pre-call menu: brand-adjacent hamburger with the switch entry plus short
 *  about and privacy notes. No session is running here, so there is no inbox. */export default function StartMenu({ switchLabel, onSwitch }: Props) {
  const [open, setOpen] = useState(false);
  const [panel, setPanel] = useState<'about' | 'privacy' | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    const onPointer = (event: PointerEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    window.addEventListener('pointerdown', onPointer);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('pointerdown', onPointer);
    };
  }, [open ]);

  function choose(next: 'about' | 'privacy') {
    setPanel((cur) => (cur === next ? null : next));
  }

  return (
    <div className="ot-menu-wrap" ref={wrapRef}>
      <button
        type="button"
        className="ot-menu-btn"
        aria-label={t('topmenu.menuLabel')}
        aria-expanded={open}
        onClick={() => {
          setOpen((value) => !value);
          setPanel(null);
        }}
      >
        <span aria-hidden="true">☰</span>
      </button>
      {open && (
        <div className="ot-menu-panel" aria-label={t('topmenu.menuLabel')}>
          <div className="ot-menu-actions">
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                onSwitch();
              }}
            >
              {switchLabel}
            </button>
          </div>
          <button
            type="button"
            className="ot-menu-about-row"
            aria-expanded={panel === 'about'}
            onClick={() => choose('about')}
          >
            {t('startmenu.about')}
          </button>
          {panel === 'about' && (
            <div className="ot-menu-about" role="dialog" aria-label={t('startmenu.about')}>
              <p>
                {t('startmenu.aboutText')}
              </p>
            </div>
          )}
          <button
            type="button"
            className="ot-menu-about-row"
            aria-expanded={panel === 'privacy'}
            onClick={() => choose('privacy')}
          >
            {t('startmenu.privacy')}
          </button>
          {panel === 'privacy' && (
            <div className="ot-menu-about" role="dialog" aria-label={t('startmenu.privacy')}>
              <p>
                {t('startmenu.privacyText')}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
