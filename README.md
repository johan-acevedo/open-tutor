# Open Tutor

A live voice tutor that helps children understand their schoolwork and take the next step themselves.

## Founding brief

This document records the project's starting intent. Open Tutor is a working name. There is no application yet.

The [product requirements](PRD.md), [visual style guide](design/STYLE-GUIDE.md), and [selected image mockups](design/mockups/pass-2/README.md) develop this intent into the first experience. The [build plan](BUILD-PLAN.md) and [review presentation](review/README.md) propose how to reach the first homework session.

## Why this exists

This project starts with a parent's immediate need. Johan's children, aged 9 to 15 in Sweden, need help with homework, assignments, and preparation for tests. Sometimes they understand more than they can put into words. Sometimes a test reveals a gap that needs patient attention.

An older student sitting beside them could listen, find a starting point, explain something differently, and help them keep going. Open Tutor aims to offer that kind of support through a browser, using live voice conversation and a shared visual workspace.

The first users are Johan's own children, with their actual schoolwork. They will use the tool on ordinary weekdays. There is no prepared demonstration or scripted assignment. What happens in those sessions should guide development.

The wider ambition is to help children across the world get better educational support. This is intended as an open-source project that others can improve, adapt, and run. Making money is not the motivation. Adults learning a trade or an advanced subject may benefit from the same approach later, but children are the initial focus.

## Arrive and meet the tutor

A child opens the page on a school Chromebook or a Windows PC. There is no installation and no account requirement.

A large avatar makes the voice tutor the centre of the starting page. The tutor greets the child and invites them into a conversation. It takes responsibility for helping the child get started, as a welcoming older student would.

The child can explain what they need, drop in files or photographs of paper assignments and tests, or paste text and screenshots from the clipboard. The exact supported file formats remain an implementation decision.

After the browser's initial microphone and audio interaction, the session feels like a live call, without push-to-talk. The tutor remains present, listening and following the material available in the session. It speaks when addressed or when it has something useful enough to contribute, with initiative to move learning forward. Silence for thinking, reading, writing, or watching a video is a natural part of the session.

A permanent text input gives the child another way to communicate. The text field and call controls belong to the stable page layout, outside the tutor's dynamically generated whiteboard content.

## A calm older student

The tutor is patient, approachable, and interested in what the child thinks. It asks questions, gives explanations, offers examples, and changes approach when an explanation does not help.

The tutor uses the judgement expected of a teacher helping with an assignment. It helps the child get going and develop their own work. It does not write the child's essay for them. A teacher-like instruction is the starting approach to this boundary. We will refine the behaviour through use rather than define an exhaustive set of rules in advance.

Questioning is one teaching tool. The tutor also explains directly when that helps. It should avoid turning every difficulty into another question the child cannot answer.

It celebrates when the child understands something they previously struggled with. When the child is interested and willing, it suggests a next step, follows their curiosity, and goes deeper into the subject. School level, assignment context, and the likely curriculum help orient the conversation. Formal curriculum mapping is not a prerequisite for the first version.

## The whiteboard gives the voice something to show

The tutor has a visual whiteboard on the page that it can update while speaking. It can draw diagrams, display text and equations, organise ideas, and explain a process step by step.

The visual tools may include vector graphics, generated web layouts, animations, and generated images. Choose the medium that helps explain the idea. Coordinate speech with what the child can actually see, and keep the session flowing while slower content is generated.

Initially, the tutor controls the whiteboard. The child does not draw on it or edit it. The exact layout and the way the large avatar makes room for explanations remain design experiments.

The initial character direction is an original, welcoming animal-hybrid or game-inspired companion. The children's interests include Minecraft, Fortnite, Roblox, anime such as Naruto and One Piece, Among Us, and Geometry Dash. These references inform the design exploration. The character needs to appeal across the initial age range.

## Learning can continue through other educators' work

The tutor can find and recommend public educational resources, including reading material and videos. These resources are part of the conversation.

For example, a child struggles with double bonds in chemistry. The tutor discusses their understanding, draws an explanation, and suggests a short video on the topic. Afterwards, they talk about the video and revisit what was confusing.

Give the model tools to discover and share resources, and let it exercise judgement. The first version does not need resource approval workflows, curated allowlists, quality gates, or helpfulness ratings. Personal feedback about which resources work for a learner may be useful later.

## Languages and continuity

The initial focus is teaching in Swedish across subjects such as maths, religion, social sciences, and chemistry. English, Spanish, and natural language switching remain goals for later, including explaining in one language while practising another.

Voice selection starts with the quality of spoken Swedish, with no preference for a masculine or feminine voice. Mixed-language teaching can follow initial use.

The tutor remembers the learner across visits. Initially, learner profiles and continuity live in browser-local storage, with no account. A returning child can choose their saved name, and siblings sharing a browser can keep separate profiles. Someone new can start without registration.

This initial memory belongs to the browser and device. Clearing browser storage loses that continuity. Browser-local memory does not imply on-device inference: live sessions still send the necessary content to the backend and selected providers.

## Ordinary schoolwork is the first proving ground

### Starting a book review

A child has read a book but does not know what to write. The tutor asks about something they remember, what they thought of a character, or a scene that made an impression.

As they talk, the tutor helps the child identify their own observations and organise them on the whiteboard. The child chooses an idea and begins writing in their own words. Where the child writes the assignment, and how the tutor sees later revisions, remain open questions.

### Returning to a mathematical difficulty

A test or homework problem reveals confusion about division, multiplication tables, or equations. The child brings the material into the session.

The tutor explores how the child approaches the problem, explains the difficult step visually, and gives them another opportunity to apply it. The aim is understanding they can use on the next problem.

These examples explain the intent. They do not limit the initial tool to those subjects or define a scripted demo.

## Initial technical direction

Use LiveKit for live audio transport and agent session handling. Separate speech recognition, the tutor LLM, and speech synthesis so providers can change as capabilities improve.

For Johan's initial instance, the `homelab` Infisical project supplies prototype credentials and existing provider credits. The intended testing LLM is Spark through OpenCode Go. The exact model and its suitability for live streaming and tool use still need confirmation. Document and image understanding may require a separate provider.

Other contributors and hosts can use their own providers and credentials. Johan's provisioning setup is not an application dependency. Select speech services for live streaming, conversational responsiveness, and language quality.

Keep credentials in the backend runtime, outside the browser and repository. Browser-local learner storage and the server-side voice session are separate responsibilities.

This is a direction for the first implementation, not a commitment to specific speech providers or a finished architecture.

## What we need to learn

The first version should let the children use real schoolwork without preparation. We need to observe whether they find the tutor helpful and interesting, and whether they learn.

Questions to answer through use include:

- Does the tutor give the child enough time to think and speak?
- Can it help the child move forward while preserving ownership of their work?
- Do its visual explanations clarify the subject?
- Does it recognise when to explain, ask, demonstrate, or change approach?
- Can the child apply what they understood to another question or task?
- Do they want to return when they need help?

The balance of humour, encouragement, initiative, and direct explanation should emerge from these experiences. We do not need parents to predict every response to frustration before building.

## Keep the first version focused

Accounts, cross-device synchronisation, parent dashboards, parent instructions, billing, resource ratings, and child-editable whiteboards can come later. Formal curriculum integrations and multiple tutor personalities can also wait.

Inference costs are covered for the initial experiment. Johan may also open his hosted instance to others for a while. Sustainable access needs attention as usage grows, but should not dictate the first experience. Free trials and user-provided provider access remain possibilities, subject to what providers support.

The first version should deliver a welcoming live conversation, useful visual teaching, homework context, educational resources, and continuity in the same browser.

## Develop openly

Build in public so developers, educators, and families can contribute what they know. Contributions may improve the software, teaching behaviour, visual explanations, languages, or educational resources.

The repository begins with this brief so contributors can understand the motivation before implementation decisions accumulate. The open-source licence and contribution process still need to be chosen. As the children use the tool, update this document to distinguish what we learned from what we initially assumed.
