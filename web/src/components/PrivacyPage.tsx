import { t, type SvKey } from '../locales/sv';
import { PaperFooter, PaperMast, PaperPage } from './Paper';

const SECTIONS: Array<[SvKey, SvKey]> = [
  ['privacy.browserTitle', 'privacy.browserBody'],
  ['privacy.sendTitle', 'privacy.sendBody'],
  ['privacy.statsTitle', 'privacy.statsBody'],
];

/** Public privacy page at /integritet: a short, calm statement of how
 *  Talarum treats what is said, on the same warm paper as the start pages.
 *  Principles, not a vendor list, so it stays true as providers change.
 *  Copy lives in web/src/locales/sv.ts. */
export default function PrivacyPage({ onBack }: { onBack: () => void }) {
  const email = t('privacy.contactEmail');
  return (
    <PaperPage>
      <PaperMast
        right={
          <a
            className="tp-mast-link"
            href="/"
            onClick={(event) => {
              if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
              event.preventDefault();
              onBack();
            }}
          >
            <span aria-hidden="true">← </span>
            {t('privacy.back')}
          </a>
        }
      />
      <main className="tp-privacy tp-wrap">
        <p className="tp-kicker">{t('privacy.kicker')}</p>
        <h1 className="tp-h1 tp-privacy-title">{t('privacy.title')}</h1>
        <p className="tp-lede">{t('privacy.intro')}</p>
        <div className="tp-privacy-list">
          {SECTIONS.map(([title, body]) => (
            <section key={title}>
              <h2>{t(title)}</h2>
              <p>{t(body)}</p>
            </section>
          ))}
          <section>
            <h2>{t('privacy.contactTitle')}</h2>
            <p>
              {t('privacy.contactPrefix')} <a href={`mailto:${email}`}>{email}</a>.
            </p>
          </section>
        </div>
        <button type="button" className="tp-back" onClick={onBack}>
          <span aria-hidden="true">← </span>
          {t('privacy.backHome')}
        </button>
      </main>
      <PaperFooter privacyLink={false} />
    </PaperPage>
  );
}
