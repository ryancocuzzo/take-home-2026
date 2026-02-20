from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


@dataclass(frozen=True)
class UrlNormalizer:
    resize_query_keys: set[str] = field(
        default_factory=lambda: {
            "w",
            "width",
            "h",
            "height",
            "q",
            "quality",
            "fit",
            "crop",
            "auto",
            "fm",
            "format",
            "ixlib",
            "_mzcb",
        }
    )

    def canonicalize(self, value: str, page_url: str | None) -> str:
        if not value:
            return value
        url = value.strip()
        if url.startswith("//"):
            url = f"https:{url}"
        elif page_url:
            url = urljoin(page_url, url)

        parts = urlsplit(url)
        filtered_query = [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k not in self.resize_query_keys
        ]
        rebuilt_query = urlencode(filtered_query, doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, rebuilt_query, ""))
