"""Emailing a task or action item from the dashboard: recipient validation,
subject/number capture, and the dashboard flash message."""
from .conftest import configure_mail, login


def test_email_task_sends_to_owner(client, db_session, member_user, fake_smtp):
    configure_mail(db_session)
    login(client, member_user)
    client.post("/tasks", data={"title": "Ship the report"})

    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Ship the report").one()

    r = client.post(f"/tasks/{task.id}/email", data={
        "to": member_user.email, "note": "Please prioritize this",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "ok=1" in r.headers["location"]

    assert len(fake_smtp.sent) == 1
    sent = fake_smtp.sent[0]
    assert sent["To"] == member_user.email
    assert f"Task #{task.id}" in sent["Subject"]
    body = sent.get_content()
    assert "Please prioritize this" in body


def test_email_action_item_sends_to_assignee(client, db_session, member_user, other_member,
                                              fake_smtp):
    configure_mail(db_session)
    login(client, member_user)
    client.post("/action-items", data={
        "description": "Send the pricing sheet", "assignee_id": str(other_member.id),
    })

    from app.models import ActionItem
    item = db_session.query(ActionItem).filter(
        ActionItem.description == "Send the pricing sheet"
    ).one()

    r = client.post(f"/action-items/{item.id}/email", data={
        "to": other_member.email, "note": "Any update?",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "ok=1" in r.headers["location"]

    assert len(fake_smtp.sent) == 1
    sent = fake_smtp.sent[0]
    assert sent["To"] == other_member.email
    assert f"Action Item #{item.id}" in sent["Subject"]
    assert "Any update?" in sent.get_content()


def test_email_rejects_unknown_recipient(client, db_session, member_user, fake_smtp):
    configure_mail(db_session)
    login(client, member_user)
    client.post("/tasks", data={"title": "Solo task"})

    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Solo task").one()

    r = client.post(f"/tasks/{task.id}/email", data={
        "to": "not-a-real-user@test.local", "note": "hi",
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "ok=0" in r.headers["location"]
    assert len(fake_smtp.sent) == 0


def test_email_rejects_disabled_recipient(client, db_session, member_user, other_member,
                                           fake_smtp):
    configure_mail(db_session)
    other_member.is_active = False
    db_session.add(other_member)
    db_session.commit()

    login(client, member_user)
    client.post("/tasks", data={"title": "Another task"})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Another task").one()

    r = client.post(f"/tasks/{task.id}/email", data={
        "to": other_member.email, "note": "hi",
    }, follow_redirects=False)
    assert "ok=0" in r.headers["location"]
    assert len(fake_smtp.sent) == 0


def test_email_without_mail_config_reports_error(client, db_session, member_user, fake_smtp):
    # No configure_mail() call -> host is empty, so notifier.send() fails cleanly.
    login(client, member_user)
    client.post("/tasks", data={"title": "No relay configured"})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "No relay configured").one()

    r = client.post(f"/tasks/{task.id}/email", data={
        "to": member_user.email, "note": "hi",
    }, follow_redirects=False)
    assert "ok=0" in r.headers["location"]
    assert len(fake_smtp.sent) == 0


def test_dashboard_shows_flash_from_email_redirect(client, member_user):
    login(client, member_user)
    r = client.get("/?ok=1&msg=Email+sent+to+someone%40test.local.")
    assert r.status_code == 200
    assert "Email sent to someone@test.local." in r.text
    assert 'class="alert success"' in r.text


def test_dashboard_shows_email_icon_per_row(client, member_user):
    login(client, member_user)
    client.post("/tasks", data={"title": "Icon check"})
    r = client.get("/")
    assert 'data-kind="tasks"' in r.text
    assert "openEmailModal(this)" in r.text
