"""Lightweight action items, workload counts, and turnover transfers."""
from datetime import date, datetime, timedelta

import pytest

from app import config
from app.models import ActionItem, AuditLog, Message, Task

from .conftest import login


def create_item(client, db_session, **fields):
    response = client.post("/action-items", data={"title": "Department work", **fields}, follow_redirects=False)
    assert response.status_code == 303
    return db_session.query(ActionItem).order_by(ActionItem.id.desc()).first()


def test_title_only_creation_defaults_to_self_without_approval(client, db_session, member_user):
    login(client, member_user)
    item = create_item(client, db_session)
    assert item.title == "Department work"
    assert item.description == ""
    assert item.assignee_id == item.requested_by_id == member_user.id
    assert item.priority == "normal"
    assert item.status == "not_started"
    assert item.due_date is None
    response = client.get("/work?person=me")
    assert item.title in response.text
    assert response.context["item_rows"][0]["item"].requested_by_id == member_user.id
    assert "+ New Task" not in response.text
    assert db_session.query(Task).count() == 0


def test_manager_assignment_notifies_owner_and_records_creator(client, db_session, manager_user, member_user):
    login(client, manager_user)
    item = create_item(
        client, db_session, assignee_id=member_user.id, priority="high",
        due_date="2026-12-01", description="Customer follow-up",
    )
    assert item.requested_by_id == manager_user.id
    assert item.assignee_id == member_user.id
    assert item.priority == "high"
    assert item.due_date == date(2026, 12, 1)
    message = db_session.query(Message).one()
    assert message.recipient_id == member_user.id
    assert message.related_id == item.id
    client.post("/logout")
    login(client, member_user)
    assert item.title in client.get("/work?person=me").text
    assert "nav-badge" in client.get("/").text


@pytest.mark.parametrize("fields", [
    {"title": "   "}, {"title": "x" * 301},
    {"priority": "urgent"}, {"due_date": "bad-date"},
])
def test_creation_validates_required_information(client, db_session, member_user, fields):
    login(client, member_user)
    response = client.post("/action-items", data={"title": "Valid title", **fields})
    assert response.status_code == 400
    assert db_session.query(ActionItem).count() == 0


def test_status_flow_requires_blocker_and_preserves_completion_date(client, db_session, member_user):
    login(client, member_user)
    item = create_item(client, db_session)
    url = f"/action-items/{item.id}/status"
    assert client.post(url, data={"status_value": "in_progress"}).status_code == 200
    db_session.refresh(item)
    assert item.status == "in_progress"
    response = client.post(url, data={"status_value": "blocked", "blocked_reason": " "})
    assert response.status_code == 400
    db_session.refresh(item)
    assert item.status == "in_progress"
    client.post(url, data={"status_value": "blocked", "blocked_reason": "Waiting for access"})
    db_session.refresh(item)
    assert item.status == "blocked"
    assert item.blocked_reason == "Waiting for access"
    assert "Waiting for access" in client.get("/work").text
    client.post(url, data={"status_value": "completed"})
    db_session.refresh(item)
    completed = item.completed_at
    assert completed is not None
    assert item.blocked_reason == ""
    client.post(url, data={"status_value": "completed"})
    db_session.refresh(item)
    assert item.completed_at == completed
    client.post(url, data={"status_value": "in_progress"})
    db_session.refresh(item)
    assert item.completed_at is None
    assert any("Waiting for access" in note.body for note in item.notes)
    assert client.post(url, data={"status_value": "invented"}).status_code == 400
    assert client.get("/work?status_filter=completed").context["item_rows"] == []


def test_my_work_is_owned_work_not_everything_i_requested(client, db_session, member_user, other_member):
    login(client, member_user)
    mine = create_item(client, db_session, title="My commitment")
    delegated = create_item(client, db_session, title="Delegated commitment", assignee_id=other_member.id)
    rows = client.get("/work?person=me").context["item_rows"]
    assert [r["item"].id for r in rows] == [mine.id]
    rows = client.get(f"/work?person={other_member.id}").context["item_rows"]
    assert [r["item"].id for r in rows] == [delegated.id]


def test_workload_counts_all_active_statuses_and_ignores_completed(client, db_session, member_user, other_member, monkeypatch):
    login(client, member_user)
    for state in ("not_started", "in_progress", "blocked", "completed"):
        db_session.add(ActionItem(
            requested_by_id=other_member.id, assignee_id=member_user.id,
            title=f"Work {state}", description="", status=state, priority="high",
            due_date=date.today() - timedelta(days=1),
            blocked_reason="Dependency" if state == "blocked" else "",
        ))
    db_session.commit()
    response = client.get("/work")
    row = next(r for r in response.context["workload_rows"] if r["owner"].id == member_user.id)
    assert {key: row[key] for key in ("total", "not_started", "in_progress", "blocked", "high", "overdue")} == {
        "total": 3, "not_started": 1, "in_progress": 1, "blocked": 1, "high": 3, "overdue": 3,
    }
    assert response.context["open_item_count"] == 3
    assert len(client.get("/work?status_filter=blocked").context["item_rows"]) == 1
    assert client.get("/").context["my_item_count"] == 3
    assert client.get("/metrics").context["open_item_count"] == 3
    monkeypatch.setattr(config, "API_KEY", "test-workload")
    result = client.get("/api/v1/summary", headers={"X-API-Key": "test-workload"}).json()
    assert result["total_open"] == result["open_action_items"] == 3
    assert result["done_action_items"] == 1
    assert result["open_tasks"] == result["done_tasks"] == 0
    assert result["blocked_action_items"] == 1
    assert result["overdue_action_items"] == 3
    assert result["workload"][0]["blocked"] == 1
    assert result["workload"][0]["overdue"] == 3


def test_individual_reassignment_preserves_history_dates_and_creator(client, db_session, member_user, other_member, manager_user):
    login(client, member_user)
    item = create_item(client, db_session, priority="high", due_date="2026-12-01")
    client.post(f"/action-items/{item.id}/notes", data={"body": "Important progress"})
    created_at = item.created_at
    client.post("/logout")
    login(client, manager_user)
    response = client.post(f"/action-items/{item.id}", data={
        "title": item.title, "description": item.description, "priority": item.priority,
        "due_date": str(item.due_date), "assignee_id": other_member.id,
    }, follow_redirects=False)
    assert response.status_code == 303
    db_session.refresh(item)
    assert item.assignee_id == other_member.id
    assert item.requested_by_id == member_user.id
    assert item.created_at == created_at
    assert item.priority == "high"
    assert item.due_date == date(2026, 12, 1)
    assert any(note.body == "Important progress" for note in item.notes)
    assert any(member_user.email in note.body and other_member.email in note.body for note in item.notes)
    message = db_session.query(Message).filter(Message.recipient_id == other_member.id).one()
    assert message.related_id == item.id


def test_bulk_transfer_includes_disabled_owners_but_leaves_completed_work(client, db_session, manager_user, member_user, other_member):
    member_user.is_active = False
    created_at = datetime.utcnow() - timedelta(days=10)
    for state in ("not_started", "in_progress", "blocked", "completed"):
        db_session.add(ActionItem(
            requested_by_id=member_user.id, assignee_id=member_user.id,
            title=f"Turnover {state}", description="", status=state,
            priority="high", due_date=date(2026, 12, 1), created_at=created_at,
            completed_at=created_at if state == "completed" else None,
            blocked_reason="Waiting" if state == "blocked" else "",
        ))
    db_session.commit()
    login(client, manager_user)
    assert member_user.email in client.get("/work").text
    response = client.post("/action-items/transfer", data={
        "source_id": member_user.id, "assignee_id": other_member.id,
    })
    assert "Transferred 3 open action items" in response.text
    db_session.expire_all()
    for item in db_session.query(ActionItem):
        assert item.assignee_id == (member_user.id if item.status == "completed" else other_member.id)
        assert item.created_at == created_at
        assert item.requested_by_id == member_user.id
        assert item.due_date == date(2026, 12, 1)
        assert item.priority == "high"
        if item.status != "completed":
            assert item.needs_review
            assert len(item.notes) == 1
    assert db_session.query(Message).filter(Message.recipient_id == other_member.id).count() == 3
    assert db_session.query(AuditLog).filter(AuditLog.action == "action_item.reassign").count() == 3


def test_bulk_transfer_is_staff_only_and_validates_destination(client, db_session, member_user, other_member, manager_user):
    login(client, member_user)
    item = create_item(client, db_session)
    response = client.post("/action-items/transfer", data={"source_id": member_user.id, "assignee_id": other_member.id})
    assert response.status_code == 403
    client.post("/logout")
    login(client, manager_user)
    for source_id, assignee_id in ((member_user.id, member_user.id), (99999, other_member.id), (member_user.id, "invalid")):
        assert client.post("/action-items/transfer", data={"source_id": source_id, "assignee_id": assignee_id}).status_code == 400
    other_member.is_active = False
    db_session.commit()
    assert client.post("/action-items/transfer", data={"source_id": member_user.id, "assignee_id": other_member.id}).status_code == 400
    db_session.refresh(item)
    assert item.assignee_id == member_user.id


def test_unrelated_member_cannot_change_owner_or_status(client, db_session, member_user, other_member):
    login(client, member_user)
    item = create_item(client, db_session)
    client.post("/logout")
    login(client, other_member)
    client.post(f"/action-items/{item.id}", data={"title": "Changed", "assignee_id": other_member.id})
    client.post(f"/action-items/{item.id}/status", data={"status_value": "completed"})
    db_session.refresh(item)
    assert item.title == "Department work"
    assert item.assignee_id == member_user.id
    assert item.status == "not_started"


def test_reassignment_only_updates_preserve_optional_metadata(client, db_session, member_user, other_member):
    login(client, member_user)
    item = create_item(client, db_session, priority="high", description="Keep this detail", due_date="2026-12-01")
    response = client.post(f"/action-items/{item.id}", data={"assignee_id": other_member.id})
    assert response.status_code == 200
    db_session.refresh(item)
    assert item.title == "Department work"
    assert item.description == "Keep this detail"
    assert item.priority == "high"
    assert item.due_date == date(2026, 12, 1)
    assert item.assignee_id == other_member.id


def test_former_owner_cannot_be_deleted_if_they_contributed_updates(client, db_session, manager_user, member_user, other_member):
    login(client, manager_user)
    item = create_item(client, db_session, assignee_id=member_user.id)
    client.post("/logout")
    login(client, member_user)
    client.post(f"/action-items/{item.id}/notes", data={"body": "Work completed before handoff"})
    client.post("/logout")
    login(client, manager_user)
    client.post(f"/action-items/{item.id}", data={"assignee_id": other_member.id})
    response = client.post(f"/admin/users/{member_user.id}/delete")
    assert "Disable the account to preserve history" in response.text
    db_session.refresh(member_user)
    assert any(note.author_id == member_user.id for note in item.notes)


def test_legacy_description_only_creation_preserves_long_details(client, db_session, member_user):
    login(client, member_user)
    response = client.post("/action-items", data={"description": "Long description " * 40})
    assert response.status_code == 200
    item = db_session.query(ActionItem).one()
    assert len(item.title) == 300
    assert item.description == ("Long description " * 40).strip()
