import { useState } from 'react';
import type { Note } from '../protocol';
import { t } from '../locales/sv';
import type { BandId } from '../bands';

type Props = {
  learnerName: string;
  notes: Note[];
  onBack: () => void;
  endReason?: string | null;
  band?: BandId;
};

const SHARE_URL = 'https://talarum.se/';

/** Calm tip-a-parent card: system share sheet on mobile, clipboard copy
 *  otherwise. No UTM, no referral ids, no tracking. */
function ShareCard({ band }: { band: BandId }) {
  const [copied, setCopied] = useState(false);
  const young = band !== 'upper';
  async function share() {
    const text = t('end.shareText');
    try {
      if (typeof navigator !== 'undefined' && 'share' in navigator) {
        await (navigator as Navigator & { share: (d: { title: string; text: string; url: string }) => Promise<void> }).share({
          title: 'Talarum',
          text,
          url: SHARE_URL,
        });
        return;
      }
    } catch {
      /* user dismissed the sheet or share failed: fall through to copy */
    }
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(SHARE_URL);
      } else {
        const ta = document.createElement('textarea');
        ta.value = SHARE_URL;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      }
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2500);
    } catch {
      /* clipboard unavailable: the URL is visible nowhere, so stay quiet */
    }
  }
  return (
    <section className="ot-share" aria-label={young ? t('end.shareTitleYoung') : t('end.shareTitleOld')}>
      <h2>{young ? t('end.shareTitleYoung') : t('end.shareTitleOld')}</h2>
      <p>{t('end.shareText')}</p>
      <button type="button" className="ot-land-ghost" onClick={() => void share()}>
        {copied ? t('end.shareCopied') : t('end.shareButton')}
      </button>
    </section>
  );
}

export default function EndCard({ learnerName, notes, onBack, band = 'primary' }: Props) {
export default function EndCard({ learnerName, notes, onBack, endReason, band = 'primary' }: Props) {
  const last = notes.length > 0 ? notes[notes.length - 1] : null;
  return (
    <div className="ot-endcard">
      <h1>{learnerName.trim() !== '' ? t('end.greetingNamed', { name: learnerName }) : t('end.greetingAnon')}</h1>
      {endReason === 'idle_timeout' && <p className="ot-endcard-idle">{t('end.idle')}</p>}
      {(last?.topic || last?.next) && (
        <div className="ot-endcard-notes">
          {last?.topic && (
            <p>
              <strong>{t('end.topicLabel')}</strong> {last.topic}
            </p>
          )}
          {last?.clicked && (
            <p>
              <strong>{t('end.clickedLabel')}</strong> {last.clicked}
            </p>
          )}
          {last?.next && (
            <p>
              <strong>{t('end.nextLabel')}</strong> {last.next}
            </p>
          )}
        </div>
      )}
      <button type="button" className="ot-land-cta" onClick={onBack}>
        {t('end.back')}
      </button>
      <ShareCard band={band} />
    </div>
  );
}
