"""Read the standalone offline user manual as navigable help topics.

The parser deliberately uses Python's standard library only. It never loads a
web page, fetches remote content, or executes scripts. The HTML is authored in
this repository and contains sibling, uniquely identified <section> topics.
"""
from dataclasses import dataclass
from html import unescape
from pathlib import Path
import re


_SECTION = re.compile(
    r'<section\s+id="([A-Za-z0-9_-]+)"[^>]*>(.*?)</section>',
    re.IGNORECASE | re.DOTALL,
)
_HEADING = re.compile(r"<h[12]\b[^>]*>(.*?)</h[12]>", re.IGNORECASE | re.DOTALL)
_LINK = re.compile(
    r'<a\s+href="#([A-Za-z0-9_-]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class HelpTopic:
    topic_id: str
    title: str
    html: str
    text: str


def plain_text(html):
    """Strip the manual's trusted markup for native search and list labels."""
    without_tags = re.sub(r"<[^>]*>", " ", html)
    return " ".join(unescape(without_tags).split())


def read_manual(path):
    """Return ordered topics and (initial letter, term, target) index entries.

    Missing/invalid documentation fails visibly rather than displaying an
    empty help window. There is no HTML engine dependency for indexing.
    """
    document = Path(path).read_text(encoding="utf-8")
    topics = []
    seen = set()
    for match in _SECTION.finditer(document):
        topic_id, body = match.groups()
        if topic_id in seen:
            raise ValueError(f"Duplicate Help topic: {topic_id}")
        seen.add(topic_id)
        heading = _HEADING.search(body)
        title = plain_text(heading.group(1)) if heading else topic_id.title()
        if topic_id == "welcome":
            title = "Welcome to 3DO CAD"
        topics.append(HelpTopic(topic_id, title, body.strip(), plain_text(body)))

    if not topics or "welcome" not in seen:
        raise ValueError("The Help file contains no recognizable manual topics.")

    entries = []
    index = next((topic for topic in topics if topic.topic_id == "index"), None)
    if index:
        for paragraph in re.findall(
            r"<p\b[^>]*>(.*?)</p>", index.html, re.IGNORECASE | re.DOTALL
        ):
            letter = re.search(
                r"<b\b[^>]*>(.*?)</b>", paragraph, re.IGNORECASE | re.DOTALL
            )
            if letter is None:
                continue
            group = plain_text(letter.group(1))
            for link in _LINK.finditer(paragraph):
                target, term = link.groups()
                if target in seen:
                    entries.append((group, plain_text(term), target))
    return topics, entries
