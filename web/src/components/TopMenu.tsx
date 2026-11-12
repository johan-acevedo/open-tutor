import { useEffect, useRef, useState } from 'react';
import type { BoardItem } from '../protocol';
import { buildScreenSection } from '../runtimeInfo';
import type { RuntimeInfo } from '../runtimeInfo';

type Props = {
  items: BoardItem[];
  dragOver: boolean;
  runtime: RuntimeInfo | null;
  onCamera: () => void;
  onFiles: () => void;
};

/** Hamburger dropdown in the topbar: live homework inbox + sessionsinfo + about note. */
export default function TopMenu({ items, dragOver, runtime, onCamera, onFiles }: Props) {
  const [open, setOpen] = useState(false);
  const [info, setInfo] = useState(false);
  const [about, setAbout] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const count = items.filter((item) => item.kind === 'homework').length;

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

  return (
    <div className="ot-menu-wrap" ref={wrapRef}>
      <button
        type="button"
        className="ot-menu-btn"
        aria-label="Meny"
        aria-expanded={open}
        onClick={() => {
          setOpen((value) => !value);
          setInfo(false);
          setAbout(false);
        }}
      >
        <span aria-hidden="true">☰</span>
      </button>
      {open && (
        <div className="ot-menu-panel" aria-label="Meny">
          <div
            className={`ot-inbox${dragOver ? ' dragover' : ''}`}
            aria-label="Inkorg för läxor"
            aria-live="polite"
          >
            <span className="ot-inbox-icon" aria-hidden="true">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3.5 13.5 12 4.5l8.5 9V20a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 20Z" />
                <path d="M9.5 20v-5h5v5" />
              </svg>
            </span>
            <span className="ot-inbox-text">
              {count === 0 ? 'Inkorg · tom' : `Inkorg · ${count} ${count === 1 ? 'uppgift' : 'uppgifter'}`}
            </span>
            <span className="ot-inbox-hint">släpp fil här</span>
          </div>
          <div className="ot-menu-actions">
            <button type="button" onClick={onCamera}>
              Fota läxan
            </button>
            <button type="button" onClick={onFiles}>
              Välj bild
            </button>
          </div>
          <button
            type="button"
            className="ot-menu-about-row"
            aria-expanded={info}
            onClick={() => setInfo((value) => !value)}
          >
            Sessionsinfo
          </button>
          {info && (
            <div className="ot-session-info" role="region" aria-label="Sessionsinfo">
              {runtime === null ? (
                <p className="ot-session-pending">Väntar på sessionsinfo från tutorn…</p>
              ) : (
                [...runtime.sections, buildScreenSection()].map((section, index) => (
                  <section key={`${section.title}-${index}`} aria-label={section.title}>
                    <h3 className="ot-session-title">{section.title}</h3>
                    <dl className="ot-session-list">
                      {section.fields.map((field, fieldIndex) => (
                        <div key={`${field.label}-${fieldIndex}`} className="ot-session-row">
                          <dt>{field.label}</dt>
                          <dd>{field.value}</dd>
                        </div>
                      ))}
                    </dl>
                  </section>
                ))
              )}
            </div>
          )}
          <button
            type="button"
            className="ot-menu-about-row"
            aria-expanded={about}
            onClick={() => setAbout((value) => !value)}
          >
            Om Open Tutor
          </button>
          {about && (
            <div className="ot-menu-about" role="dialog" aria-label="Om Open Tutor">
              <p>by Johan Acevedo</p>
              <button type="button" onClick={() => setAbout(false)}>
                Stäng
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
