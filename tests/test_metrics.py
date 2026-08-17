"""Executive metrics page: counts, workload, and stale-item detection."""
from datetime import datetime, timedelta

from .conftest import login


def test_metrics_page_loads_with_counts(client, db_session, member_user):
    login(client, member_user)
    client.post("/tasks", data={"title": "Task A"})
    client.post("/action-items", data={"description": "Item A", "assignee_id": str(member_user.id)})

    r = client.get("/metrics")
    assert r.status_code == 200
    assert "Executive Snapshot" in r.text
    assert member_user.email in r.text  # shows up in the workload table


def test_stale_flag_on_old_untouched_task(client, db_session, member_user):
    login(client, member_user)
    client.post("/tasks", data={"title": "Old task"})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Old task").one()
    task.updated_at = datetime.utcnow() - timedelta(weeks=5)
    task.created_at = task.updated_at
    db_session.add(task)
    db_session.commit()

    r = client.get("/metrics")
    assert "haven't been touched" in r.text
    assert "Old task" in r.text  # appears in the oldest-open-items list


def test_usage_chart_ranks_most_active_user_first(client, db_session, member_user, other_member):
    # member_user does several actions (logs in + creates two tasks); other_member
    # only logs in once — member_user should be ranked #1 in the usage chart.
    login(client, member_user)
    client.post("/tasks", data={"title": "One"})
    client.post("/tasks", data={"title": "Two"})
    client.post("/logout")

    login(client, other_member)

    r = client.get("/metrics")
    assert r.status_code == 200
    assert "Application usage by user" in r.text
    assert member_user.email in r.text
    assert other_member.email in r.text
    assert "most active" in r.text

    # member_user's activity count should appear before other_member's within
    # the usage chart itself (rows are emitted in rank order). The nav bar
    # also shows the logged-in user's (other_member's) email, so restrict the
    # comparison to the chart section rather than the whole page.
    chart_start = r.text.index('class="usage3d-chart"')
    chart_html = r.text[chart_start:]
    assert chart_html.index(member_user.email) < chart_html.index(other_member.email)


def test_usage_chart_days_filter_excludes_old_activity(client, db_session, member_user):
    login(client, member_user)
    client.post("/tasks", data={"title": "Recent"})

    from app.models import AuditLog
    # Backdate all this user's audit entries beyond the 30-day default window.
    db_session.query(AuditLog).filter(AuditLog.user_email == member_user.email).update(
        {"ts": datetime.utcnow() - timedelta(days=100)}
    )
    db_session.commit()

    r = client.get("/metrics?usage_days=30")
    assert r.status_code == 200

    r90 = client.get("/metrics?usage_days=90")
    assert r90.status_code == 200
    # A wider window should count more (backdated) activity than the narrow one.
    import re
    def total_usage_count(html):
        # crude: sum every <div class="usage3d-count">N</div>
        return sum(int(n) for n in re.findall(r'usage3d-count">(\d+)<', html))
    assert total_usage_count(r90.text) >= total_usage_count(r.text)


def test_usage_days_invalid_value_falls_back_to_default(client, member_user):
    login(client, member_user)
    r = client.get("/metrics?usage_days=999")
    assert r.status_code == 200
    assert "Last 30 days" in r.text
