# Open Tutor: review meeting notes

Companion to the [presentation](board-meeting.html) and [technical plan](../BUILD-PLAN.md).

## 1. Ready to build the first real homework session

The next investment should be a working teaching loop, guided by the product and visual foundation.

This meeting covers the two requested steps: preserve the agreed foundation in a PR and recommend the technical approach. It does not claim that the tutor has been implemented or deployed. The wingless character, inward or frontal gaze, Swedish-first teaching, and accountless arrival are already agreed. Provider and hosting choices are proposals for review.

## 2. One URL, then ordinary schoolwork

Success means the child understands more and can take the next step themselves.

The child writes long assignments in their school document or on paper, sharing drafts when useful. The board is tutor-controlled. Continuity means notes in this browser, not automatic cross-device sync. Each later session starts with a fresh board. The first test is a real homework session with Johan present, rather than a staged subject-specific showcase.

## 3. Keep the companion. Give the lesson room.

These are design references. Making the interaction work is the next phase.

The package includes the PRD, visual guide, ten selected screen states, and the revised character sheet. Some reference and intermediate images remain with the generation prompts for provenance. The earlier competitor and coaching reports stay local. Precise spacing and colour tokens remain implementation defaults, not extra decisions Johan must settle now.

## 4. Build our experience. Borrow selected working parts.

Reusing patterns saves effort while preserving your specific teaching experience.

The research repositories are real code, but reading source is not runtime verification. The recommendation uses the familiar Python stack because t3-call already integrates the relevant speech providers and visual work. No external project source has been copied yet. Preserve MIT notices when copying selected code. Do not introduce a dependency on the t3-call app itself. No AGPL code was copied.

## 5. Three pieces, with clear responsibilities

We can change a voice or model without rebuilding the whole experience.

There are two backend processes: a small FastAPI web service and the persistent LiveKit worker. This diagram groups them as our tutor service to keep the responsibilities readable. The HTTPS page and uploads use our web service; audio and call data use LiveKit. Direct provider plugins perform inference. A coding-agent harness is not part of each conversational turn. LiveKit documents media, RPC and state exchange; this architecture remains untested here.

## 6. Familiar parts, each with one job

No account platform, central learner database, or local GPU is needed for the first family version.

Start file support with PDFs, PNG/JPEG photos, screenshots and pasted text. The format choice is proposed rather than an exclusion of all future formats. The frontend build can be served by FastAPI, avoiding separate frontend hosting for the first family deployment. Speech provider key names are present, but their balances and live performance are not verified. The exact media model and voice selection happen in the next phase.

## 7. A flexible teaching board, without building an editor

Preserve expressive teaching while avoiding an unnecessary canvas-editor dependency.

This does not constrain every explanation to a fixed set of cards. The tutor can create web content in isolated panels as well as structured equations and SVG. A background tool can publish slower imagery later. Use a browser acknowledgement and shared visual identifiers to coordinate speech with what is actually visible. Nothing is implemented yet. tldraw templates and the tldraw SDK have different licensing; the SDK requires a production key.

## 8. The LLM needs a supported route for tutoring

Settle the route before real homework. No provider settings or credentials have been changed.

The earlier API-availability assumption was incomplete. Do not disguise traffic or silently replace the chosen model. Also test HTTP streaming and tool compatibility; a Responses endpoint does not prove WebSocket support.

## 9. Use the home lab, with managed call transport

Start with family use. A public demo can follow with a simple owner-controlled spending limit.

ThinkCentre is proposed from inventory evidence, which records always-on intent rather than guaranteed availability. We have not connected to it, changed DNS, installed services or deployed the app. The existing Mini tunnel can route HTTP over the tailnet. No LiveKit or OpenCode key names appeared in the inspected homelab development environment; they may exist in other service configuration. The first implementation must locate provisioning. No costs are measured; existing credits cover the experiment without a new billing product.

## 10. Four milestones, each ending in something usable

The first working session is the priority; elaborate animation and expansion come later.

Milestone A uses fictional material until the LLM route is settled. It is not a separate product demo; it tests the technical uncertainties before the full workspace is built. B keeps voice, visual teaching, homework and continuity together. C checks microphone permissions, school restrictions, reconnects and a usable URL. D uses whatever schoolwork the child brings, without a prepared subject-specific script.

## 11. A grounded proposal, with the unknowns visible

There is no measured cost, latency claim, deployed app, or live teaching result in this package.

The competitor research was useful for discovery but contains unverified marketing claims. The new technical recommendation is based on targeted source inspection and official documentation. The artifact checks apply to documents and the presentation, not to a tutor application. Do not mistake polished mockups for functioning software. The package includes a reproducible deck builder and a primary-source evidence record.

## 12. A concrete direction to take into the first build

Next authorised build phase, after your review: the integration experiment. Nothing has been deployed.

The PR remains open for review and has not been merged. The project licence is still unselected; MIT is proposed for easy reuse, not applied unilaterally. The spending limit for a broader public demo is an operational follow-up, not an account or payment system for the children. Johan can review this package asynchronously; no immediate answers are required to understand the recommendation.
