import asyncio

from open_tutor.page_answers import PageAnswers, answers_text


def make(settle=0.02, window=4.0, clock=None):
    prompts, notes, records = [], [], []

    async def note(text):
        notes.append(text)

    kwargs = {"settle_s": settle, "spoken_window_s": window}
    if clock is not None:
        kwargs["clock"] = clock
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
        box.child_spoke()
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
        box.child_spoke()
        await asyncio.sleep(0.1)
        return prompts, notes

    prompts, notes = asyncio.run(run())
    assert prompts == [] and len(notes) == 1


def test_old_speech_does_not_swallow_a_later_answer():
    now = [100.0]

    async def run():
        box, prompts, notes, _ = make(clock=lambda: now[0])
        box.child_spoke()
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
