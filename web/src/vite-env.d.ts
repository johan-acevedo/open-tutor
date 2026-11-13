/// <reference types="vite/client" />

declare module 'virtual:screen-shell' {
  export const frameHtml: string;
  export const shellCss: string;
  export const shellJs: string;
  export const mapLanData: string;
}

declare module 'virtual:screen-demo' {
  export const klockanBody: string;
  export const klockanPatch: string;
  export const divisionBody: string;
  export const divisionPatch: string;
}
