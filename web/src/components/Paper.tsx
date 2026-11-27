import type { MouseEvent, ReactNode } from 'react';
import '@fontsource-variable/fraunces/opsz.css';
import '@fontsource-variable/fraunces/opsz-italic.css';
import '@fontsource/plus-jakarta-sans/400.css';
import '@fontsource/plus-jakarta-sans/500.css';
import '@fontsource/plus-jakarta-sans/600.css';
import '@fontsource/plus-jakarta-sans/700.css';
import '@fontsource/caveat/600.css';
import '@fontsource/caveat/700.css';
import { explicitHostBand, type BandConfig, type BandId } from '../bands';
import { bandUrl } from '../bandLinks';
import { t, type SvKey } from '../locales/sv';
import { usePlayingGreetingBand, preloadGreeting, toggleGreeting } from './greetingAudio';

// Warm paper editorial pages, v4 (2026-11-27): the start pages (/, the band
// pages), the household picker and /integritet share one light paper look.
// Fixed band nav in the masthead (no switch inside the hero), one audience
// voice per page, a squared exercise book beside a dark companion call
// window, illustrated steps, then the planned price and a closing call to
// action. The call view, the end card and the Smart Screen keep their dark
// themes. Fonts are self-hosted (fontsource), never a font CDN. Styles:
// paper.css. Copy: locales/sv.ts.

/** Who a page speaks to: / and /ak1-6 speak to parents about their child;
 *  /hogstadiet and /gymnasiet speak to the learner directly. */
export type Voice = 'parent' | 'you';

export function voiceOf(band: BandId): Voice {
  return band === 'primary' ? 'parent' : 'you';
}

/** Page frame. The document itself scrolls (iOS URL-bar collapse, tap the
 *  status bar to scroll to the top); only the call view is a fixed
 *  viewport. */
export function PaperPage({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <div className="tp" aria-label={label}>
      {children}
    </div>
  );
}

const NAV: Array<[BandId, SvKey]> = [
  ['primary', 'landing.navPrimary'],
  ['middle', 'landing.navMiddle'],
  ['upper', 'landing.navUpper'],
];

/** Where a band link points. On a tutor.* host the prefix is swapped (full
 *  load); on any other host Åk 1–6 is the front door (/) and the other bands
 *  their own paths. */
export function bandHref(target: BandId): string {
  try {
    const href = window.location.href;
    if (explicitHostBand(window.location.hostname) !== null) return bandUrl(target, href);
    if (target === 'primary') {
      const url = new URL(href);
      url.pathname = '/';
      url.searchParams.delete('band');
      url.hash = '';
      return url.pathname + url.search;
    }
    const url = new URL(bandUrl(target, href));
    url.hash = '';
    return url.pathname + url.search;
  } catch {
    return target === 'primary' ? '/' : `/${target === 'middle' ? 'hogstadiet' : 'gymnasiet'}`;
  }
}

/** Masthead: logo left, the three band links in the middle (a slim strip
 *  under the top bar on phones), Integritet far right, then an optional slot
 *  (the returning visitor's menu). The current band is marked, and the links
 *  never move between pages. */
export function PaperMast({ active, onNavigate, right }: {
  /** The band page being shown, 'privacy' on /integritet, null elsewhere. */
  active?: BandId | 'privacy' | null;
  /** In-app navigation (talarum-style hosts); tutor.* hosts do a full load. */
  onNavigate?: (target: BandId) => void;
  right?: ReactNode;
}) {
  function onClick(event: MouseEvent<HTMLAnchorElement>, target: BandId) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (target === active) {
      // Already here: stay put instead of reloading the same page.
      event.preventDefault();
      return;
    }
    if (!onNavigate) return;
    try {
      if (explicitHostBand(window.location.hostname) !== null) return;
    } catch {
      return;
    }
    event.preventDefault();
    onNavigate(target);
  }
  return (
    <header className="tp-mast">
      <div className="tp-wrap tp-mast-in">
        <a className="tp-logo" href="/">
          <img src="/talarum-logo.svg" alt={t('brand.name')} width={128} height={30} />
        </a>
        <nav className="tp-nav" aria-label={t('landing.navLabel')}>
          {NAV.map(([id, label]) => (
            <a
              key={id}
              href={bandHref(id)}
              aria-current={active === id ? 'page' : undefined}
              onClick={(e) => onClick(e, id)}
            >
              {t(label)}
            </a>
          ))}
        </nav>
        <div className="tp-mast-right">
          <a className="tp-mast-link" href="/integritet" aria-current={active === 'privacy' ? 'page' : undefined}>
            {t('landing.headerPrivacy')}
          </a>
          {right}
        </div>
      </div>
    </header>
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

const TITLE: Record<BandId, [SvKey, SvKey, SvKey]> = {
  primary: ['landing.titlePrefixPrimary', 'landing.titleAccentPrimary', 'landing.titleSuffixPrimary'],
  middle: ['landing.titlePrefixMiddle', 'landing.titleAccentMiddle', 'landing.titleSuffixMiddle'],
  upper: ['landing.titlePrefixUpper', 'landing.titleAccentUpper', 'landing.titleSuffixUpper'],
};

const INTRO: Record<BandId, SvKey> = {
  primary: 'landing.introPrimary',
  middle: 'landing.introMiddle',
  upper: 'landing.introUpper',
};

/** Headline with an italic accent word. The accent and the rest of its line
 *  stay together, so the accent never strands at a line end. */
export function PaperTitle({ band }: { band: BandId }) {
  const [prefix, accent, suffix] = TITLE[band];
  return (
    <h1 className="tp-h1">
      {t(prefix)}
      <i>{t(accent)}</i>
      {t(suffix)}
    </h1>
  );
}

type Book = {
  subject: SvKey;
  task: SvKey;
  question: SvKey;
  row1: SvKey;
  note1: SvKey;
  row2: SvKey;
  learnerSaid: SvKey;
  companionSaid: SvKey;
  problem: SvKey;
  done: SvKey;
};

const BOOK: Record<BandId, Book> = {
  primary: {
    subject: 'landing.bookSubjectPrimary',
    task: 'landing.bookTaskPrimary',
    question: 'landing.bookQuestionPrimary',
    row1: 'landing.row1Primary',
    note1: 'landing.note1Primary',
    row2: 'landing.row2Primary',
    learnerSaid: 'landing.learnerSaidPrimary',
    companionSaid: 'landing.companionSaidPrimary',
    problem: 'landing.stepProblemPrimary',
    done: 'landing.stepDonePrimary',
  },
  middle: {
    subject: 'landing.bookSubjectMiddle',
    task: 'landing.bookTaskMiddle',
    question: 'landing.bookQuestionMiddle',
    row1: 'landing.row1Middle',
    note1: 'landing.note1Middle',
    row2: 'landing.row2Middle',
    learnerSaid: 'landing.learnerSaidMiddle',
    companionSaid: 'landing.companionSaidMiddle',
    problem: 'landing.stepProblemMiddle',
    done: 'landing.stepDoneMiddle',
  },
  upper: {
    subject: 'landing.bookSubjectUpper',
    task: 'landing.bookTaskUpper',
    question: 'landing.bookQuestionUpper',
    row1: 'landing.row1Upper',
    note1: 'landing.note1Upper',
    row2: 'landing.row2Upper',
    learnerSaid: 'landing.learnerSaidUpper',
    companionSaid: 'landing.companionSaidUpper',
    problem: 'landing.stepProblemUpper',
    done: 'landing.stepDoneUpper',
  },
};

/** Quiet voice waveform (CSS bars). Moves only while the greeting plays. */
function Wave({ bars = 23, live = false, className = '' }: { bars?: number; live?: boolean; className?: string }) {
  return (
    <span className={`tp-wave${live ? ' is-live' : ''}${className ? ` ${className}` : ''}`} aria-hidden="true">
      {Array.from({ length: bars }, (_, i) => (
        <i key={i} />
      ))}
    </span>
  );
}

/** The hero showcase: a squared exercise book with work in progress (never
 *  the finished answer) and a two-way exchange, beside a dark call window
 *  with the companion pointing at the book. */
export function Showcase({ band }: { band: BandConfig }) {
  const book = BOOK[band.id];
  const live = usePlayingGreetingBand() === band.id;
  const learner = t(voiceOf(band.id) === 'parent' ? 'landing.learnerPrimary' : 'landing.learnerYou');
  return (
    <figure className="tp-show" data-companion={band.id} key={band.id} aria-label={t('landing.showcaseLabel', { companion: band.companion.name })}>
      <div className="tp-book">
        <p className="tp-book-head">{t(book.subject)}</p>
        <p className="tp-book-q">
          <small>{t(book.task)}</small> {t(book.question)}
        </p>
        <div className="tp-hand">
          <p>
            <span>{t(book.row1)}</span> <em>{t(book.note1)}</em>
          </p>
          <p className="tp-hand-next">
            <span>{t(book.row2)}</span>
          </p>
        </div>
        <div className="tp-said">
          <p>
            <b>{learner}:</b> {t(book.learnerSaid)}
          </p>
          <p>
            <b>{band.companion.name}:</b> {t(book.companionSaid)}
          </p>
        </div>
      </div>
      <div className="tp-call" role="img" aria-label={t('landing.callLabel', { companion: band.companion.name })}>
        <img
          src={band.companion.poses.pointing}
          alt=""
          width={784}
          height={800}
          onError={(e) => ((e.target as HTMLImageElement).style.visibility = 'hidden')}
        />
        <Wave live={live} />
      </div>
    </figure>
  );
}

/** The 1-tap start: dark charcoal pill with the companion's face. */
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

/** Labelled listen control: plays the companion's spoken hello, and reads
 *  "Spelar…" with a stop mark while it plays. */
export function ListenButton({ band }: { band: BandConfig }) {
  const playing = usePlayingGreetingBand() === band.id;
  const companion = band.companion.name;
  return (
    <button
      type="button"
      className={`tp-listen${playing ? ' is-playing' : ''}`}
      onPointerEnter={() => preloadGreeting(band.id)}
      onPointerDown={() => preloadGreeting(band.id)}
      onFocus={() => preloadGreeting(band.id)}
      onClick={() => toggleGreeting(band.id)}
      aria-pressed={playing}
      title={t('landing.listenTitle', { companion })}
    >
      {playing ? (
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <rect x="5" y="5" width="10" height="10" rx="2" fill="currentColor" />
        </svg>
      ) : (
        <svg viewBox="0 0 52 48" aria-hidden="true">
          <path d="M6 18 H14 L25 9 V39 L14 30 H6 Z" fill="currentColor" stroke="currentColor" strokeWidth="3" strokeLinejoin="round" />
          <path d="M31 17 a10 10 0 0 1 0 14" fill="none" stroke="currentColor" strokeWidth="4.5" strokeLinecap="round" />
          <path d="M37 11 a18 18 0 0 1 0 26" fill="none" stroke="currentColor" strokeWidth="4.5" strokeLinecap="round" />
        </svg>
      )}
      <span className="tp-listen-label">
        <span>{t(playing ? 'landing.listenPlaying' : 'landing.listen')}</span>
        <span className="tp-sr">{t('landing.listenSuffix', { companion })}</span>
      </span>
    </button>
  );
}

/** The quiet line under the start row: free while we test, no account. */
export function QuietPrice() {
  return (
    <p className="tp-quietline">
      <b>{t('landing.quietFree')}</b>
      <span aria-hidden="true"> · </span>
      <span className="tp-sr">, </span>
      {t('landing.quietAccount')}
    </p>
  );
}

export type StartProps = {
  label: string;
  disabled?: boolean;
  onStart: () => void;
};

/** Band page hero: headline, one-voice intro, an optional returning-visitor
 *  line, the start row (start + Hör rösten), the quiet price line, and the
 *  showcase. */
export function Hero({ band, hello, start }: { band: BandConfig; hello?: ReactNode; start: StartProps }) {
  return (
    <header className="tp-hero tp-wrap">
      <div className="tp-hero-copy">
        <PaperTitle band={band.id} />
        <p className="tp-lede">{t(INTRO[band.id])}</p>
        {hello}
        <div className="tp-cta-row">
          <StartButton band={band} label={start.label} disabled={start.disabled} onClick={start.onStart} />
          <ListenButton band={band} />
        </div>
        <QuietPrice />
      </div>
      <Showcase band={band} />
    </header>
  );
}

const TALK_ART: Record<BandId, string> = {
  primary: '/illustrations/step-talk-primary.webp',
  middle: '/illustrations/step-talk-middle.webp',
  upper: '/illustrations/step-talk-upper.webp',
};

/** "Så går det till": three illustrated steps. The illustrations carry no
 *  text; the band's maths is written over them in HTML (Caveat), placed by
 *  percentages so it stays inside the phone screen, the board and the page
 *  at every width. */
export function StepsSection({ band }: { band: BandConfig }) {
  const book = BOOK[band.id];
  const parent = voiceOf(band.id) === 'parent';
  const companion = band.companion.name;
  return (
    <section className="tp-sec tp-how" id="sa-gar-det-till" aria-labelledby="tp-how-title">
      <div className="tp-wrap">
        <p className="tp-kicker">{t('landing.howKicker')}</p>
        <h2 className="tp-h2" id="tp-how-title">{t(parent ? 'landing.howHeadPrimary' : 'landing.howHeadYou')}</h2>
        <ol className="tp-steps" data-companion={band.id}>
          <li>
            <div className="tp-art tp-art-capture" aria-hidden="true">
              <img src="/illustrations/step-capture.webp" alt="" width={960} height={536} loading="lazy" decoding="async" />
              <span className="tp-ink tp-ink-page">{t(book.problem)}</span>
              <span className="tp-ink tp-ink-screen">{t(book.problem)}</span>
            </div>
            <h3>
              <span className="tp-step-n">{t('landing.stepN', { n: 1 })}</span> {t('landing.step1Title')}
            </h3>
            <p>{t(parent ? 'landing.step1TextPrimary' : 'landing.step1TextYou')}</p>
          </li>
          <li>
            <div className="tp-art tp-art-talk" aria-hidden="true">
              <img src={TALK_ART[band.id]} alt="" width={960} height={536} loading="lazy" decoding="async" />
              <span className="tp-ink tp-ink-board">{t(book.row1)}</span>
              <Wave bars={19} className="tp-wave-board" />
            </div>
            <h3>
              <span className="tp-step-n">{t('landing.stepN', { n: 2 })}</span> {t('landing.step2Title')}
            </h3>
            <p>{t(parent ? 'landing.step2TextPrimary' : 'landing.step2TextYou', { companion })}</p>
          </li>
          <li>
            <div className="tp-art tp-art-solve" aria-hidden="true">
              <img src="/illustrations/step-solve.webp" alt="" width={960} height={536} loading="lazy" decoding="async" />
              <span className="tp-ink tp-ink-done">
                {t(book.done)} <b>✓</b>
              </span>
            </div>
            <h3>
              <span className="tp-step-n">{t('landing.stepN', { n: 3 })}</span>{' '}
              {t(parent ? 'landing.step3TitlePrimary' : 'landing.step3TitleYou')}
            </h3>
            <p>{t(parent ? 'landing.step3TextPrimary' : 'landing.step3TextYou')}</p>
          </li>
        </ol>
      </div>
    </section>
  );
}

const VERSUS_NOTE: Record<BandId, SvKey> = {
  primary: 'landing.versusNotePrimary',
  middle: 'landing.versusNoteMiddle',
  upper: 'landing.versusNoteUpper',
};

/** Planned price on a warm sand band: a compact ruled card beside an
 *  understated comparison with private tutoring. Billing is not live: the
 *  heading says so plainly. */
export function PriceSection({ band }: { band: BandId }) {
  return (
    <section className="tp-sec tp-price" id="pris" aria-labelledby="tp-price-title">
      <div className="tp-wrap">
        <p className="tp-kicker">{t('landing.priceKicker')}</p>
        <h2 className="tp-h2" id="tp-price-title">{t('landing.priceTitle')}</h2>
        <div className="tp-pricing">
          <dl className="tp-list">
            <div className="tp-li">
              <dt>{t('landing.priceNowLabel')}</dt>
              <dd className="tp-free">{t('landing.priceNowValue')}</dd>
            </div>
            <div className="tp-li">
              <dt>{t('landing.priceLaterLabel')}</dt>
              <dd>{t('landing.priceLaterValue')}</dd>
            </div>
            <div className="tp-li">
              <dt>{t('landing.priceTermLabel')}</dt>
              <dd>{t('landing.priceTermValue')}</dd>
            </div>
          </dl>
          <div className="tp-versus" role="group" aria-label={t('landing.versusLabel')}>
            <div className="tp-bar is-us">
              <div className="tp-bar-lab"><b>{t('landing.versusUs')}</b><span>{t('landing.versusUsValue')}</span></div>
              <div className="tp-track"><div className="tp-fill" style={{ width: '5%' }} /></div>
            </div>
            <div className="tp-bar">
              <div className="tp-bar-lab"><b>{t(band === 'upper' ? 'landing.versusHumanUpper' : 'landing.versusHuman')}</b><span>{t('landing.versusHumanValue')}</span></div>
              <div className="tp-track">
                <div className="tp-fill" style={{ width: '60%' }} />
                <div className="tp-fill tp-fill-range" style={{ width: '40%' }} />
              </div>
            </div>
            <p>{t(VERSUS_NOTE[band])}</p>
          </div>
        </div>
      </div>
    </section>
  );
}

/** Closing strip: one question in the page's voice and the same two
 *  controls as the hero. */
export function ClosingCta({ band, start }: { band: BandConfig; start: StartProps }) {
  const parent = voiceOf(band.id) === 'parent';
  return (
    <section className="tp-close" aria-labelledby="tp-close-title">
      <div className="tp-wrap">
        <h2 className="tp-h2" id="tp-close-title">{t(parent ? 'landing.closingPrimary' : 'landing.closingYou')}</h2>
        <div className="tp-cta-row">
          <StartButton band={band} label={start.label} disabled={start.disabled} onClick={start.onStart} />
          <ListenButton band={band} />
        </div>
      </div>
    </section>
  );
}

/** Everything under a band page's hero: steps, price, closing. */
export function BandSections({ band, start }: { band: BandConfig; start: StartProps }) {
  return (
    <>
      <StepsSection band={band} />
      <PriceSection band={band.id} />
      <ClosingCta band={band} start={start} />
    </>
  );
}

