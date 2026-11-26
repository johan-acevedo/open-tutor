// Focus for start-view changes. The household picker returns focus to its
// opener when that control is still on screen; when the picker closes onto a
// new view (a picked learner's band view, or "+ Någon ny" to the chooser)
// the opener is gone with the old view, so focus moves to the new view's
// start control instead: the landing hero CTA, else the chooser's first
// card CTA.

/** Focus the current start view's primary start control. True when found. */
export function focusStartControl(root: ParentNode = document): boolean {
  const hero = root.querySelector<HTMLElement>('.ot-land-hero .ot-land-cta');
  if (hero) {
    hero.focus();
    return true;
  }
  const card = root.querySelector<HTMLElement>('.ot-choose-card .ot-choose-cta');
  if (card) {
    card.focus();
    return true;
  }
  return false;
}
