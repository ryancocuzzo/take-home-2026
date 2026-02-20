import html
from dataclasses import dataclass
from html.parser import HTMLParser


@dataclass(frozen=True)
class ScriptSignal:
    attrs: dict[str, str]
    body: str


@dataclass(frozen=True)
class MetaSignal:
    key: str
    content: str


class _SignalParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[ScriptSignal] = []
        self.meta_tags: list[MetaSignal] = []
        self._script_attrs: dict[str, str] | None = None
        self._script_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): (value or "") for key, value in attrs}
        tag = tag.lower()
        if tag == "script":
            self._script_attrs = attrs_dict
            self._script_chunks = []
            return
        if tag != "meta":
            return

        key = (attrs_dict.get("property") or attrs_dict.get("name") or attrs_dict.get("itemprop") or "").strip()
        content = (attrs_dict.get("content") or "").strip()
        if key and content:
            self.meta_tags.append(MetaSignal(key=key.lower(), content=html.unescape(content)))

    def handle_data(self, data: str) -> None:
        if self._script_attrs is not None:
            self._script_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script" or self._script_attrs is None:
            return
        body = html.unescape("".join(self._script_chunks).strip())
        self.scripts.append(ScriptSignal(attrs=self._script_attrs, body=body))
        self._script_attrs = None
        self._script_chunks = []


def extract_html_signals(html_text: str) -> tuple[list[ScriptSignal], list[MetaSignal]]:
    parser = _SignalParser()
    parser.feed(html_text)
    return parser.scripts, parser.meta_tags
