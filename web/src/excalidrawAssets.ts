// Must be imported before '@excalidraw/excalidraw': the library reads this when it loads and
// otherwise fetches its fonts from a public CDN. Fonts are served from public/excalidraw/fonts.
declare global {
  interface Window {
    EXCALIDRAW_ASSET_PATH?: string | string[];
  }
}

window.EXCALIDRAW_ASSET_PATH = new URL('excalidraw/', document.baseURI).href;

export {};
