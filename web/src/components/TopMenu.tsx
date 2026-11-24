import { useEffect, useId, useRef, useState, type ReactElement } from 'react';
import type { BoardItem } from '../protocol';
import { t } from '../locales/sv';

type Props = {
  items: BoardItem[];
  dragOver: boolean;
  onCamera: () => void;
  onFiles: () => void;
  /** Leave the call and go back to the start screen (switch/add student). */
  onSwitchStudent?: () => void;
  switchLabel?: string;
};

const stroke = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
};

function Icon({ name }: { name: 'menu' | 'camera' | 'image' | 'tray' | 'switch' | 'info' | 'chevron' }) {
  const paths: Record<typeof name, ReactElement> = {
    menu: (
      <>
        <path d="M4 7h16" />
        <path d="M4 12h16" />
        <path d="M4 17h16" />
      </>
    ),
    camera: (
      <>
        <path d="M4 8.5A1.5 1.5 0 0 1 5.5 7h2.2l1.6-2.2h5.4L16.3 7h2.2A1.5 1.5 0 0 1 20 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 17.5Z" />
        <circle cx="12" cy="13" r="3.4" />
      </>
    ),
    image: (
      <>
        <rect x="4" y="4.5" width="16" height="15" rx="2" />
        <circle cx="9.2" cy="9.6" r="1.6" />
        <path d="m4.5 17 4.6-4.6 3.4 3.4 2.4-2.4 4.6 4.6" />
      </>
    ),
    tray: (
      <>
        <path d="M12 3.5v9" />
        <path d="m8.2 9 3.8 3.8L15.8 9" />
        <path d="M4 13.5h4.2l1.3 2.5h5l1.3-2.5H20v4.5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18Z" />
      </>
    ),
    switch: (
      <>
        <path d="M14 4.5h3.5A1.5 1.5 0 0 1 19 6v12a1.5 1.5 0 0 1-1.5 1.5H14" />
        <path d="M10 8.5 6.5 12l3.5 3.5" />
        <path d="M6.5 12H15" />
      </>
    ),
    info: (
      <>
        <circle cx="12" cy="12" r="8.2" />
        <path d="M12 11v5" />
        <path d="M12 7.8v.1" />
      </>
    ),
    chevron: <path d="m9 6 6 6-6 6" />,
  };
  return (
    <svg className="ot-callmenu-icon" width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" {...stroke}>
      {paths[name]}
    </svg>
  );
}

/**
 * The in-call header menu: send homework (status, camera, file), switch
 * student (which ends the call, so it sits apart and says so), and a short
 * about note. A disclosure, not an ARIA menu: plain buttons in tab order.
 */
export default function TopMenu({ items, dragOver, onCamera, onFiles, onSwitchStudent, switchLabel }: Props) {
  const [open, setOpen] = useState(false);
  const [about, setAbout] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelId = useId();
  const switchHintId = useId();
  const count = items.filter((item) => item.kind === 'homework').length;

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
        triggerRef.current?.focus();
      }
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
  }, [open]);

  // Picking an action closes the menu: the file picker / camera / start
  // screen takes over, and the menu should not still hang open behind it.
  const pick = (action: () => void) => () => {
    setOpen(false);
    action();
  };

  const status =
    count === 0
      ? t('topmenu.inboxEmpty')
      : count === 1
        ? t('topmenu.inboxOne', { count })
        : t('topmenu.inboxMany', { count });

  return (
    <div className="ot-menu-wrap ot-callmenu" ref={wrapRef}>
      <button
        ref={triggerRef}
        type="button"
        className="ot-menu-btn ot-callmenu-btn"
        aria-label={t('topmenu.menuLabel')}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => {
          setOpen((value) => !value);
          setAbout(false);
        }}
      >
        <Icon name="menu" />
        <span className="ot-callmenu-btn-label">{t('topmenu.menuLabel')}</span>
      </button>
      {open && (
        <div id={panelId} className="ot-callmenu-panel" role="group" aria-label={t('topmenu.menuLabel')}>
          <div
            className={`ot-callmenu-drop${dragOver ? ' dragover' : ''}${count > 0 ? ' has-items' : ''}`}
            aria-label={t('topmenu.inboxLabel')}
            aria-live="polite"
          >
            <Icon name="tray" />
            <span className="ot-callmenu-drop-text">
              <strong>{status}</strong>
              <span className="ot-callmenu-drop-hint">{t('topmenu.dropHint')}</span>
            </span>
          </div>
          <button type="button" className="ot-callmenu-item" onClick={pick(onCamera)}>
            <Icon name="camera" />
            <span className="ot-callmenu-label">{t('topmenu.photo')}</span>
          </button>
          <button type="button" className="ot-callmenu-item" onClick={pick(onFiles)}>
            <Icon name="image" />
            <span className="ot-callmenu-label">{t('topmenu.chooseImage')}</span>
          </button>

          <div className="ot-callmenu-sep" role="presentation" />

          {onSwitchStudent && (
            <button
              type="button"
              className="ot-callmenu-item ot-callmenu-leave"
              aria-label={switchLabel ?? t('topmenu.switchFallback')}
              aria-describedby={switchHintId}
              onClick={pick(onSwitchStudent)}
            >
              <Icon name="switch" />
              <span className="ot-callmenu-label">
                {switchLabel ?? t('topmenu.switchFallback')}
                <small id={switchHintId}>{t('topmenu.switchHint')}</small>
              </span>
            </button>
          )}
          <button
            type="button"
            className={`ot-callmenu-item ot-callmenu-about-row${about ? ' open' : ''}`}
            aria-expanded={about}
            onClick={() => setAbout((value) => !value)}
          >
            <Icon name="info" />
            <span className="ot-callmenu-label">{t('topmenu.aboutTitle')}</span>
            <Icon name="chevron" />
          </button>
          {about && (
            <div className="ot-callmenu-about">
              <p>{t('startmenu.aboutText')}</p>
              <p className="ot-callmenu-by">{t('topmenu.aboutBy')}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
