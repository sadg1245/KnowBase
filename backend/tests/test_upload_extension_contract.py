"""Upload whitelist and parser factory must agree on supported file types."""

import unittest

from fastapi import HTTPException

from app.api.routes.documents import ALLOWED_EXTENSIONS, _validate_extension
from app.collector.pipeline import DocumentPipeline, supported_file_types
from app.collector.parsers.base import BaseParser


class UploadExtensionContractTests(unittest.TestCase):
    def test_whitelist_is_derived_from_the_parser_factory(self):
        self.assertEqual(
            ALLOWED_EXTENSIONS, {f".{name}" for name in supported_file_types()}
        )

    def test_every_allowed_extension_builds_a_parser(self):
        pipeline = DocumentPipeline(None, None, None)
        DocumentPipeline._PARSER_CACHE.clear()
        for extension in sorted(ALLOWED_EXTENSIONS):
            with self.subTest(extension=extension):
                parser = pipeline._get_parser(extension.lstrip("."))
                self.assertIsInstance(parser, BaseParser)

    def test_textual_markup_formats_reuse_text_parsers(self):
        pipeline = DocumentPipeline(None, None, None)
        DocumentPipeline._PARSER_CACHE.clear()
        for extension, expected in (
            (".rst", "MarkdownParser"),
            (".json", "_TxtParser"),
            (".xml", "_TxtParser"),
            (".yaml", "_TxtParser"),
            (".yml", "_TxtParser"),
        ):
            with self.subTest(extension=extension):
                parser = pipeline._get_parser(extension.lstrip("."))
                self.assertEqual(type(parser).__name__, expected)

    def test_doc_files_are_rejected_until_a_parser_exists(self):
        with self.assertRaises(HTTPException) as caught:
            _validate_extension("legacy.doc")
        self.assertEqual(caught.exception.status_code, 400)
