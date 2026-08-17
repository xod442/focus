"""In-app messaging: sending a short ping tied to a task/action item, the
per-user message queue on the dashboard, and clearing a message."""
from .conftest import login


def test_message_task_lands_in_owner_queue(client, db_session, member_user, other_member):
    login(client, member_user)
    client.post("/tasks", data={"title": "Owned by member"})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Owned by member").one()
    client.post("/logout")

    login(client, other_member)
    r = client.post(f"/tasks/{task.id}/message", data={"body": "Any update on this?"},
                     follow_redirects=False)
    assert r.status_code == 303
    assert "ok=1" in r.headers["location"]

    from app.models import Message
    messages = db_session.query(Message).all()
    assert len(messages) == 1
    m = messages[0]
    assert m.sender_id == other_member.id
    assert m.recipient_id == member_user.id  # the task's owner, not the sender
    assert m.body == "Any update on this?"
    assert m.related_kind == "task"
    assert m.related_id == task.id


def test_message_action_item_lands_in_assignee_queue(client, db_session, member_user,
                                                       other_member):
    login(client, member_user)
    client.post("/action-items", data={
        "description": "Ping the vendor", "assignee_id": str(other_member.id),
    })
    from app.models import ActionItem
    item = db_session.query(ActionItem).filter(
        ActionItem.description == "Ping the vendor"
    ).one()

    r = client.post(f"/action-items/{item.id}/message", data={"body": "Still waiting on you"},
                     follow_redirects=False)
    assert r.status_code == 303

    from app.models import Message
    m = db_session.query(Message).one()
    assert m.recipient_id == other_member.id  # the assignee, not the requester
    assert m.sender_id == member_user.id


def test_message_body_truncated_to_max_length(client, db_session, member_user):
    login(client, member_user)
    client.post("/tasks", data={"title": "Truncate me"})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Truncate me").one()

    long_body = "x" * 500
    client.post(f"/tasks/{task.id}/message", data={"body": long_body})

    from app.models import MESSAGE_BODY_MAX_LEN, Message
    m = db_session.query(Message).one()
    assert len(m.body) == MESSAGE_BODY_MAX_LEN


def test_message_rejects_empty_body(client, db_session, member_user):
    login(client, member_user)
    client.post("/tasks", data={"title": "No empty messages"})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "No empty messages").one()

    r = client.post(f"/tasks/{task.id}/message", data={"body": "   "}, follow_redirects=False)
    assert "ok=0" in r.headers["location"]

    from app.models import Message
    assert db_session.query(Message).count() == 0


def test_dashboard_shows_only_my_own_messages(client, db_session, member_user, other_member):
    login(client, member_user)
    client.post("/tasks", data={"title": "For member"})
    client.post("/logout")

    login(client, other_member)
    client.post("/tasks", data={"title": "For other"})
    from app.models import Task
    task_for_member = db_session.query(Task).filter(Task.title == "For member").one()
    task_for_other = db_session.query(Task).filter(Task.title == "For other").one()

    # other_member messages member_user (about member's task)
    client.post(f"/tasks/{task_for_member.id}/message", data={"body": "Message to member"})
    client.post("/logout")

    login(client, member_user)
    # member_user messages other_member (about other's task)
    client.post(f"/tasks/{task_for_other.id}/message", data={"body": "Message to other"})

    r = client.get("/")
    assert "Message to member" in r.text   # addressed to member_user (logged in)
    assert "Message to other" not in r.text  # addressed to other_member, not shown here


def test_clear_message_removes_it_and_requires_recipient(client, db_session, member_user,
                                                           other_member):
    login(client, member_user)
    client.post("/tasks", data={"title": "Clear test"})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Clear test").one()
    client.post("/logout")

    login(client, other_member)
    client.post(f"/tasks/{task.id}/message", data={"body": "hello"})
    client.post("/logout")

    from app.models import Message
    m = db_session.query(Message).one()

    # A non-recipient (other_member, the sender) cannot clear member_user's message.
    login(client, other_member)
    client.post(f"/messages/{m.id}/clear")
    assert db_session.get(Message, m.id) is not None

    client.post("/logout")
    login(client, member_user)
    r = client.get("/")
    assert "hello" in r.text

    client.post(f"/messages/{m.id}/clear")
    assert db_session.get(Message, m.id) is None

    r = client.get("/")
    assert "hello" not in r.text
    assert "No messages right now." in r.text


def test_message_related_link_shown_on_dashboard(client, db_session, member_user, other_member):
    login(client, member_user)
    client.post("/tasks", data={"title": "Linked task"})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Linked task").one()
    client.post("/logout")

    login(client, other_member)
    client.post(f"/tasks/{task.id}/message", data={"body": "context please"})
    client.post("/logout")

    login(client, member_user)
    r = client.get("/")
    assert f"/tasks/{task.id}/edit" in r.text
    assert f"Task #{task.id}: Linked task" in r.text


def test_reply_sends_message_back_to_original_sender(client, db_session, member_user,
                                                       other_member):
    login(client, member_user)
    client.post("/tasks", data={"title": "Reply target"})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Reply target").one()
    client.post("/logout")

    # other_member pings member_user (the task owner).
    login(client, other_member)
    client.post(f"/tasks/{task.id}/message", data={"body": "Any update?"})
    client.post("/logout")

    from app.models import Message
    original = db_session.query(Message).filter(Message.body == "Any update?").one()

    # member_user (the recipient) replies.
    login(client, member_user)
    r = client.post(f"/messages/{original.id}/reply", data={"body": "Yes, almost done."},
                     follow_redirects=False)
    assert r.status_code == 303
    assert "ok=1" in r.headers["location"]

    reply = db_session.query(Message).filter(Message.body == "Yes, almost done.").one()
    assert reply.sender_id == member_user.id
    assert reply.recipient_id == other_member.id  # goes back to the original sender
    assert reply.related_kind == original.related_kind
    assert reply.related_id == original.related_id
    assert reply.related_label == original.related_label

    # The original message is untouched — replying doesn't consume/clear it.
    assert db_session.get(Message, original.id) is not None


def test_conversation_can_go_back_and_forth_until_cleared(client, db_session, member_user,
                                                            other_member):
    login(client, member_user)
    client.post("/tasks", data={"title": "Ping pong"})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Ping pong").one()
    client.post("/logout")

    login(client, other_member)
    client.post(f"/tasks/{task.id}/message", data={"body": "msg1"})
    client.post("/logout")

    from app.models import Message

    login(client, member_user)
    m1 = db_session.query(Message).filter(Message.body == "msg1").one()
    client.post(f"/messages/{m1.id}/reply", data={"body": "msg2"})
    client.post("/logout")

    login(client, other_member)
    m2 = db_session.query(Message).filter(Message.body == "msg2").one()
    client.post(f"/messages/{m2.id}/reply", data={"body": "msg3"})
    client.post("/logout")

    # All three messages exist; each landed in the right person's queue.
    assert db_session.query(Message).count() == 3
    m3 = db_session.query(Message).filter(Message.body == "msg3").one()
    assert m3.recipient_id == member_user.id

    # The task relationship (kind/id/label) is carried unchanged across every
    # hop of the conversation, not just the first reply.
    for m in (m1, m2, m3):
        assert m.related_kind == "task"
        assert m.related_id == task.id
        assert m.related_label == f"Task #{task.id}: Ping pong"

    # Only when a party clears their own copy does it disappear.
    login(client, member_user)
    client.post(f"/messages/{m1.id}/clear")
    assert db_session.get(Message, m1.id) is None
    assert db_session.query(Message).count() == 2


def test_only_recipient_can_reply(client, db_session, member_user, other_member):
    login(client, member_user)
    client.post("/tasks", data={"title": "Reply auth check"})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Reply auth check").one()
    client.post("/logout")

    login(client, other_member)
    client.post(f"/tasks/{task.id}/message", data={"body": "please reply"})

    from app.models import Message
    original = db_session.query(Message).filter(Message.body == "please reply").one()

    # other_member is the sender, not the recipient — cannot reply to their own message.
    client.post(f"/messages/{original.id}/reply", data={"body": "sneaky"})
    assert db_session.query(Message).filter(Message.body == "sneaky").count() == 0


def test_reply_rejects_empty_body(client, db_session, member_user, other_member):
    login(client, member_user)
    client.post("/tasks", data={"title": "Empty reply check"})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Empty reply check").one()
    client.post("/logout")

    login(client, other_member)
    client.post(f"/tasks/{task.id}/message", data={"body": "hello"})
    client.post("/logout")

    from app.models import Message
    original = db_session.query(Message).filter(Message.body == "hello").one()

    login(client, member_user)
    r = client.post(f"/messages/{original.id}/reply", data={"body": "   "},
                     follow_redirects=False)
    assert "ok=0" in r.headers["location"]
    assert db_session.query(Message).count() == 1  # only the original


def test_dashboard_shows_reply_button_and_clear_confirmation(client, db_session, member_user,
                                                               other_member):
    login(client, member_user)
    client.post("/tasks", data={"title": "UI check"})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "UI check").one()
    client.post("/logout")

    login(client, other_member)
    client.post(f"/tasks/{task.id}/message", data={"body": "hi there"})
    client.post("/logout")

    login(client, member_user)
    r = client.get("/")
    assert "openReplyModal(this)" in r.text
    assert "onsubmit=\"return confirm(" in r.text


def test_action_item_reply_chain_preserves_related_context(client, db_session, member_user,
                                                             other_member):
    login(client, member_user)
    client.post("/action-items", data={
        "description": "Ping the vendor", "assignee_id": str(other_member.id),
    })
    from app.models import ActionItem
    item = db_session.query(ActionItem).filter(
        ActionItem.description == "Ping the vendor"
    ).one()

    client.post(f"/action-items/{item.id}/message", data={"body": "any update?"})
    client.post("/logout")

    from app.models import Message
    original = db_session.query(Message).filter(Message.body == "any update?").one()
    expected_label = f"Action Item #{item.id}: Ping the vendor"
    assert original.related_kind == "action_item"
    assert original.related_id == item.id
    assert original.related_label == expected_label

    login(client, other_member)
    client.post(f"/messages/{original.id}/reply", data={"body": "working on it"})
    client.post("/logout")

    reply = db_session.query(Message).filter(Message.body == "working on it").one()
    assert reply.related_kind == "action_item"
    assert reply.related_id == item.id
    assert reply.related_label == expected_label

    login(client, member_user)
    r = client.post(f"/messages/{reply.id}/reply", data={"body": "thanks!"},
                     follow_redirects=False)
    assert r.status_code == 303

    reply2 = db_session.query(Message).filter(Message.body == "thanks!").one()
    assert reply2.related_kind == "action_item"
    assert reply2.related_id == item.id
    assert reply2.related_label == expected_label


def test_message_keeps_relationship_after_source_task_is_deleted(client, db_session,
                                                                   member_user, other_member):
    """The relationship is a denormalized snapshot, so a message about a task
    stays correctly labeled/linked even after that task is later deleted —
    it doesn't silently lose its association or point at the wrong record."""
    login(client, member_user)
    client.post("/tasks", data={"title": "Will be deleted"})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Will be deleted").one()
    task_id = task.id
    client.post("/logout")

    login(client, other_member)
    client.post(f"/tasks/{task_id}/message", data={"body": "question about this"})
    client.post("/logout")

    from app.models import Message
    message = db_session.query(Message).filter(Message.body == "question about this").one()
    assert message.related_kind == "task"
    assert message.related_id == task_id
    assert message.related_label == f"Task #{task_id}: Will be deleted"

    login(client, member_user)
    client.post(f"/tasks/{task_id}/delete")
    assert db_session.get(Task, task_id) is None  # task is really gone

    # The message keeps its original relationship info regardless.
    db_session.refresh(message)
    assert message.related_kind == "task"
    assert message.related_id == task_id
    assert message.related_label == f"Task #{task_id}: Will be deleted"

    # It still renders correctly (label + link) on the dashboard.
    r = client.get("/")
    assert f"Task #{task_id}: Will be deleted" in r.text
    assert f"/tasks/{task_id}/edit" in r.text

