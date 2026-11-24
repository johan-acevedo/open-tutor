import { useEffect, useRef, useState } from 'react';
import { t } from '../locales/sv';

export type StartPanel = 'about' | 'privacy' | null;

type Props = {
  /** Switch-student entry (bands 1-2) or switch-person entry (band 3). */
  switchLabel: string;
  /** Return to the nameless first-visit page. */
  onSwitch: () => void;
  /** Controlled open state (the landing top bar opens the menu from its nav). */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Controlled panel state (the landing nav and footer open these from outside). */
  panel?: StartPanel;
  onPanelChange?: (panel: StartPanel) => void;
};

/** Pre-call menu: brand-adjacent hamburger with the switch entry plus short
 *  about and privacy notes. The landing page lifts the open and panel state
 *  so its nav links and footer can open the same panels from outside. */export default function StartMenu({ switchLabel, onSwitch, open: openProp, onOpenChange, panel: panelProp, onPanelChange }: Props) {
  const [openInner, setOpenInner] = useState(false);
  const [panelInner, setPanelInner] = useState<StartPanel>(null);
  const open = openProp ?? openInner;
  const panel = panelProp ?? panelInner;
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);

  // A panel opened from outside (landing nav or footer) takes focus, so the
  // next Tab stays in the menu instead of falling back to <body>.
  useEffect(() => {
    if (open && panel) panelRef.current?.focus();
  }, [open, panel]);

  function setOpen(next: boolean) {
    if (openProp === undefined) setOpenInner(next);
    onOpenChange?.(next);
    if (panelProp === undefined) setPanelInner(null);
    onPanelChange?.(null);
  }

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
    // setOpen is stable enough: it only writes the props/state above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open ]);

  function choose(next: 'about' | 'privacy') {
    const value: StartPanel = panel === next ? null : next;
    if (panelProp === undefined) setPanelInner(value);
    onPanelChange?.(value);
  }

  return (
    <div className="ot-menu-wrap" ref={wrapRef}>
      <button
        type="button"
        className="ot-menu-btn"
        aria-label={t('topmenu.menuLabel')}
        aria-expanded={open}
        onClick={() => {
          setOpen(!open);
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
            <div className="ot-menu-about" role="dialog" aria-label={t('startmenu.about')} ref={panelRef} tabIndex={-1}>
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
            <div className="ot-menu-about" role="dialog" aria-label={t('startmenu.privacy')} ref={panelRef} tabIndex={-1}>
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
