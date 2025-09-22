from pathlib import Path
import main as cli


def test_cli_ingest_no_network(monkeypatch, tmp_path, capsys):
    out_dir = tmp_path / "dl"
    out_dir.mkdir()

    def fake_download_source(url: str, output_dir: str, filename: str | None, prefer_ext: str):
        # Simulate a successful download by creating an empty file and returning its path
        name = (filename or "video") + "." + prefer_ext
        p = Path(output_dir) / name
        p.write_bytes(b"")
        return p

    monkeypatch.setattr(cli, "download_source", fake_download_source)

    rc = cli.main([
        "ingest",
        "https://example.com/video",
        "--output-dir", str(out_dir),
        "--filename", "output",
        "--ext", "mp4",
        "--log-level", "INFO",
    ])
    assert rc == 0
    printed = capsys.readouterr().out.strip()
    assert printed.endswith("/output.mp4"), printed
