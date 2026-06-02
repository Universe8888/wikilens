"""Shared prompt sanitization and XML delimiter utilities.

Every LLM prompt that interpolates user content (vault text, claims, paths)
MUST pass that content through sanitise_xml() before insertion into XML-tagged
templates. This prevents prompt injection via crafted note content.
"""

from __future__ import annotations


def sanitise_xml(text: str) -> str:
    """Escape XML-significant characters in user content.

    Prevents delimiter breakout when user text is inserted into XML-tagged
    prompt templates (e.g. <passage_a>...</passage_a>).
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def xml_tag(tag: str, content: str, *, sanitize: bool = True) -> str:
    """Wrap content in an XML tag pair, sanitizing by default."""
    body = sanitise_xml(content) if sanitize else content
    return f"<{tag}>\n{body}\n</{tag}>"
