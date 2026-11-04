// Client-side image downscaling for homework intake.
// Images are capped at 1600px on the long side and encoded as JPEG 0.85.

export type Downscaled = {
  bytes: Uint8Array;
  dataUrl: string;
  width: number;
  height: number;
  mimeType: string;
};

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('could not decode image'));
    img.src = src;
  });
}

/** Downscale an image file to max 1600px long side, JPEG quality 0.85. */
export async function downscaleImage(file: File | Blob, maxSide = 1600): Promise<Downscaled> {
  const objectUrl = URL.createObjectURL(file);
  try {
    const img = await loadImage(objectUrl);
    const naturalW = img.naturalWidth || img.width;
    const naturalH = img.naturalHeight || img.height;
    const scale = Math.min(1, maxSide / Math.max(naturalW, naturalH));
    const width = Math.max(1, Math.round(naturalW * scale));
    const height = Math.max(1, Math.round(naturalH * scale));
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('no 2d canvas context');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, width, height);
    ctx.drawImage(img, 0, 0, width, height);
    const blob: Blob | null = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.85));
    if (!blob) throw new Error('canvas toBlob failed');
    const buffer = new Uint8Array(await blob.arrayBuffer());
    const dataUrl = `data:image/jpeg;base64,${b64encode(buffer)}`;
    return { bytes: buffer, dataUrl, width, height, mimeType: 'image/jpeg' };
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

function b64encode(bytes: Uint8Array): string {
  let s = '';
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    s += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(s);
}

/** Convert a data URL back to bytes (for re-sending rendered pages). */
export function dataUrlToBytes(dataUrl: string): Uint8Array {
  const comma = dataUrl.indexOf(',');
  const b64 = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
