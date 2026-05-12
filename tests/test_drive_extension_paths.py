from __future__ import annotations

from app.drive_extension_paths import extension_destination_segments


def test_pdf() -> None:
    assert extension_destination_segments("a.PDF") == ("PDF", ["PDF"])


def test_docx() -> None:
    assert extension_destination_segments("x.docx") == ("Documente", ["Documente"])


def test_images() -> None:
    assert extension_destination_segments("p.png") == ("Afise", ["Afise"])
    assert extension_destination_segments("p.JPEG") == ("Afise", ["Afise"])
    assert extension_destination_segments("p.jpg") == ("Afise", ["Afise"])


def test_powerpoint() -> None:
    assert extension_destination_segments("s.pptx") == ("PowerPoint", ["Powerpoint"])
    assert extension_destination_segments("s.ppt") == ("PowerPoint", ["Powerpoint"])


def test_other() -> None:
    assert extension_destination_segments("n.txt") == ("Altele", ["Altele"])
    assert extension_destination_segments("noext") == ("Altele", ["Altele"])
