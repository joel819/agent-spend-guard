from cli.__main__ import main


def test_demo_shows_all_three_outcomes(capsys, monkeypatch, tmp_path):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    assert main(["demo", "--yes", "--scripted", "--tamper"]) == 0
    out = capsys.readouterr().out
    assert "2 auto-approved" in out and "1 needed a human" in out and "1 hard-rejected" in out
    assert "NEEDS CONFIRMATION" in out and "REJECTED" in out and "cannot be overridden" in out
    assert "Audit chain verified" in out and "Audit chain BROKEN" in out


def test_demo_human_says_no(capsys, monkeypatch, tmp_path):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    main(["demo", "--no", "--scripted"])
    out = capsys.readouterr().out
    assert "DENIED" in out
