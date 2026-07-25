import pytest

from src.main import parse_args


def test_hours_and_explicit_window_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--hours",
                "30",
                "--since",
                "2026-07-23T00:00:00+08:00",
                "--until",
                "2026-07-24T00:00:00+08:00",
            ]
        )


@pytest.mark.parametrize(
    "argv",
    [
        ["--since", "2026-07-23T00:00:00+08:00"],
        ["--until", "2026-07-24T00:00:00+08:00"],
    ],
)
def test_explicit_window_requires_both_ends(argv):
    with pytest.raises(SystemExit):
        parse_args(argv)


def test_resume_defaults_to_no_redelivery():
    args = parse_args(["--resume", "latest"])

    assert args.resume == "latest"
    assert args.redeliver is False


@pytest.mark.parametrize(
    "extra",
    [
        ["--hours", "30"],
        [
            "--since",
            "2026-07-23T00:00:00+08:00",
            "--until",
            "2026-07-24T00:00:00+08:00",
        ],
        ["--resume", "latest"],
    ],
)
def test_daemon_rejects_manual_window_and_resume(extra):
    with pytest.raises(SystemExit):
        parse_args(["--daemon", *extra])


def test_redelivery_requires_resume():
    with pytest.raises(SystemExit):
        parse_args(["--redeliver"])


def test_scheduled_flag_is_accepted_with_manual_run():
    args = parse_args(["--scheduled", "--no-deliver", "--hours", "6"])
    assert args.scheduled is True
    assert args.no_deliver is True
    assert args.hours == 6


def test_scheduled_is_rejected_with_daemon():
    with pytest.raises(SystemExit):
        parse_args(["--scheduled", "--daemon"])


def test_scheduled_is_rejected_with_healthcheck():
    with pytest.raises(SystemExit):
        parse_args(["--scheduled", "--healthcheck"])

