from index_org_webhook.classify import classify, note_title, task_heading


def test_leading_cues_are_tasks() -> None:
    assert classify("todo call the dentist") == "task"
    assert classify("to do buy milk") == "task"
    assert classify("Remind me to take out the compost") == "task"
    assert classify("don't forget the library books") == "task"
    assert classify("I need to file the insurance claim") == "task"
    assert classify("I have to email Megan") == "task"
    assert classify("please remember to lock the shed") == "task"
    assert classify("task pick up dry cleaning") == "task"


def test_imperative_openers_are_tasks() -> None:
    assert classify("call the dentist") == "task"
    assert classify("buy milk") == "task"
    assert classify("email the parish office") == "task"
    assert classify("schedule a haircut") == "task"
    assert classify("book the campsite") == "task"
    assert classify("pay the water bill") == "task"
    assert classify("pick up Arrowhead from the vet") == "task"
    assert classify("follow up with Fountain Tire") == "task"


def test_filler_words_are_stripped_before_classify() -> None:
    assert classify("um call the dentist") == "task"
    assert classify("uh, todo buy milk") == "task"
    assert classify("um the repairman came") == "note"


def test_notes_are_not_tasks() -> None:
    assert classify("The repairman came and cleaned the AC") == "note"
    assert classify("Walked Arrowhead Trail this morning") == "note"
    assert classify("I called OPB yesterday") == "note"
    assert classify("Thoughts about the Sunday readings") == "note"


def test_task_heading_strips_cue() -> None:
    assert task_heading("todo call the dentist") == "Call the dentist"
    assert task_heading("Remind me to take out the compost") == "Take out the compost"


def test_note_title_uses_first_clause() -> None:
    assert note_title("Walked Arrowhead Trail. It was icy.") == "Walked Arrowhead Trail"
    long = "a " * 80
    title = note_title(long)
    assert len(title) <= 73
    assert title.endswith("…")
