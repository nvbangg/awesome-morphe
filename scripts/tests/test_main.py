from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

import main as sync


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    tasks = MagicMock()
    client = MagicMock()
    git_status = MagicMock(return_value=b"")
    summary = MagicMock()
    tasks.discover.return_value = 0
    tasks.update.return_value = 0
    monkeypatch.setattr(sync.discover, "run", tasks.discover)
    monkeypatch.setattr(sync.fetch, "fetch_all_repos", tasks.fetch)
    monkeypatch.setattr(sync.update, "run", tasks.update)
    monkeypatch.setattr(sync.telegram, "send_notification", tasks.telegram)
    monkeypatch.setattr(sync.http, "HTTP_CLIENT", client)
    monkeypatch.setattr(sync.subprocess, "check_output", git_status)
    tasks.audit.return_value = "Audit"
    tasks.find_projects.return_value = "Projects"
    monkeypatch.setattr(sync.audit_readme, "audit_repos_and_links", tasks.audit)
    monkeypatch.setattr(sync.find_projects, "run", tasks.find_projects)
    monkeypatch.setattr(sync, "append_step_summary", summary)
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "output"))
    return tasks, git_status, client, summary


@pytest.mark.parametrize(
    "arguments,changes,mode",
    (
        ([], b"", None),
        ([], b" M data/repos.json\n", "default"),
        (["--daily"], b"", "daily"),
    ),
)
def test_sync_preserves_update_gate_and_stage_order(arguments, changes, mode, pipeline, tmp_path: Path) -> None:
    tasks, git_status, _client, summary = pipeline
    git_status.return_value = changes
    assert sync.main(arguments) == 0
    daily = "--daily" in arguments
    expected = [call.audit(), call.find_projects()] if daily else []
    expected.extend([call.discover(), call.fetch(daily)])
    if mode:
        expected.append(call.update(daily))
        assert (tmp_path / "output").read_text(encoding="utf-8") == "updated=true\n"
    else:
        assert not (tmp_path / "output").exists()
    assert tasks.mock_calls == expected
    if daily:
        summary.assert_called_once_with("## 📋 Review:\n\nAudit\n\nProjects")
    else:
        summary.assert_not_called()
    if arguments:
        git_status.assert_not_called()
    else:
        git_status.assert_called_once_with(
            ["git", "status", "--porcelain", "--", "data/", "web/public/"], cwd=sync.ROOT_DIR
        )


@pytest.mark.parametrize("stage", ("discover", "fetch", "update"))
def test_sync_failure_stops_later_tasks_and_does_not_mark_update(stage, pipeline, tmp_path: Path) -> None:
    tasks, _git_status, client, _summary = pipeline
    if stage == "fetch":
        tasks.fetch.side_effect = RuntimeError("Fetch failed")
        with pytest.raises(RuntimeError, match="Fetch failed"):
            sync.main(["--daily"])
    else:
        getattr(tasks, stage).return_value = 1
        assert sync.main(["--daily"]) == 1
    stages = ["discover", "fetch", "update"]
    assert [task[0] for task in tasks.mock_calls] == ["audit", "find_projects"] + stages[: stages.index(stage) + 1]
    assert not (tmp_path / "output").exists()
    client.__exit__.assert_called_once()


@pytest.mark.parametrize(
    "arguments,expected",
    (
        (["audit-readme"], call.audit()),
        (["find-projects"], call.find_projects()),
        (["discover"], call.discover()),
        (["fetch", "--daily"], call.fetch(True)),
        (["update", "--daily"], call.update(True)),
        (["telegram", "Custom title", "notification.md"], call.telegram("Custom title", Path("notification.md"))),
    ),
)
def test_selected_task_runs_alone(arguments, expected, pipeline) -> None:
    tasks, git_status, _client, _summary = pipeline
    assert sync.main(arguments) == 0
    assert tasks.mock_calls == [expected]
    git_status.assert_not_called()
