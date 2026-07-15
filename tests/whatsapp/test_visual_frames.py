from __future__ import annotations

import base64
import unittest

from orbit.whatsapp.visual_frames import VisualFrameMixin


class VisualFrameTests(unittest.TestCase):
    def test_decodes_small_jpeg_data_url(self):
        payload = base64.b64encode(b"jpeg-bytes").decode("ascii")
        data_url = f"data:image/jpeg;base64,{payload}"

        returned_url, image_bytes, mime_type = VisualFrameMixin._decode_visual_data_url(data_url)

        self.assertEqual(returned_url, data_url)
        self.assertEqual(image_bytes, b"jpeg-bytes")
        self.assertEqual(mime_type, "image/jpeg")

    def test_rejects_non_image_data_url(self):
        with self.assertRaisesRegex(ValueError, "image data URL"):
            VisualFrameMixin._decode_visual_data_url("data:text/plain;base64,SGVsbG8=")

    def test_fallback_summary_is_compact(self):
        summary = VisualFrameMixin._fallback_visual_summary(
            {"title": "Q3 plan", "key_points": ["Ship beta", "Measure retention"]}
        )
        self.assertEqual(summary, "Q3 plan: Ship beta; Measure retention")


if __name__ == "__main__":
    unittest.main()
