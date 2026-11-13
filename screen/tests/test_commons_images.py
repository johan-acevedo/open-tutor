"""Boundary tests for the Commons helper: real response shapes, nothing mocked away.

The payloads below are trimmed captures of the live API for "Colosseum Rome"
(2026-11-13), including the ``thumb.wikimedia.org`` thumbnail URLs with their
utm parameters and the HTML anchor that Artist arrives as. Downloads are served
from real bytes with the content types Wikimedia sends.

Run them with: uv run --project server pytest screen/tests/test_commons_images.py
"""

from __future__ import annotations

import json
import pathlib
import sys
import unittest

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import commons_images as commons

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 64
HTML = b"<!DOCTYPE html><html><body>Not an image</body></html>"

THUMB = "https://thumb.wikimedia.org/wikipedia/commons/thumb/5/53/Colosseum_in_Rome%2C_Italy_-_April_2007.jpg/960px-Colosseum_in_Rome%2C_Italy_-_April_2007.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail"
ORIGINAL = "https://upload.wikimedia.org/wikipedia/commons/5/53/Colosseum_in_Rome%2C_Italy_-_April_2007.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=original"
DESCRIPTION = "https://commons.wikimedia.org/wiki/File:Colosseum_in_Rome,_Italy_-_April_2007.jpg"
DILIF_ARTIST = '<a href="//commons.wikimedia.org/wiki/User:Diliff" title="User:Diliff">Diliff</a>'


def page(index, *, title="File:Colosseum in Rome, Italy - April 2007.jpg", mime="image/jpeg", size=3947925,
         url=ORIGINAL, thumb=THUMB, description=DESCRIPTION, artist=DILIF_ARTIST,
         licence="CC BY-SA 2.5", licence_url="https://creativecommons.org/licenses/by-sa/2.5",
         thumbmime=None, imageinfo=True, **extra):
    """One imageinfo page as the Commons API returns it."""
    entry = {"size": size, "width": 4827, "height": 2833, "url": url, "descriptionurl": description,
             "mime": mime, "extmetadata": {}}
    if thumb:
        entry["thumburl"] = thumb
        entry["thumbwidth"] = 800
        entry["thumbheight"] = 470
    if thumbmime:
        entry["thumbmime"] = thumbmime
    metadata = {}
    if artist is not None:
        metadata["Artist"] = {"value": artist}
    if licence is not None:
        metadata["LicenseShortName"] = {"value": licence}
    if licence_url is not None:
        metadata["LicenseUrl"] = {"value": licence_url}
    entry["extmetadata"] = metadata
    result = {"pageid": 2067974 + index, "ns": 6, "title": title, "index": index, "imagerepository": "local"}
    if imageinfo:
        result["imageinfo"] = [entry]
    result.update(extra)
    return result


def payload(*pages):
    return {"batchcomplete": "", "query": {"pages": {str(page["pageid"]): page for page in pages}}}


SEARCH = payload(page(2), page(1, title="File:Colosseum in Rome-April 2007-1- copie 2B.jpg"),
                page(3, title="File:Cross Colosseum Rome Italy.jpg", size=6709659,
                     artist='<a href="//commons.wikimedia.org/wiki/User:Jebulon">Jebulon</a>', licence="CC0",
                     licence_url="http://creativecommons.org/publicdomain/zero/1.0/deed.en"))


class CommonsCase(unittest.IsolatedAsyncioTestCase):
    """A client whose transport answers from Python, plus the requests it saw."""

    def serve(self, respond):
        self.requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return respond(request)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.aclose)
        return client

    def serve_json(self, body):
        return self.serve(lambda request: httpx.Response(200, json=body))


class SearchTest(CommonsCase):
    async def test_asks_for_three_commons_bitmaps_and_keeps_credit(self):
        result = await commons.search_images("Colosseum   Rome", client=self.serve_json(SEARCH))

        (request,) = self.requests
        self.assertEqual(request.url.path, "/w/api.php")
        self.assertEqual(request.url.params["action"], "query")
        self.assertEqual(request.url.params["generator"], "search")
        self.assertEqual(request.url.params["gsrnamespace"], "6")
        self.assertEqual(request.url.params["gsrlimit"], "3")
        self.assertEqual(request.url.params["gsrsearch"], "filetype:bitmap Colosseum Rome")
        self.assertEqual(request.url.params["iiprop"], "url|extmetadata|size|mime")
        self.assertEqual(request.url.params["iiurlwidth"], "800")

        self.assertEqual([c.title for c in result.candidates], [
            "File:Colosseum in Rome-April 2007-1- copie 2B.jpg",
            "File:Colosseum in Rome, Italy - April 2007.jpg",
            "File:Cross Colosseum Rome Italy.jpg",
        ])
        first = result.candidates[1]
        self.assertEqual(first.source_url, DESCRIPTION)
        self.assertTrue(first.image_url.startswith("https://thumb.wikimedia.org/wikipedia/commons/thumb/"))
        self.assertEqual(first.mime_type, "image/jpeg")
        self.assertEqual(first.credit, "Bild: Diliff, CC BY-SA 2.5, Wikimedia Commons")
        self.assertEqual(result.candidates[2].credit, "Bild: Jebulon, CC0, Wikimedia Commons")
        self.assertEqual(result.rejected, [])

    async def test_each_boundary_is_rejected_with_a_short_reason(self):
        body = payload(
            page(1, title="File:Good.jpg"),
            page(2, title="File:Vector.svg", mime="image/svg+xml"),
            page(3, title="File:Anonymous.jpg", artist=None),
            page(4, title="File:No licence.jpg", licence=None),
            page(5, title="File:Elsewhere.jpg", thumb="https://evil.example/wikipedia/commons/5/53/Elsewhere.jpg"),
            page(6, title="File:Plain.jpg", thumb=None, url="http://upload.wikimedia.org/wikipedia/commons/5/53/Plain.jpg"),
            page(7, title="File:Traversal.jpg",
                 thumb="https://thumb.wikimedia.org/wikipedia/commons/thumb/../../etc/passwd"),
            page(8, title="File:Huge.jpg", thumb=None, size=9 * 1024 * 1024),
            page(9, title="File:Gone.jpg", imageinfo=False),
        )
        body["query"]["pages"]["-1"] = {"title": "File:Nope.jpg", "missing": ""}
        result = await commons.search_images("Colosseum Rome", client=self.serve_json(body))

        self.assertEqual([c.title for c in result.candidates], ["File:Good.jpg"])
        reasons = {entry["title"]: entry["reason"] for entry in result.rejected}
        self.assertEqual(reasons["File:Vector.svg"], "unsupported media type image/svg+xml")
        self.assertEqual(reasons["File:Anonymous.jpg"], "no author")
        self.assertEqual(reasons["File:No licence.jpg"], "no licence")
        self.assertEqual(reasons["File:Elsewhere.jpg"], "image host evil.example is not Wikimedia")
        self.assertEqual(reasons["File:Plain.jpg"], "image URL is not https")
        self.assertEqual(reasons["File:Traversal.jpg"], "image path has a traversal segment")
        self.assertIn("over the", reasons["File:Huge.jpg"])
        self.assertEqual(reasons["File:Gone.jpg"], "no imageinfo")
        self.assertEqual(reasons["File:Nope.jpg"], "no such Commons file")
        self.assertEqual(len(self.requests), 1)

        elsewhere = next(entry for entry in result.rejected if entry["title"] == "File:Elsewhere.jpg")
        self.assertEqual(elsewhere["source"], DESCRIPTION)
        self.assertEqual(elsewhere["licence_url"], "https://creativecommons.org/licenses/by-sa/2.5")

    async def test_keeps_at_most_three_candidates(self):
        body = payload(*[page(index, title=f"File:Colosseum {index}.jpg") for index in range(1, 5)])
        result = await commons.search_images("Colosseum Rome", client=self.serve_json(body))
        self.assertEqual(len(result.candidates), 3)
        self.assertEqual(result.rejected, [])

    async def test_thumbnail_type_wins_over_the_original_type(self):
        body = payload(page(1, title="File:Plan.tiff", mime="image/tiff", thumbmime="image/png",
                            thumb=THUMB.replace(".jpg", ".png")))
        result = await commons.search_images("Colosseum plan", client=self.serve_json(body))
        self.assertEqual(result.candidates[0].mime_type, "image/png")

    async def test_empty_query_makes_no_request(self):
        client = self.serve_json(SEARCH)
        result = await commons.search_images("   ", client=client)
        self.assertEqual((result.candidates, self.requests), ([], []))
        self.assertEqual(result.rejected[0]["reason"], "empty query")

    async def test_api_failure_is_raised_not_swallowed(self):
        client = self.serve(lambda request: httpx.Response(503, text="upstream down"))
        with self.assertRaises(httpx.HTTPStatusError):
            await commons.search_images("Colosseum Rome", client=client)


class LookupTest(CommonsCase):
    async def test_thumbnail_link_resolves_through_its_file_title(self):
        link = ("https://thumb.wikimedia.org/wikipedia/commons/thumb/8/8e/Cross_Colosseum_Rome_Italy.jpg/"
                "960px-Cross_Colosseum_Rome_Italy.jpg?utm_source=commons.wikimedia.org&utm_content=thumbnail")
        body = payload(page(3, title="File:Cross Colosseum Rome Italy.jpg", artist="Jebulon", licence="CC BY-SA 4.0",
                            licence_url="https://creativecommons.org/licenses/by-sa/4.0"))
        result = await commons.lookup_image(link, client=self.serve_json(body))

        (request,) = self.requests
        self.assertEqual(request.url.params["titles"], "File:Cross Colosseum Rome Italy.jpg")
        self.assertNotIn("generator", request.url.params)
        self.assertEqual(result.candidates[0].credit, "Bild: Jebulon, CC BY-SA 4.0, Wikimedia Commons")

    async def test_file_page_link_is_looked_up_and_its_credit_is_not_trusted(self):
        link = DESCRIPTION + "?credit=Bild%3A%20Pwned%2C%20CC0"
        body = payload(page(1))
        result = await commons.lookup_image(link, client=self.serve_json(body))

        self.assertEqual(self.requests[0].url.params["titles"],
                         "File:Colosseum in Rome, Italy - April 2007.jpg")
        self.assertEqual(result.candidates[0].credit, "Bild: Diliff, CC BY-SA 2.5, Wikimedia Commons")

    async def test_links_off_commons_and_its_image_hosts_are_refused_before_any_request(self):
        for link in [
            "https://example.com/wiki/File:Colosseum.jpg",
            "http://commons.wikimedia.org/wiki/File:Colosseum.jpg",
            "https://upload.wikimedia.org/wikipedia/commons/../../etc/passwd",
            "https://upload.wikimedia.org:8443/wikipedia/commons/5/53/Colosseum.jpg",
            "https://upload.wikimedia.org:notaport/wikipedia/commons/5/53/Colosseum.jpg",
            "https://user:secret@upload.wikimedia.org/wikipedia/commons/5/53/Colosseum.jpg",
            "https://commons.wikimedia.org/wiki/Category:Colosseum",
            "https://thumb.wikimedia.org/wikipedia/en/thumb/5/53/Colosseum.jpg",
            "javascript:alert(1)",
            "",
        ]:
            with self.subTest(link=link):
                result = await commons.lookup_image(link, client=self.serve_json(payload(page(1))))
                self.assertEqual(result.candidates, [])
                self.assertTrue(result.rejected[0]["reason"])
        self.assertEqual(self.requests, [])

    async def test_missing_file_is_reported(self):
        client = self.serve(lambda request: httpx.Response(
            200, json={"batchcomplete": "", "query": {"pages": {"-1": {"title": "File:Nope.jpg", "missing": ""}}}}))
        result = await commons.lookup_image("https://commons.wikimedia.org/wiki/File:Nope.jpg", client=client)
        self.assertEqual((result.candidates, result.rejected[0]["reason"]), ([], "no such Commons file"))


class DownloadTest(CommonsCase):
    def candidate(self, image_url=THUMB, mime="image/jpeg"):
        return commons.Candidate(title="File:Colosseum.jpg", source_url=DESCRIPTION,
                                 image_url=image_url, mime_type=mime,
                                 credit="Bild: Diliff, CC BY-SA 2.5, Wikimedia Commons")

    def serve_image(self, body=JPEG, *, status=200, content_type="image/jpeg", headers=None):
        def respond(request):
            return httpx.Response(status, content=body, headers={"content-type": content_type, **(headers or {})})

        return self.serve(respond)

    async def test_returns_the_bitmap_bytes_for_each_supported_type(self):
        for mime, body in [("image/jpeg", JPEG), ("image/png", PNG), ("image/webp", WEBP)]:
            with self.subTest(mime=mime):
                client = self.serve_image(body, content_type=mime)
                self.assertEqual(await commons.download_image(self.candidate(mime=mime), client=client), body)
                self.assertEqual(str(self.requests[-1].url), THUMB)

    async def test_html_pretending_to_be_an_image_is_refused(self):
        client = self.serve_image(HTML, content_type="image/jpeg")
        with self.assertRaisesRegex(ValueError, "not a bitmap"):
            await commons.download_image(self.candidate(), client=client)

    async def test_an_html_content_type_is_refused_even_with_image_bytes(self):
        client = self.serve_image(JPEG, content_type="text/html; charset=utf-8")
        with self.assertRaisesRegex(ValueError, "text/html"):
            await commons.download_image(self.candidate(), client=client)

    async def test_a_redirect_is_refused_and_not_followed(self):
        def respond(request):
            return httpx.Response(302, headers={"location": "https://evil.example/colosseum.jpg"})

        client = self.serve(respond)
        with self.assertRaisesRegex(ValueError, "redirects"):
            await commons.download_image(self.candidate(), client=client)
        self.assertEqual(len(self.requests), 1)

    async def test_a_declared_length_over_two_mib_is_refused_before_reading(self):
        client = self.serve_image(JPEG, headers={"content-length": str(commons.MAX_BYTES + 1)})
        with self.assertRaisesRegex(ValueError, "over the"):
            await commons.download_image(self.candidate(), client=client)

    async def test_a_stream_that_grows_past_two_mib_is_cut_off(self):
        chunk = PNG + b"\x00" * (commons.MAX_BYTES // 2)

        async def stream():
            for _ in range(3):
                yield chunk

        def respond(request):
            return httpx.Response(200, content=stream(), headers={"content-type": "image/png"})

        with self.assertRaisesRegex(ValueError, "grew past"):
            await commons.download_image(self.candidate(mime="image/png"), client=self.serve(respond))

    async def test_a_failed_download_raises(self):
        client = self.serve_image(b"", status=404, content_type="text/plain")
        with self.assertRaisesRegex(ValueError, "HTTP 404"):
            await commons.download_image(self.candidate(), client=client)

    async def test_a_candidate_off_wikimedia_is_never_fetched(self):
        client = self.serve_image()
        for url in [
            "https://evil.example/wikipedia/commons/5/53/Colosseum.jpg",
            "http://upload.wikimedia.org/wikipedia/commons/5/53/Colosseum.jpg",
            "https://upload.wikimedia.org/wikipedia/en/5/53/Colosseum.jpg",
            "https://upload.wikimedia.org:8443/wikipedia/commons/5/53/Colosseum.jpg",
            "https://user:secret@thumb.wikimedia.org/wikipedia/commons/5/53/Colosseum.jpg",
        ]:
            with self.subTest(url=url):
                with self.assertRaisesRegex(ValueError, "Refusing to download"):
                    await commons.download_image(self.candidate(image_url=url), client=client)
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
