import { createContext, useContext, type ReactNode } from 'react';
import '@fontsource-variable/lexend/wght.css';
import { BANDS, type BandConfig, type BandId } from './bands';

const BandContext = createContext<BandConfig>(BANDS.primary);

/** Band theme provider. Lexend (middle and upper) is self-hosted via
 *  fontsource, never a font CDN; the browser only fetches it where a band
 *  theme uses it. */
export function BandProvider({ band, children }: { band: BandId; children: ReactNode }) {
  const config = BANDS[band];
  return (
    <BandContext.Provider value={config}>
      {config.theme.stylesheet && <style>{config.theme.stylesheet}</style>}
      {children}
    </BandContext.Provider>
  );
}

export function useBand() {
  return useContext(BandContext);
}
