import { t } from '../locales/sv';

/** Talarum brand: the flame icon plus a lowercase wordmark.
 *  All three band themes are dark canvases, so the light text reads
 *  cleanly everywhere. */
export default function Brand() {
  return (
    <span className="ot-land-brand">
      <span className="ot-land-mark" aria-hidden="true">
        <img src="/talarum-icon.svg" alt="" width={30} height={30} />
      </span>
      <span className="ot-brand-word" aria-label={t('brand.name')}>
        talarum
      </span>
    </span>
  );
}
