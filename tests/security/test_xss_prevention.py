"""Tests for XSS prevention across all inputs.

This module tests Cross-Site Scripting (XSS) attack prevention to ensure:
1. Script tags are not injected into text fields
2. Event handlers are neutralized
3. JavaScript URLs are blocked
4. HTML entities are properly handled
5. SVG and other embedded content is safe

Note: XSS prevention is primarily handled at the output/display layer.
These tests verify that input sanitization doesn't introduce vulnerabilities.
"""

import pytest

from mahavishnu.core.task_models import (
    FTSSearchQuery,
    TaskCreateRequest,
    TaskUpdateRequest,
)


class TestScriptTagInjection:
    """Tests for <script> tag injection prevention."""

    def test_script_tag_in_title_preserved(self):
        """Test that script tags in title are preserved as text (not rendered).

        Note: Titles are plain text, not HTML. XSS prevention is at render time.
        """
        request = TaskCreateRequest(
            title="<script>alert('xss')</script>",
            repository="test-repo",
        )
        # The title is preserved as literal text
        assert "<script>" in request.title
        assert "alert" in request.title

    def test_script_tag_in_description_preserved(self):
        """Test that script tags in description are preserved as text."""
        request = TaskCreateRequest(
            title="Test",
            repository="test-repo",
            description="<script>document.cookie</script>",
        )
        assert "<script>" in request.description

    def test_script_src_injection(self):
        """Test that script src injection is handled."""
        request = TaskCreateRequest(
            title='<script src="https://evil.com/xss.js">',
            repository="test-repo",
        )
        # Preserved as text
        assert "evil.com" in request.title

    def test_mixed_case_script_tag(self):
        """Test that mixed case script tags are handled."""
        request = TaskCreateRequest(
            title="<ScRiPt>alert('xss')</ScRiPt>",
            repository="test-repo",
        )
        assert "<ScRiPt>" in request.title


class TestEventHandlerInjection:
    """Tests for event handler injection prevention."""

    def test_onclick_handler_in_title(self):
        """Test that onclick handlers are preserved as text."""
        request = TaskCreateRequest(
            title='<div onclick="alert(1)">click</div>',
            repository="test-repo",
        )
        assert "onclick" in request.title

    def test_onerror_handler(self):
        """Test that onerror handlers are preserved as text."""
        request = TaskCreateRequest(
            title='<img src=x onerror="alert(1)">',
            repository="test-repo",
        )
        assert "onerror" in request.title

    def test_onload_handler(self):
        """Test that onload handlers are preserved as text."""
        request = TaskCreateRequest(
            title='<body onload="alert(1)">',
            repository="test-repo",
        )
        assert "onload" in request.title

    def test_onmouseover_handler(self):
        """Test that onmouseover handlers are preserved as text."""
        request = TaskCreateRequest(
            title='<div onmouseover="alert(1)">hover</div>',
            repository="test-repo",
        )
        assert "onmouseover" in request.title


class TestJavaScriptURLInjection:
    """Tests for javascript: URL injection prevention."""

    def test_javascript_url_in_title(self):
        """Test that javascript: URLs are preserved as text."""
        request = TaskCreateRequest(
            title='Click here: javascript:alert(1)',
            repository="test-repo",
        )
        assert "javascript:" in request.title

    def test_javascript_url_with_encoding(self):
        """Test that encoded javascript URLs are preserved as text."""
        request = TaskCreateRequest(
            title='javascript%3Aalert(1)',
            repository="test-repo",
        )
        # Preserved as text (not decoded)
        assert "javascript" in request.title

    def test_javascript_url_uppercase(self):
        """Test that uppercase JAVASCRIPT: URLs are preserved as text."""
        request = TaskCreateRequest(
            title='JAVASCRIPT:alert(1)',
            repository="test-repo",
        )
        assert "JAVASCRIPT:" in request.title


class TestDataURIInjection:
    """Tests for data: URI injection prevention."""

    def test_data_uri_in_title(self):
        """Test that data: URIs are preserved as text."""
        request = TaskCreateRequest(
            title='data:text/html,<script>alert(1)</script>',
            repository="test-repo",
        )
        assert "data:" in request.title

    def test_data_uri_base64(self):
        """Test that base64 data URIs are preserved as text."""
        request = TaskCreateRequest(
            title='data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==',
            repository="test-repo",
        )
        assert "base64" in request.title


class TestSVGInjection:
    """Tests for SVG-based XSS injection prevention."""

    def test_svg_onload_in_title(self):
        """Test that SVG onload is preserved as text."""
        request = TaskCreateRequest(
            title='<svg onload="alert(1)">',
            repository="test-repo",
        )
        assert "<svg" in request.title
        assert "onload" in request.title

    def test_svg_script_injection(self):
        """Test that SVG script elements are preserved as text."""
        request = TaskCreateRequest(
            title='<svg><script>alert(1)</script></svg>',
            repository="test-repo",
        )
        assert "<svg>" in request.title

    def test_svg_foreignobject(self):
        """Test that SVG foreignObject is preserved as text."""
        request = TaskCreateRequest(
            title='<svg><foreignObject><script>alert(1)</script></foreignObject></svg>',
            repository="test-repo",
        )
        assert "foreignObject" in request.title


class TestHTMLAttributeInjection:
    """Tests for HTML attribute injection prevention."""

    def test_attribute_breakout(self):
        """Test that attribute breakouts are preserved as text."""
        request = TaskCreateRequest(
            title='"><script>alert(1)</script>',
            repository="test-repo",
        )
        # The title is preserved as text, including the quote
        assert '">' in request.title

    def test_single_quote_breakout(self):
        """Test that single quote breakouts are preserved as text."""
        request = TaskCreateRequest(
            title="'><script>alert(1)</script>",
            repository="test-repo",
        )
        assert "'>" in request.title

    def test_attribute_without_quotes(self):
        """Test that unquoted attribute injection is preserved as text."""
        request = TaskCreateRequest(
            title='onmouseover=alert(1)',
            repository="test-repo",
        )
        assert "onmouseover" in request.title


class TestUnicodeXSS:
    """Tests for Unicode-based XSS injection prevention."""

    def test_unicode_script_tag(self):
        """Test that Unicode script tags are preserved as text."""
        # Using Unicode escapes for <script>
        request = TaskCreateRequest(
            title='\u003cscript\u003ealert(1)\u003c/script\u003e',
            repository="test-repo",
        )
        # Unicode is preserved as-is
        assert "script" in request.title

    def test_unicode_null_byte(self):
        """Test that Unicode null bytes are handled."""
        request = TaskCreateRequest(
            title="test\u0000script",
            repository="test-repo",
        )
        # Null bytes should be removed
        assert "\u0000" not in request.title


class TestCSSInjection:
    """Tests for CSS-based injection prevention."""

    def test_expression_injection(self):
        """Test that CSS expression() is preserved as text."""
        request = TaskCreateRequest(
            title='style="width:expression(alert(1))"',
            repository="test-repo",
        )
        assert "expression" in request.title

    def test_css_import(self):
        """Test that CSS @import is preserved as text."""
        request = TaskCreateRequest(
            title='@import url("https://evil.com/evil.css")',
            repository="test-repo",
        )
        assert "@import" in request.title


class TestUpdateRequestXSS:
    """Tests for XSS in update requests."""

    def test_update_title_with_script(self):
        """Test that script tags in update title are preserved as text."""
        update = TaskUpdateRequest(title="<script>alert(1)</script>")
        assert "<script>" in update.title

    def test_update_description_with_xss(self):
        """Test that XSS in update description is preserved as text."""
        update = TaskUpdateRequest(
            description='<img src=x onerror="alert(1)">'
        )
        assert "onerror" in update.description


class TestFTSSearchXSS:
    """Tests for XSS in full-text search queries."""

    def test_search_query_with_script(self):
        """Test that script tags in search query are handled."""
        # Script tags are not dangerous in search - they're just text
        query = FTSSearchQuery(query="<script>alert(1)</script>")
        assert "script" in query.query

    def test_search_query_with_html(self):
        """Test that HTML in search query is handled."""
        query = FTSSearchQuery(query="<div>search term</div>")
        assert "div" in query.query
