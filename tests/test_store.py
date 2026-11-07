from claugram.storage import Store


def make_store(tmp_path):
    return Store(tmp_path / "state.sqlite3")


def test_question_flow(tmp_path):
    s = make_store(tmp_path)
    pid = s.upsert_project("demo", str(tmp_path))
    qid = s.create_question(pid, None, 123, "A or B?", ["A", "B"], 60)
    s.attach_question_message(qid, 555)
    assert s.find_question_by_message(555)["id"] == qid
    assert s.find_question_by_short(qid[:16])["id"] == qid
    assert s.answer_question(qid, "B", 123)
    assert not s.answer_question(qid, "again", 123)  # already answered
    row = s.get_question(qid)
    assert row["status"] == "answered" and row["answer_text"] == "B"
    s.close()


def test_permission_flow(tmp_path):
    s = make_store(tmp_path)
    pid = s.upsert_project("demo", str(tmp_path))
    perm = s.create_permission(pid, None, 123, "Bash", {"command": "git push"},
                               "high", "publishes code", 60)
    assert s.decide_permission(perm, "deny", 123, "no")
    row = s.get_permission(perm)
    assert row["decision"] == "deny"
    s.close()


def test_job_queue(tmp_path):
    s = make_store(tmp_path)
    pid = s.upsert_project("demo", str(tmp_path))
    jid = s.enqueue_job(pid, 1, "code", "do a thing")
    claimed = s.claim_next_job()
    assert claimed["id"] == jid and claimed["status"] == "queued"
    assert s.claim_next_job() is None  # nothing left queued
    s.finish_job(jid, "done", "ok")
    s.close()
