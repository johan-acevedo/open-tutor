import { useEffect, useRef, useState } from 'react';

type Props = {
  /** "Byt elev" (bands 1–2) or "Byt person" (band 3). */
  switchLabel: string;
  /** Return to the nameless first-visit page. */
  onSwitch: () => void;
};

/** Pre-call menu: brand-adjacent hamburger with the switch entry plus short
 *  about and privacy notes. No session is running here, so there is no inbox. */
export default function StartMenu({ switchLabel, onSwitch }: Props) {
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
        aria-label="Meny"
        aria-expanded={open}
        onClick={() => {
          setOpen((value) => !value);
          setPanel(null);
        }}
      >
        <span aria-hidden="true">☰</span>
      </button>
      {open && (
        <div className="ot-menu-panel" aria-label="Meny">
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
            Om tjänsten
          </button>
          {panel === 'about' && (
            <div className="ot-menu-about" role="dialog" aria-label="Om tjänsten">
              <p>
                Open Tutor är en rösttutor som hjälper dig med läxor och skolarbete.
                Du pratar, och tutorn förklarar och visar på skärmen.
              </p>
            </div>
          )}
          <button
            type="button"
            className="ot-menu-about-row"
            aria-expanded={panel === 'privacy'}
            onClick={() => choose('privacy')}
          >
            Integritet
          </button>
          {panel === 'privacy' && (
            <div className="ot-menu-about" role="dialog" aria-label="Integritet">
              <p>
                Din profil och anteckningar sparas bara i den här webbläsaren.
                Röstsamtalet går via våra leverantörer så att tutorn kan höra dig.
                Inget konto behövs.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
