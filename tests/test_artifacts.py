import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from doubao_sign.artifacts import (
    ArtifactDownloadError,
    ArtifactKind,
    ArtifactRef,
    download_artifact,
    extract_artifact_refs,
)


class FakeResponse:
    def __init__(self, *, status_code=200, content=b"data", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


class RecordingGetter:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class ArtifactExtractionTests(unittest.TestCase):
    def test_extracts_typed_image_url_and_ignores_normal_link(self):
        event = json.dumps(
            {
                "content": {
                    "content_block": [
                        {
                            "content": {
                                "image_block": {
                                    "image_url": "https://cdn.example/image-output.webp"
                                }
                            }
                        },
                        {
                            "content": {
                                "text_block": {
                                    "link": "https://example.com/article"
                                }
                            }
                        },
                    ]
                }
            }
        )

        refs = extract_artifact_refs(event, ArtifactKind.IMAGE)

        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].url, "https://cdn.example/image-output.webp")
        self.assertEqual(refs[0].kind, ArtifactKind.IMAGE)

    def test_prefers_raw_original_over_watermarked_and_preview_variants(self):
        event = json.dumps({
            "creations": [{
                "image": {
                    "image_thumb": {"url": "https://cdn.example/thumb.png"},
                    "image_ori": {"url": "https://cdn.example/original.png"},
                    "image_preview": {"url": "https://cdn.example/preview.png"},
                    "image_ori_raw": {"url": "https://cdn.example/raw.png"},
                }
            }],
            "icon_url": "https://cdn.example/icon.png",
        })
        refs = extract_artifact_refs(event, ArtifactKind.IMAGE)
        self.assertEqual(
            [ref.url for ref in refs],
            ["https://cdn.example/raw.png"],
        )

    def test_extracts_extensionless_ppt_download_from_typed_context(self):
        event = json.dumps(
            {
                "patch_op": [
                    {
                        "patch_value": {
                            "presentation_file": {
                                "file_name": "验收演示.pptx",
                                "download_url": "https://cdn.example/download?id=42",
                            }
                        }
                    }
                ]
            },
            ensure_ascii=False,
        )

        refs = extract_artifact_refs(event, ArtifactKind.PPT)

        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].filename, "验收演示.pptx")

    def test_deduplicates_repeated_url_within_event(self):
        url = "https://cdn.example/result.png"
        event = json.dumps({"image_url": url, "preview_image_url": url})

        refs = extract_artifact_refs(event, ArtifactKind.IMAGE)

        self.assertEqual([ref.url for ref in refs], [url])

    def test_ignores_malformed_sse_json(self):
        self.assertEqual(extract_artifact_refs("not-json", ArtifactKind.IMAGE), ())


class ArtifactDownloadTests(unittest.TestCase):
    def test_downloads_image_with_auth_headers_and_content_type_extension(self):
        getter = RecordingGetter(
            FakeResponse(content=b"\x89PNG\r\n\x1a\ncontent", headers={"content-type": "image/png"})
        )
        headers = {"Cookie": "private", "User-Agent": "UA", "Referer": "ref"}
        ref = ArtifactRef(ArtifactKind.IMAGE, "https://cdn.example/download")
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)

            saved = download_artifact(ref, root, headers, getter=getter)

            self.assertEqual(saved.parent, root / "images")
            self.assertEqual(saved.suffix, ".png")
            self.assertEqual(saved.read_bytes(), b"\x89PNG\r\n\x1a\ncontent")
        self.assertEqual(getter.calls[0][1]["headers"], headers)

    def test_unsafe_ppt_filename_stays_inside_kind_directory(self):
        getter = RecordingGetter(
            FakeResponse(
                content=b"PK\x03\x04pptx",
                headers={
                    "content-type": "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                },
            )
        )
        ref = ArtifactRef(
            ArtifactKind.PPT,
            "https://cdn.example/download?id=9",
            "../../outside.pptx",
        )
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)

            saved = download_artifact(ref, root, {}, getter=getter)

            self.assertEqual(saved.parent, root / "ppt")
            self.assertEqual(saved.name, "outside.pptx")
            self.assertTrue(saved.is_file())

    def test_http_error_does_not_expose_remote_url(self):
        getter = RecordingGetter(FakeResponse(status_code=403))
        ref = ArtifactRef(ArtifactKind.IMAGE, "https://secret.example/token-value.png")
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            with self.assertRaises(ArtifactDownloadError) as caught:
                download_artifact(ref, Path(directory), {}, getter=getter)

        self.assertIn("HTTP 403", str(caught.exception))
        self.assertNotIn("secret.example", str(caught.exception))

    def test_empty_download_is_rejected(self):
        getter = RecordingGetter(
            FakeResponse(content=b"", headers={"content-type": "image/png"})
        )
        ref = ArtifactRef(ArtifactKind.IMAGE, "https://cdn.example/result.png")
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            with self.assertRaisesRegex(ArtifactDownloadError, "空文件"):
                download_artifact(ref, Path(directory), {}, getter=getter)


if __name__ == "__main__":
    unittest.main()
