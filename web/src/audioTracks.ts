/**
 * The agent can publish more than one audio track: the fox's speech, and the short
 * filler sounds it makes while the reply is still on its way (a separate
 * `background_audio` track, see server/open_tutor/fillers.py). One
 * <audio> element holds one stream, so a second live track needs its own element.
 */

/** Is this element already playing another track that is still live? */
export function audioElementBusy(el: HTMLAudioElement | null): boolean {
  if (!el) return false;
  const stream = el.srcObject as MediaStream | null | undefined;
  if (!stream || typeof stream.getAudioTracks !== 'function') return false;
  const tracks = stream.getAudioTracks();
  if (!Array.isArray(tracks) || tracks.length === 0) return false;
  // A stream whose tracks have all ended is a stale attach (reconnect), not a
  // second track: reuse the element for it.
  return tracks.some((track) => track?.readyState === 'live');
}
