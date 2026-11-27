import type { MouseEvent, ReactNode } from 'react';
import '@fontsource-variable/fraunces/opsz.css';
import '@fontsource-variable/fraunces/opsz-italic.css';
import '@fontsource/plus-jakarta-sans/400.css';
import '@fontsource/plus-jakarta-sans/500.css';
import '@fontsource/plus-jakarta-sans/600.css';
import '@fontsource/plus-jakarta-sans/700.css';
import '@fontsource/caveat/600.css';
import '@fontsource/caveat/700.css';
import { BANDS, explicitHostBand, type BandConfig, type BandId } from '../bands';
import { t, type SvKey } from '../locales/sv';
import { usePlayingGreetingBand, toggleGreeting } from './greetingAudio';

// Warm paper editorial pages (2026-11-27): the start pages (/, the band
// pages), the household picker and /integritet share one light paper look.
// The call view, the end card and the Smart Screen keep their dark themes.
// Fonts are self-hosted (fontsource), never a font CDN. Styles: paper.css.

/** Who a page speaks to: grundskola families (/, /ak1-6, /hogstadiet) or
 *  upper-secondary students and adults (/gymnasiet). */
export type Audience = 'family' | 'adult';

export function audienceOf(band: BandId): Audience {
  return band === 'upper' ? 'adult' : 'family';
}

/** Page frame: the paper canvas is the scroll container. */
export function PaperPage({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <div className="tp" aria-label={label}>
      {children}
    </div>
  );
}

/** Masthead: logo left, optional centred nav, right-hand slot. */
export function PaperMast({ nav, right }: { nav?: ReactNode; right?: ReactNode }) {
  return (
    <header className="tp-mast">
      <div className="tp-wrap tp-mast-in">
        <a className="tp-logo" href="/">
          <img src="/talarum-logo.svg" alt={t('brand.name')} width={128} height={30} />
        </a>
        {nav && (
          <nav className="tp-nav" aria-label={t('landing.navLabel')}>
            {nav}
          </nav>
        )}
        {right && <div className="tp-mast-right">{right}</div>}
      </div>
    </header>
  );
}

/** In-page link to a section: scrolls the paper canvas without touching the
 *  URL (a hash change would fire popstate and reset the start view). */
export function SectionLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <a
      href={`#${to}`}
      onClick={(event) => {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        const target = document.getElementById(to);
        if (!target) return;
        event.preventDefault();
        const reduce = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        target.scrollIntoView?.({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
      }}
    >
      {children}
    </a>
  );
}

/** One calm footer line plus the /integritet link. */
export function PaperFooter({ privacyLink = true }: { privacyLink?: boolean }) {
  return (
    <footer className="tp-foot">
      <div className="tp-wrap tp-foot-in">
        <img src="/talarum-logo.svg" alt={t('brand.name')} width={86} height={20} />
        <p>{t('landing.footerText')}</p>
        {privacyLink && (
          <a href="/integritet">
            {t('landing.footerPrivacy')} <span aria-hidden="true">→</span>
          </a>
        )}
      </div>
    </footer>
  );
}

/** Headline with an italic accent word. The accent and the rest of its line
 *  stay together, so the accent never strands at a line end. */
export function PaperTitle({ prefix, accent, suffix }: { prefix: SvKey; accent: SvKey; suffix: SvKey }) {
  return (
    <h1 className="tp-h1">
      {t(prefix)}
      <i>{t(accent)}</i>
      {t(suffix)}
    </h1>
  );
}

const BOOK: Record<BandId, {
  subject: SvKey;
  task: SvKey;
  question: SvKey;
  rows: [SvKey, SvKey, SvKey];
  notes: [SvKey, SvKey];
  said: SvKey;
}> = {
  primary: {
    subject: 'landing.bookSubjectPrimary',
    task: 'landing.bookTaskPrimary',
    question: 'landing.bookQuestionPrimary',
    rows: ['landing.row1Primary', 'landing.row2Primary', 'landing.row3Primary'],
    notes: ['landing.note1Primary', 'landing.note2Primary'],
    said: 'landing.bookSaidPrimary',
  },
  middle: {
    subject: 'landing.bookSubjectMiddle',
    task: 'landing.bookTaskMiddle',
    question: 'landing.bookQuestionMiddle',
    rows: ['landing.row1Middle', 'landing.row2Middle', 'landing.row3Middle'],
    notes: ['landing.note1Middle', 'landing.note2Middle'],
    said: 'landing.bookSaidMiddle',
  },
  upper: {
    subject: 'landing.bookSubjectUpper',
    task: 'landing.bookTaskUpper',
    question: 'landing.bookQuestionUpper',
    rows: ['landing.row1Upper', 'landing.row2Upper', 'landing.row3Upper'],
    notes: ['landing.note1Upper', 'landing.note2Upper'],
    said: 'landing.bookSaidUpper',
  },
};

/** The squared exercise book: a worked example in the band's subject, the
 *  companion's spoken question, and the companion beside the page. Purely
 *  illustrative, so the whole book is one labelled figure. */
export function Notebook({ band }: { band: BandConfig }) {
  const book = BOOK[band.id];
  return (
    <figure className="tp-book" data-companion={band.id} key={band.id}>
      <div className="tp-book-head">
        <span>{t(book.subject)}</span>
        <span className="tp-book-live">{t('landing.bookLive')}</span>
      </div>
      <p className="tp-book-q">
        <small>{t(book.task)}</small>
        {t(book.question)}
      </p>
      <div className="tp-hand">
        <div>
          <span>{t(book.rows[0])}</span>
          {t(book.notes[0]) && <em>{t(book.notes[0])}</em>}
        </div>
        <div>
          <span>{t(book.rows[1])}</span>
          {t(book.notes[1]) && <em>{t(book.notes[1])}</em>}
        </div>
        <div className="tp-hand-res">
          <span>{t(book.rows[2])}</span>
        </div>
      </div>
      <figcaption className="tp-said">
        <b>{t('landing.saidBy', { companion: band.companion.name })}</b> {t(book.said)}
      </figcaption>
      <img
        className="tp-book-fig"
        src={band.companion.hero}
        alt=""
        aria-hidden="true"
        onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
      />
    </figure>
  );
}

/** The single 1-tap start: dark espresso button with the companion's face. */
export function StartButton({ band, label, disabled, onClick }: {
  band: BandConfig;
  label: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button type="button" className="tp-cta" disabled={disabled} onClick={onClick}>
      <img src={band.companion.face} alt="" aria-hidden="true" width={40} height={40} />
      <span>{label}</span>
      <span className="tp-cta-arrow" aria-hidden="true">→</span>
    </button>
  );
}

/** Quiet round listen control: plays the companion's spoken hello. */
export function ListenButton({ band, greeting }: { band: BandConfig; greeting: string }) {
  const playing = usePlayingGreetingBand() === band.id;
  return (
    <button
      type="button"
      className={`tp-listen${playing ? ' is-playing' : ''}`}
      onClick={() => toggleGreeting(band.id)}
      aria-pressed={playing}
      aria-label={t('landing.listenAria', { greeting, companion: band.companion.name })}
      title={t('landing.listenTitle', { companion: band.companion.name })}
    >
      <svg viewBox="0 0 52 48" aria-hidden="true">
        <path d="M6 18 H14 L25 9 V39 L14 30 H6 Z" fill="currentColor" stroke="currentColor" strokeWidth="3" strokeLinejoin="round" />
        <path d="M31 17 a10 10 0 0 1 0 14" fill="none" stroke="currentColor" strokeWidth="4.5" strokeLinecap="round" />
        <path d="M36 11 a18 18 0 0 1 0 26" fill="none" stroke="currentColor" strokeWidth="4.5" strokeLinecap="round" />
        <path d="M41 6 a26 26 0 0 1 0 36" fill="none" stroke="currentColor" strokeWidth="4.5" strokeLinecap="round" opacity=".55" />
      </svg>
    </button>
  );
}

/** Honest price anchor beside the start button: free while we test, the
 *  planned price in one plain line. */
export function PriceAnchor() {
  return (
    <p className="tp-anchor">
      <b>{t('landing.freeNow')}</b>
      <span>{t('landing.plannedPrice')}</span>
    </p>
  );
}

/** The ruled price list beside a bar comparison with human tutoring. Billing
 *  is not live: the section says so plainly. */
export function PriceSection({ audience }: { audience: Audience }) {
  const adult = audience === 'adult';
  return (
    <section className="tp-sec" id="pris" aria-labelledby="tp-price-title">
      <div className="tp-wrap">
        <p className="tp-kicker">{t('landing.priceKicker')}</p>
        <h2 className="tp-h2" id="tp-price-title">{t(adult ? 'landing.priceTitleAdult' : 'landing.priceTitleFamily')}</h2>
        <p className="tp-sub">{t('landing.priceSub')}</p>
        <div className="tp-pricing">
          <div className="tp-list">
            <dl>
              <div className="tp-li">
                <dt>{t('landing.priceFreeLabel')}<small>{t('landing.priceFreeNote')}</small></dt>
                <dd className="tp-free">{t('landing.priceFreeValue')}</dd>
              </div>
              <div className="tp-li">
                <dt>{t('landing.priceAfterLabel')}<small>{t('landing.priceAfterNote')}</small></dt>
                <dd>{t('landing.priceAfterValue')}</dd>
              </div>
              <div className="tp-li">
                <dt>{t('landing.priceSubscriptionLabel')}</dt>
                <dd className="tp-word">{t('landing.priceSubscriptionValue')}</dd>
              </div>
            </dl>
            <p className="tp-now">{t('landing.priceNow')}</p>
          </div>
          <div className="tp-versus">
            <h3>{t(adult ? 'landing.versusTitleAdult' : 'landing.versusTitleFamily')}</h3>
            <div className="tp-bars">
              <div className="tp-bar is-us">
                <div className="tp-bar-lab"><b>{t('landing.versusUs')}</b><span>{t('landing.versusUsValue')}</span></div>
                <div className="tp-track"><div className="tp-fill" style={{ width: '5%' }} /></div>
              </div>
              <div className="tp-bar">
                <div className="tp-bar-lab"><b>{t(adult ? 'landing.versusHumanAdult' : 'landing.versusHuman')}</b><span>{t('landing.versusHumanValue')}</span></div>
                <div className="tp-track">
                  <div className="tp-fill" style={{ width: '60%' }} />
                  <div className="tp-fill tp-fill-range" style={{ width: '40%' }} />
                </div>
              </div>
            </div>
            <p>{t(adult ? 'landing.versusNoteAdult' : 'landing.versusNoteFamily')}</p>
          </div>
        </div>
      </div>
    </section>
  );
}

/** "Så går det till": three steps, each with a small squared board that
 *  shows the band's example moving forward. */
export function StepsSection({ band }: { band: BandConfig }) {
  const book = BOOK[band.id];
  const adult = audienceOf(band.id) === 'adult';
  return (
    <section className="tp-sec" id="sa-gar-det-till" aria-labelledby="tp-how-title">
      <div className="tp-wrap">
        <p className="tp-kicker">{t('landing.howTitle')}</p>
        <h2 className="tp-h2" id="tp-how-title">{t(adult ? 'landing.howHeadAdult' : 'landing.howHeadFamily')}</h2>
        <ol className="tp-steps">
          <li>
            <p className="tp-step-n">{t('landing.stepN', { n: 1 })}</p>
            <h3>{t(adult ? 'landing.step1TitleAdult' : 'landing.step1Title')}</h3>
            <p>{t('landing.step1Text')}</p>
            <div className="tp-mini" aria-hidden="true">{t(book.rows[0])}</div>
          </li>
          <li>
            <p className="tp-step-n">{t('landing.stepN', { n: 2 })}</p>
            <h3>{t('landing.step2Title')}</h3>
            <p>{t('landing.step2Text', { companion: band.companion.name })}</p>
            <div className="tp-mini" aria-hidden="true">
              {t(book.rows[0])}
              <br />
              <em>{t(book.rows[1])}</em>
            </div>
          </li>
          <li>
            <p className="tp-step-n">{t('landing.stepN', { n: 3 })}</p>
            <h3>{t('landing.step3Title')}</h3>
            <p>{t('landing.step3Text')}</p>
            <div className="tp-mini" aria-hidden="true">
              {t(book.rows[1])}
              <br />
              <em>{t(book.rows[2])} ✓</em>
            </div>
          </li>
        </ol>
      </div>
    </section>
  );
}

export type QuietLink = {
  lead: SvKey;
  label: SvKey;
  href: string;
  /** Companion face shown beside the link. */
  face: BandId;
  /** In-app target: a band or the front door. */
  target: BandId | '/';
};

/** Quiet cross-links to the other audiences, just above the footer. A plain
 *  left click navigates in place on talarum-style hosts; the href stays a
 *  real link (new tab, copy, no-JS). */
export function QuietLinks({ links, onNavigate }: { links: QuietLink[]; onNavigate?: (target: BandId | '/') => void }) {
  function onClick(event: MouseEvent<HTMLAnchorElement>, target: BandId | '/') {
    if (!onNavigate) return;
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    // A tutor.* host swap still needs a full load.
    try {
      if (explicitHostBand(window.location.hostname) !== null) return;
    } catch {
      return;
    }
    event.preventDefault();
    onNavigate(target);
  }
  return (
    <section className="tp-quiet" aria-label={t('landing.crossLabel')}>
      <div className="tp-wrap">
        {links.map((link) => (
          <a key={link.href} className="tp-quiet-row" href={link.href} onClick={(e) => onClick(e, link.target)}>
            <img src={BANDS[link.face].companion.face} alt="" aria-hidden="true" width={44} height={44} />
            <span className="tp-quiet-lead">{t(link.lead)}</span>
            <span className="tp-quiet-label">
              {t(link.label)} <span aria-hidden="true">→</span>
            </span>
          </a>
        ))}
      </div>
    </section>
  );
}
