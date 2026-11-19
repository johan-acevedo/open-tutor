import { createContext, useContext, type ReactNode } from 'react';
import { BANDS, type BandConfig, type BandId } from './bands';

const BandContext = createContext<BandConfig>(BANDS.primary);

export function BandProvider({ band, children }: { band: BandId; children: ReactNode }) {
  const config = BANDS[band];
  return (
    <BandContext.Provider value={config}>
      {band !== 'primary' && (
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fontsource-variable/lexend@5.3.0/index.css" />
      )}
      {config.theme.stylesheet && <style>{config.theme.stylesheet}</style>}
      {children}
    </BandContext.Provider>
  );
}

export function useBand() {
  return useContext(BandContext);
}
