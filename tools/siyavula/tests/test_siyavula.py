"""Check downloads and book contents without downloading textbooks in CI."""

import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import siyavula


def epub_bytes(*, text="Living things need water.", missing_spine=False):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
        archive.writestr("OPS/book.opf", '''<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
          <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
            <dc:title>Natural Sciences</dc:title><dc:language>en</dc:language>
          </metadata>
          <manifest>
            <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
            <item id="image" href="diagram.png" media-type="image/png"/>
          </manifest>
          <spine><itemref idref="chapter"/></spine>
        </package>''')
        if not missing_spine:
            archive.writestr("OPS/chapter.xhtml", f'<html><body><p>{text}</p><a href="https://creativecommons.org/licenses/by/4.0/">License</a></body></html>')
        archive.writestr("OPS/diagram.png", b"image fixture")
    return output.getvalue()


class BooksTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory / "book.epub"
        self.content = epub_bytes()
        self.path.write_bytes(self.content)
        self.book = {"id": "science-4", "filename": "book.epub", "url": "https://www.siyavula.com/book.epub", "sha256": hashlib.sha256(self.content).hexdigest()}

    def test_reports_readable_text_images_and_original_locations(self):
        details = siyavula.inspect_epub(self.path)
        self.assertEqual(details["embedded_language"], "en")
        self.assertGreater(details["text_characters"], 20)
        self.assertEqual(details["spine"][0]["href"], "OPS/chapter.xhtml")
        self.assertEqual(details["image_resources"], 1)
        self.assertEqual(details["missing_manifest_resources"], [])
        self.assertIn("https://creativecommons.org/licenses/by/4.0/", details["embedded_license_links"])

    def test_rejects_changed_book_bytes(self):
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            siyavula.inspect_epub(self.path, "0" * 64)

    def test_rejects_a_download_error_page(self):
        self.path.write_text("<html>Access denied</html>")
        with self.assertRaises(zipfile.BadZipFile):
            siyavula.inspect_epub(self.path)

    def test_identifies_publisher_lfs_pointer_instead_of_book(self):
        self.path.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 123\n")
        with self.assertRaisesRegex(ValueError, "Git LFS pointer"):
            siyavula.inspect_epub(self.path)

    def test_rejects_missing_reading_content(self):
        self.path.write_bytes(epub_bytes(missing_spine=True))
        with self.assertRaises(KeyError):
            siyavula.inspect_epub(self.path)

    def test_repeat_download_keeps_book_and_does_not_fetch_again(self):
        before = self.path.stat().st_mtime_ns
        with patch.object(siyavula.urllib.request, "urlopen", side_effect=AssertionError("network used")):
            result = siyavula.download_book(self.book, self.directory)
        self.assertEqual(result["status"], "cached")
        self.assertEqual(self.path.stat().st_mtime_ns, before)
        self.assertEqual(self.path.read_bytes(), self.content)

    def test_invalid_download_is_not_published(self):
        other = {**self.book, "filename": "other.epub"}
        response = io.BytesIO(b"<html>Access denied</html>")
        response.headers = {}
        response.url = other["url"]
        with patch.object(siyavula.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(ValueError):
                siyavula.download_book(other, self.directory)
        self.assertFalse((self.directory / "other.epub").exists())
        self.assertEqual(list(self.directory.glob("*.part")), [])

    def test_download_keeps_original_bytes_and_source_receipt(self):
        other = {**self.book, "filename": "other.epub"}
        response = io.BytesIO(self.content)
        response.headers = {"Content-Type": "application/epub+zip"}
        response.url = other["url"]
        with patch.object(siyavula.urllib.request, "urlopen", return_value=response):
            result = siyavula.download_book(other, self.directory)
        self.assertEqual((self.directory / "other.epub").read_bytes(), self.content)
        self.assertEqual(result["resolved_url"], other["url"])
        self.assertTrue((self.directory / "other.epub.json").exists())

    def test_only_discovers_unbranded_english_epubs(self):
        links = siyavula.CatalogueLinks()
        links.feed('''<a href="/Gr4_Learner_Eng_CC-BY.epub">ePUB (CC-BY)</a>
          <a href="/Gr4_Learner_Afr_CC-BY.epub">ePUB (CC-BY)</a>
          <a href="/Gr4_Learner_Eng_CC-BY-ND.epub">ePUB (CC-BY-ND)</a>
          <a href="/Gr5_Learner_Eng_CC-BY.epub">ePUB (Closed copyright)</a>''')
        self.assertEqual(links.urls, {"https://www.siyavula.com/Gr4_Learner_Eng_CC-BY.epub"})

    def test_cannot_resolve_resources_outside_book(self):
        with self.assertRaises(ValueError):
            siyavula.member_path("OPS/book.opf", "../../outside.xhtml")


if __name__ == "__main__":
    unittest.main()
