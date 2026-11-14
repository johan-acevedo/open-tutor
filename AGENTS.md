# Working in this repository

For any agent (or person) picking up work here. This file holds the purpose and spirit of
the project and the few rules that protect the children who use it. It does not prescribe
technical solutions: those are ours to explore.

## What this is

Open Tutor is a live voice tutor for school children. A child opens a page, talks with
"Räven", a fox, about their real homework, and sees explanations on a screen beside it. It
is used by the owner's own children, aged 9 to 15 in Sweden, and by a small public test.

The product speaks Swedish. Code, comments, docs, commits and PRs are in English.

## What we are building toward

A summary of the founding brief in `README.md`. Read the brief itself before work that
shapes how the tutor behaves or what the child sees; where this summary and the brief
differ, the brief wins.

- **It starts with a parent's need.** The children bring their actual homework on ordinary
  weekdays. There is no scripted demo. What happens in those sessions guides development,
  ahead of anyone's prediction of what children want.
- **The tutor is a calm older student sitting beside the child.** Patient, approachable,
  interested in what the child thinks. It asks, it explains directly when that helps, and it
  changes approach when an explanation does not land. It does not turn every difficulty into
  another question the child cannot answer.
- **The child owns the work.** The tutor helps them get going and find their own words. It
  does not write the essay. This boundary is a teacher's judgement, refined through use, not
  an exhaustive rule set.
- **It feels like a live call.** No push-to-talk. The tutor answers without making the child
  wait in silence, speaks when addressed or when it has something useful to add, and leaves
  room for the child to think, read or write.
- **The screen gives the voice something to show.** Choose the medium that explains the idea,
  and keep speech in step with what the child can actually see.
- **Learning continues through other educators' work.** The tutor may find and share public
  resources and use its own judgement.
- **Easy to arrive.** No installation and no account, on whatever device the child has.
- **Swedish first**, across school subjects. Other languages and language switching later.
- **Open and not for profit.** Built in public so developers, educators and families can
  improve, adapt and run it.

Left out on purpose until the owner asks for them: accounts, sync between devices, parent
dashboards and parent instructions, billing, resource ratings, a whiteboard the child edits,
formal curriculum integration, several tutor personalities.

What we are trying to learn from real use, and what any change should be judged against:

- Does the tutor give the child enough time to think and speak?
- Does the child move forward while the work stays theirs?
- Do the visual explanations clarify the subject?
- Does the tutor recognise when to explain, ask, demonstrate or change approach?
- Can the child apply what they understood to the next task?
- Do they want to come back when they need help?

## Explore freely

Everything technical here is the current answer, not a commitment: the models and providers,
the voice stack, how the screen is produced, the frameworks, the hosting. Each was chosen
because it served the experience above at the time, and each can be replaced when something
serves it better. Nothing in this repository should be read as "this is how it must be
done".

- **Judge a solution by the experience,** in real sessions with real children where
  possible, and by measurements of what the child would feel (how long before the tutor
  speaks, how long before the screen shows something) rather than by how elegant it is.
- **Try things small and where no child is affected,** then show the before and after.
- **Write down what you learned,** including what did not work and why, with the date. An
  idea that was dropped was dropped for a stated reason; a new take that answers that
  reason is welcome.
- **Say what you did not test.** A green test run is supporting evidence. A real session is
  the proof.

## Finding your way

The current shape, described where it is kept current:

- `README.md` and `PRD.md`: the founding brief and product requirements.
- `docs/smart-screen.md`: the state file for the tutor and its screen. What runs where,
  decisions and their reasons, measurements, what real test calls settled, open questions.
  Read it before starting and update it in the same pull request as your change.
- `server/README.md`: running the service locally, settings, tests, probes that run a real
  session, and the per-session debug log.
- `screen/README.md` and `screen/NOTES.md`: how the screen is built today and why.
- `deploy/README.md`: hosting an instance.

The code is in `web/` (the page), `server/` (the voice worker and web service), `screen/`
(the screen's shell, reference and tools) and `tools/` (curriculum and textbook sources).
CI runs the server and web test suites on every pull request; the commands are in
`.github/workflows/` and `server/README.md`.

## Protecting the children and the people testing

These are not technical preferences. They hold whatever the solution looks like.

- **Children's words stay private.** Session logs hold what children said. They stay on the
  machine that wrote them. Never copy transcript text, names or schoolwork into the
  repository, pull requests, issues or other services; report counts and timings. Test
  learners are fictional.
- **This repository is public.** No secrets, no private addresses or contact details.
  Secrets come from the host's private configuration and are never printed or logged.
- **What a model writes is untrusted** until it has been made safe to show a child.
- **A live call is someone's lesson.** Never restart or stop a service while a call is
  running, and never stop processes by name pattern; use the service's own controls. Run
  experiments under your own names and ports so they cannot take a real child's call.
- **Try changes on a development instance first**, then deploy to the public instance.
- **Real providers cost money.** Run the narrowest live test that proves the change.

## Working together

- `main` is the trunk. Branch from it, open a pull request, and merge when the diff has been
  reviewed and CI is green. A reviewer should come from a different model family than the
  author.
- When handing off, name the branch and commit, what is on `main`, where it runs, what you
  verified on the real thing, and what you did not.
