import html
import json
from dataclasses import dataclass
from html.parser import HTMLParser


@dataclass(frozen=True)
class DataJsonSignal:
    """A data-* attribute whose value is JSON (e.g. data-product-object)."""
    key: str
    payload: dict | list


@dataclass(frozen=True)
class ScriptSignal:
    attrs: dict[str, str]
    body: str


@dataclass(frozen=True)
class MetaSignal:
    key: str
    content: str


_DATA_JSON_ATTRS = frozenset({"data-product-object", "data-product", "data-colorways"})
_DATA_COLOR_ATTR = "data-product-color"
_DATA_SWATCH_ATTR = "data-color-swatch"


class _SignalParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[ScriptSignal] = []
        self.meta_tags: list[MetaSignal] = []
        self.data_json: list[DataJsonSignal] = []
        self.data_color_values: list[str] = []
        self._script_attrs: dict[str, str] | None = None
        self._script_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): (value or "") for key, value in attrs}
        tag = tag.lower()
        if tag == "script":
            self._script_attrs = attrs_dict
            self._script_chunks = []
            return

        for key, value in attrs_dict.items():
            if key in _DATA_JSON_ATTRS and value.strip().startswith(("{", "[")):
                try:
                    payload = json.loads(html.unescape(value.strip()))
                    if isinstance(payload, (dict, list)):
                        self.data_json.append(DataJsonSignal(key=key, payload=payload))
                except json.JSONDecodeError:
                    pass
            elif key == _DATA_COLOR_ATTR and value.strip():
                self.data_color_values.append(html.unescape(value.strip()))
            elif key == _DATA_SWATCH_ATTR:
                aria = attrs_dict.get("aria-label", "").strip()
                if " - " in aria and " swatch" in aria:
                    color_part = aria.split(" - ", 1)[1].removesuffix(" swatch")
                    if color_part:
                        self.data_color_values.append(html.unescape(color_part))

        if tag == "meta":
            # Meta tags: accept property/name/itemprop as key
            key = (attrs_dict.get("property") or attrs_dict.get("name") or attrs_dict.get("itemprop") or "").strip()
        else:
            # Non-meta elements: only accept itemprop + content (schema.org microdata)
            # e.g. <span itemprop="price" content="29.95">
            key = attrs_dict.get("itemprop", "").strip()

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


def extract_html_signals(
    html_text: str,
) -> tuple[list[ScriptSignal], list[MetaSignal], list[DataJsonSignal], list[str]]:
    parser = _SignalParser()
    parser.feed(html_text)
    return parser.scripts, parser.meta_tags, parser.data_json, parser.data_color_values
