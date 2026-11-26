import { t } from '../locales/sv';
import Brand from './Brand';

/** Public privacy page at /integritet: what the browser remembers, what is
 *  sent during a call, and how to begin together. Calm landing-style type,
 *  no warning styling. Copy lives in web/src/locales/sv.ts. */
export default function PrivacyPage({ onBack }: { onBack: () => void }) {
  const email = t('privacy.contactEmail');
  return (
    <div className="ot-land">
      <header className="ot-land-top">
        <div className="ot-land-topinner">
          <Brand />
          {/* Right-aligned like the chooser's Integritet link, and visible on
              phones too (the centred nav collapses there). */}
          <nav className="ot-land-topright" aria-label={t('landing.navLabel')}>
            <a className="ot-choose-privacy" href="/">
              <span aria-hidden="true">← </span>
              {t('privacy.back')}
            </a>
          </nav>
        </div>
      </header>
      <div className="ot-land-scroll">
        <main className="ot-privacy">
          <h1>{t('privacy.title')}</h1>
          <p className="ot-privacy-lead">{t('privacy.intro')}</p>
          <section>
            <h2>{t('privacy.browserTitle')}</h2>
            <p>{t('privacy.browserBody')}</p>
          </section>
          <section>
            <h2>{t('privacy.sendTitle')}</h2>
            <p>{t('privacy.sendBody')}</p>
            <p>{t('privacy.training')}</p>
            <p>{t('privacy.stats')}</p>
          </section>
          <section>
            <h2>{t('privacy.togetherTitle')}</h2>
            <p>{t('privacy.togetherBody')}</p>
          </section>
          <p className="ot-privacy-contact">
            {t('privacy.contactPrefix')}{' '}
            <a href={`mailto:${email}`}>{email}</a>
          </p>
          <p>
            <button type="button" className="ot-land-ghost" onClick={onBack}>
              ← {t('privacy.back')}
            </button>
          </p>
        </main>
      </div>
    </div>
  );
}
