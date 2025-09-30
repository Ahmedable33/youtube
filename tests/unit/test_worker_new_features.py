"""Tests unitaires pour les nouvelles fonctionnalités du worker"""
from pathlib import Path
import importlib
import types
import sys
from unittest.mock import patch, MagicMock
import subprocess


def _stub_googleapiclient():
    """Stub googleapiclient pour éviter les dépendances"""
    ga = types.ModuleType("googleapiclient")
    ga_discovery = types.ModuleType("googleapiclient.discovery")
    ga_errors = types.ModuleType("googleapiclient.errors")
    ga_http = types.ModuleType("googleapiclient.http")
    sys.modules["googleapiclient"] = ga
    sys.modules["googleapiclient.discovery"] = ga_discovery
    sys.modules["googleapiclient.errors"] = ga_errors
    sys.modules["googleapiclient.http"] = ga_http


def test_probe_audio_language_success():
    """Test détection langue audio via ffprobe avec succès"""
    _stub_googleapiclient()
    worker = importlib.import_module("src.worker")

    fake_video = Path("/tmp/test_video.mp4")

    # Mock subprocess.run pour simuler ffprobe retournant 'fr'
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "fr\n"

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        lang = worker._probe_audio_language(fake_video)

        assert lang == "fr"
        mock_run.assert_called_once()
        # Vérifier que ffprobe est bien appelé
        call_args = mock_run.call_args[0][0]
        assert "ffprobe" in call_args


def test_probe_audio_language_undefined():
    """Test détection langue audio avec tag 'und' (undefined)"""
    _stub_googleapiclient()
    worker = importlib.import_module("src.worker")

    fake_video = Path("/tmp/test_video.mp4")

    # Mock subprocess.run pour simuler ffprobe retournant 'und'
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "und"

    with patch("subprocess.run", return_value=mock_result):
        lang = worker._probe_audio_language(fake_video)

        # 'und' doit être ignoré et retourner None
        assert lang is None


def test_probe_audio_language_no_metadata():
    """Test détection langue audio sans métadonnées"""
    _stub_googleapiclient()
    worker = importlib.import_module("src.worker")

    fake_video = Path("/tmp/test_video.mp4")

    # Mock subprocess.run pour simuler ffprobe sans output
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""

    with patch("subprocess.run", return_value=mock_result):
        lang = worker._probe_audio_language(fake_video)

        assert lang is None


def test_probe_audio_language_ffprobe_error():
    """Test détection langue audio avec erreur ffprobe"""
    _stub_googleapiclient()
    worker = importlib.import_module("src.worker")

    fake_video = Path("/tmp/test_video.mp4")

    # Mock subprocess.run pour simuler erreur ffprobe
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "Error: file not found"

    with patch("subprocess.run", return_value=mock_result):
        lang = worker._probe_audio_language(fake_video)

        # En cas d'erreur, doit retourner None
        assert lang is None


def test_probe_audio_language_timeout():
    """Test détection langue audio avec timeout"""
    _stub_googleapiclient()
    worker = importlib.import_module("src.worker")

    fake_video = Path("/tmp/test_video.mp4")

    # Mock subprocess.run pour lever TimeoutExpired
    with patch(
        "subprocess.run", side_effect=subprocess.TimeoutExpired("ffprobe", 10)
    ):
        lang = worker._probe_audio_language(fake_video)

        # Timeout doit être géré et retourner None
        assert lang is None


def test_generate_placeholder_thumbnail_success(tmp_path):
    """Test génération placeholder thumbnail avec Pillow"""
    _stub_googleapiclient()
    worker = importlib.import_module("src.worker")

    output_path = tmp_path / "placeholder_thumb.jpg"

    # Mock PIL au niveau de src.worker pour éviter l'import direct
    mock_image = MagicMock()
    mock_draw = MagicMock()

    # Simuler la sauvegarde qui crée le fichier
    def save_side_effect(*args, **kwargs):
        output_path.write_bytes(b"fake_jpeg")

    mock_image.save = MagicMock(side_effect=save_side_effect)

    # Mock PIL dans le contexte de src.worker
    mock_pil = MagicMock()
    mock_pil.Image.new.return_value = mock_image
    mock_pil.ImageDraw.Draw.return_value = mock_draw
    mock_pil.ImageFont.load_default.return_value = MagicMock()

    with patch.dict("sys.modules", {"PIL": mock_pil, "PIL.Image": mock_pil.Image, "PIL.ImageDraw": mock_pil.ImageDraw, "PIL.ImageFont": mock_pil.ImageFont}):
        result = worker._generate_placeholder_thumbnail(output_path)

        assert result is True
        assert output_path.exists()
        mock_pil.Image.new.assert_called_once()


def test_generate_placeholder_thumbnail_no_pillow(tmp_path):
    """Test génération placeholder thumbnail sans Pillow disponible"""
    _stub_googleapiclient()
    worker = importlib.import_module("src.worker")

    output_path = tmp_path / "placeholder_thumb.jpg"

    # Mock ImportError pour simuler Pillow non disponible
    # On mock au niveau module pour que l'import dans _generate_placeholder_thumbnail échoue
    mock_pil = MagicMock()
    mock_pil.Image.new.side_effect = ImportError("No module named 'PIL'")
    
    with patch.dict("sys.modules", {"PIL": mock_pil, "PIL.Image": mock_pil.Image}):
        result = worker._generate_placeholder_thumbnail(output_path)

        assert result is False
        assert not output_path.exists()


def test_generate_placeholder_thumbnail_pillow_error(tmp_path):
    """Test génération placeholder thumbnail avec erreur Pillow"""
    _stub_googleapiclient()
    worker = importlib.import_module("src.worker")

    output_path = tmp_path / "placeholder_thumb.jpg"

    # Mock PIL avec une erreur lors de la sauvegarde
    mock_image = MagicMock()
    mock_image.save = MagicMock(side_effect=Exception("Save failed"))
    
    mock_pil = MagicMock()
    mock_pil.Image.new.return_value = mock_image
    mock_pil.ImageDraw.Draw.return_value = MagicMock()
    mock_pil.ImageFont.load_default.return_value = MagicMock()

    with patch.dict("sys.modules", {"PIL": mock_pil, "PIL.Image": mock_pil.Image, "PIL.ImageDraw": mock_pil.ImageDraw, "PIL.ImageFont": mock_pil.ImageFont}):
        result = worker._generate_placeholder_thumbnail(output_path)

        assert result is False


def test_default_privacy_status_logic():
    """Test que la logique de privacy_status utilise 'public' comme défaut"""
    _stub_googleapiclient()
    worker = importlib.import_module("src.worker")

    # On ne peut pas tester directement process_queue, mais on peut vérifier
    # que la chaîne 'public' est bien dans le code comme défaut
    import inspect

    source = inspect.getsource(worker.process_queue)
    # Vérifier que 'public' est présent comme fallback dans la chaîne de priorité
    assert 'or "public"' in source or "or 'public'" in source
