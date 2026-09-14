from pathlib import Path

from scripts.dsa_prepare_private_text_export import prepare


def test_text_export_excludes_sqlite_and_hashes_text(tmp_path):
    src = tmp_path / "source"
    out = tmp_path / "out"
    (src / "original-model").mkdir(parents=True)
    (src / "preflight.json").write_text('{"passed":true}\n')
    (src / "original-model" / "original-result.json").write_text('{"score":1}\n')
    (src / "original-model" / "original-data.db").write_bytes(b"SQLite format 3\x00binary")
    result = prepare(src, out)
    assert (out / "preflight.json").is_file()
    assert (out / "original-model" / "original-result.json").is_file()
    assert not (out / "original-model" / "original-data.db").exists()
    assert result["binary_files_copied"] == 0
    assert result["excluded_binary_paths"] == ["original-model/original-data.db"]
    assert (out / "private-export-manifest.json").is_file()


def test_binary_content_in_approved_text_path_is_refused(tmp_path):
    src = tmp_path / "source"
    out = tmp_path / "out"
    src.mkdir()
    (src / "preflight.json").write_bytes(b"abc\x00def")
    try:
        prepare(src, out)
    except ValueError as exc:
        assert "binary-looking evidence refused" in str(exc)
    else:
        raise AssertionError("binary content should be refused")
