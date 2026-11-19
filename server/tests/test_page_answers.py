import asyncio

from open_tutor.page_answers import PageAnswers, answers_text


def make(settle=0.02, window=4.0, clock=None, wait_free=None):
    prompts, notes, records = [], [], []

    async def note(text):
        notes.append(text)

    kwargs = {"settle_s": settle, "spoken_window_s": window}
    if clock is not None:
        kwargs["clock"] = clock
    if wait_free is not None:
        kwargs["wait_free"] = wait_free
    box = PageAnswers(prompts.append, note, lambda kind, data: records.append((kind, data)), **kwargs)
    return box, prompts, notes, records


def test_three_boxes_sent_together_become_one_prompt():
    async def run():
        box, prompts, notes, records = make()
        box.add("p2", "svar-1", "11")
        box.add("p2", "svar-2", "14")
        box.add("p2", "svar-3", "28")
        await asyncio.sleep(0.08)
        return prompts, notes, records

    prompts, notes, records = asyncio.run(run())
    assert len(prompts) == 1 and notes == []
    assert "svar-1: 11" in prompts[0] and "svar-3: 28" in prompts[0]
    assert records == [("prompt", {"kind": "page_answer", "parts": 3, "page": "p2", "reply": True})]


def test_answer_said_aloud_and_sent_gets_no_second_reply():
    async def run():
        box, prompts, notes, _ = make()
        box.child_spoke("det blir 28")
        box.add("p3", "svar", "28")
        await asyncio.sleep(0.08)
        return prompts, notes

    prompts, notes = asyncio.run(run())
    assert prompts == []
    assert len(notes) == 1 and "p3" in notes[0] and "28" in notes[0]


def test_speech_just_after_the_send_also_counts():
    async def run():
        box, prompts, notes, _ = make(settle=0.05)
        box.add("p3", "svar", "28")
        await asyncio.sleep(0.01)
        box.child_spoke("det blir 28")
        await asyncio.sleep(0.1)
        return prompts, notes

    prompts, notes = asyncio.run(run())
    assert prompts == [] and len(notes) == 1


def test_old_speech_does_not_swallow_a_later_answer():
    now = [100.0]

    async def run():
        box, prompts, notes, _ = make(clock=lambda: now[0])
        box.child_spoke("det blir 38")
        now[0] += 30.0
        box.add("p4", "svar", "38")
        await asyncio.sleep(0.08)
        return prompts, notes

    prompts, notes = asyncio.run(run())
    assert len(prompts) == 1 and notes == []


def test_resending_a_box_keeps_the_last_value():
    assert "7" in answers_text([("p1", "a", "7")])

    async def run():
        box, prompts, _, _ = make()
        box.add("p1", "a", "6")
        box.add("p1", "a", "7")
        await asyncio.sleep(0.08)
        return prompts

    prompts = asyncio.run(run())
    assert len(prompts) == 1 and ": 7" in prompts[0] and ": 6" not in prompts[0]


def test_answer_waits_until_the_tutor_has_finished_speaking():
    # Real call 2026-11-19: an answer sent while the tutor spoke cut its sentence off.
    async def run():
        free = asyncio.Event()

        async def wait_free():
            await free.wait()

        box, prompts, notes, _ = make(wait_free=wait_free)
        box.add("p1", "svar", "16")
        await asyncio.sleep(0.08)
        before = list(prompts)
        free.set()
        await asyncio.sleep(0.02)
        return before, prompts, notes

    before, prompts, notes = asyncio.run(run())
    assert before == [] and len(prompts) == 1 and notes == []


def test_child_speaking_during_the_wait_gets_one_reply_not_two():
    async def run():
        free = asyncio.Event()

        async def wait_free():
            await free.wait()

        box, prompts, notes, _ = make(wait_free=wait_free)
        box.add("p1", "svar", "16")
        await asyncio.sleep(0.05)
        box.child_spoke("det blir 16")
        free.set()
        await asyncio.sleep(0.02)
        return prompts, notes

    prompts, notes = asyncio.run(run())
    assert prompts == [] and len(notes) == 1


def test_wait_until_free_returns_when_speech_ends():
    from types import SimpleNamespace

    from open_tutor.agent import wait_until_free

    async def run():
        session = SimpleNamespace(agent_state="speaking", user_state="listening")

        async def finish():
            await asyncio.sleep(0.03)
            session.agent_state = "listening"

        asyncio.create_task(finish())
        await asyncio.wait_for(wait_until_free(session, poll_s=0.01), timeout=1)
        return session.agent_state

    assert asyncio.run(run()) == "listening"


def test_spoken_turn_does_not_expire_during_a_long_wait():
    # Review of PR #83: said and typed together, then a long tutor reply.
    async def run():
        now = [0.0]
        free = asyncio.Event()

        async def wait_free():
            await free.wait()

        box, prompts, notes, _ = make(window=4.0, clock=lambda: now[0], wait_free=wait_free)
        box.child_spoke("det blir 16")
        box.add("p1", "svar", "16")
        await asyncio.sleep(0.05)
        now[0] = 30.0  # the tutor spoke for a long time
        free.set()
        await asyncio.sleep(0.02)
        return prompts, notes

    prompts, notes = asyncio.run(run())
    assert prompts == [] and len(notes) == 1


def test_close_drops_a_waiting_answer():
    async def run():
        free = asyncio.Event()

        async def wait_free():
            await free.wait()

        box, prompts, notes, _ = make(wait_free=wait_free)
        box.add("p1", "svar", "16")
        await asyncio.sleep(0.05)
        box.close()
        free.set()
        await asyncio.sleep(0.02)
        return prompts, notes

    prompts, notes = asyncio.run(run())
    assert prompts == [] and notes == []


def test_resend_during_the_wait_keeps_the_spoken_decision():
    # Re-check of PR #83: speak+send at 0 s, resend at 12 s, tutor done at 30 s.
    async def run():
        now = [0.0]
        free = asyncio.Event()

        async def wait_free():
            await free.wait()

        box, prompts, notes, _ = make(window=4.0, clock=lambda: now[0], wait_free=wait_free)
        box.child_spoke("det blir 16")
        box.add("p1", "svar", "16")
        await asyncio.sleep(0.05)
        now[0] = 12.0
        box.add("p1", "svar", "16")
        await asyncio.sleep(0.05)
        now[0] = 30.0
        free.set()
        await asyncio.sleep(0.02)
        return prompts, notes

    prompts, notes = asyncio.run(run())
    assert prompts == [] and len(notes) == 1 and "16" in notes[0]


def test_a_changed_value_after_saying_the_old_one_gets_feedback():
    async def run():
        now = [0.0]
        free = asyncio.Event()

        async def wait_free():
            await free.wait()

        box, prompts, notes, _ = make(window=4.0, clock=lambda: now[0], wait_free=wait_free)
        box.child_spoke("det blir 16")
        box.add("p1", "svar", "16")
        await asyncio.sleep(0.05)
        now[0] = 12.0
        box.add("p1", "svar", "17")
        await asyncio.sleep(0.05)
        now[0] = 30.0
        free.set()
        await asyncio.sleep(0.02)
        return prompts, notes

    prompts, notes = asyncio.run(run())
    assert len(prompts) == 1 and "17" in prompts[0] and notes == []


def test_unrelated_question_during_the_wait_still_gets_answer_feedback():
    # Re-check of PR #83: send 16, then ask something else while it waits.
    async def run():
        now = [0.0]
        free = asyncio.Event()

        async def wait_free():
            await free.wait()

        box, prompts, notes, _ = make(window=4.0, clock=lambda: now[0], wait_free=wait_free)
        box.add("p1", "svar", "16")
        await asyncio.sleep(0.05)
        now[0] = 10.0
        box.child_spoke("kan du säga uppgiften igen")  # an unrelated question, well after the send
        now[0] = 20.0
        free.set()
        await asyncio.sleep(0.02)
        return prompts, notes

    prompts, notes = asyncio.run(run())
    assert len(prompts) == 1 and notes == []


def test_resend_with_an_unrelated_question_between_still_gets_feedback():
    # Round 3 of PR #83: send 0 s, unrelated question 8 s, resend 20 s, done 30 s.
    async def run():
        now = [0.0]
        free = asyncio.Event()

        async def wait_free():
            await free.wait()

        box, prompts, notes, _ = make(window=4.0, clock=lambda: now[0], wait_free=wait_free)
        box.add("p1", "svar", "16")
        await asyncio.sleep(0.05)
        now[0] = 8.0
        box.child_spoke("vad betyder uttryck")
        now[0] = 20.0
        box.add("p1", "svar", "18")
        await asyncio.sleep(0.05)
        now[0] = 30.0
        free.set()
        await asyncio.sleep(0.02)
        return prompts, notes

    prompts, notes = asyncio.run(run())
    assert len(prompts) == 1 and notes == []


def test_answer_said_late_or_in_a_long_turn_gets_one_reply():
    # Round 3 of PR #83: send 0 s, the same answer committed at 8 s, release at 30 s.
    async def run():
        now = [0.0]
        free = asyncio.Event()

        async def wait_free():
            await free.wait()

        box, prompts, notes, _ = make(window=4.0, clock=lambda: now[0], wait_free=wait_free)
        box.add("p1", "svar", "16")
        await asyncio.sleep(0.05)
        now[0] = 8.0
        box.child_spoke("ja alltså först tog jag fem gånger tre och sen blir det 16")
        now[0] = 30.0
        free.set()
        await asyncio.sleep(0.02)
        return prompts, notes

    prompts, notes = asyncio.run(run())
    assert prompts == [] and len(notes) == 1


def test_decimal_comma_and_several_boxes_match_what_was_said():
    from open_tutor.page_answers import _norm

    assert _norm("Det blir 2,5!") == "det blir 2.5"

    async def run():
        box, prompts, notes, _ = make()
        box.child_spoke("svaret är 2,5 och sen 7")
        box.add("p2", "a", "2,5")
        box.add("p2", "b", "7")
        await asyncio.sleep(0.08)
        return prompts, notes

    prompts, notes = asyncio.run(run())
    assert prompts == [] and len(notes) == 1


def test_signs_and_operators_stay_part_of_the_value():
    from open_tutor.page_answers import _norm

    assert _norm("-16") == "-16" and _norm("3/4") == "3/4" and _norm("3+4") == "3+4"
    assert _norm("3/4") != _norm("3+4")

    async def run():
        box, prompts, notes, _ = make()
        box.child_spoke("det blir 16")
        box.add("p1", "svar", "-16")
        await asyncio.sleep(0.08)
        return prompts, notes

    prompts, notes = asyncio.run(run())
    assert len(prompts) == 1 and notes == []
