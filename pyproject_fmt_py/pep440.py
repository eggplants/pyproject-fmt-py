"""Reading and writing a version the way [PEP 440](https://peps.python.org/pep-0440/) spells one.

A number is held as the value it names rather than as the digits the file wrote, since a leading
zero names no number of its own. What a segment leaves unwritten is the zero the spec reads there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_PEP440 = re.compile(
    r"""
    ^
    v?
    (?:(?P<epoch>[0-9]+)!)?
    (?P<release>[0-9]+(?:\.[0-9]+)*)
    (?:[-_.]?(?P<pre_l>alpha|a|beta|b|preview|pre|c|rc)[-_.]?(?P<pre_n>[0-9]+)?)?
    (?:-(?P<post_n1>[0-9]+)|[-_.]?(?P<post_l>post|rev|r)[-_.]?(?P<post_n2>[0-9]+)?)?
    (?P<dev>[-_.]?dev[-_.]?(?P<dev_n>[0-9]+)?)?
    (?:\+(?P<local>[a-z0-9]+(?:[-_.][a-z0-9]+)*))?
    $
    """,
    re.VERBOSE | re.IGNORECASE,
)

#: What each pre-release label is written as once it is read.
_PRE_LABELS = {"alpha": "a", "a": "a", "beta": "b", "b": "b", "rc": "rc", "c": "rc", "pre": "rc", "preview": "rc"}


def is_valid_version(raw: str) -> bool:
    """Whether the text is a version PEP 440 reads."""
    return _PEP440.match(raw.strip()) is not None


def written_number(digits: str) -> int | None:
    """The number the digits name, where what was written is digits counted the way PEP 440 counts.

    A leading zero names no number of its own, so `01` is not a number the file may write.
    """
    if not digits.isdigit():
        return None
    value = int(digits)
    return value if str(value) == digits else None


@dataclass
class Version:
    """What a version says, in the parts PEP 440 reads it as.

    Attributes:
        release: The numbers the release names, at least one.
        epoch: The epoch, where the version names one.
        pre: The pre-release label and its number, where the version names one.
        post: Whether it names a post release, and its number.
        dev: Whether it names a development release, and its number.
        local: The local version, lowercased.
        has_wildcard: Whether the version closed with `.*`.
    """

    release: list[int] = field(default_factory=list)
    epoch: int | None = None
    pre: tuple[str, int | None] | None = None
    post: tuple[str | None, int | None] | None = None
    dev: tuple[str, int | None] | None = None
    local: str | None = None
    has_wildcard: bool = False

    @classmethod
    def parse(cls, raw: str) -> Version:
        """Read a version.

        Raises:
            ValueError: If the text is not a version PEP 440 reads.
        """
        text = raw.strip()
        has_wildcard = text.endswith(".*")
        if has_wildcard:
            text = text[:-2]
        found = _PEP440.match(text)
        if found is None:
            msg = f"Invalid version: {text}"
            raise ValueError(msg)

        def number(name: str) -> int | None:
            held = found.group(name)
            return int(held) if held is not None else None

        # an implicit post release is written `1.0-1`, which names the number without the label
        if found.group("post_n1") is not None:
            post: tuple[str | None, int | None] | None = (None, number("post_n1"))
        elif found.group("post_l") is not None:
            post = ("post", number("post_n2"))
        else:
            post = None
        pre_label = found.group("pre_l")
        local = found.group("local")
        return cls(
            release=[int(part) for part in found.group("release").split(".")],
            epoch=number("epoch"),
            pre=(pre_label.lower(), number("pre_n")) if pre_label is not None else None,
            post=post,
            dev=("dev", number("dev_n")) if found.group("dev") is not None else None,
            local=local.lower() if local is not None else None,
            has_wildcard=has_wildcard,
        )

    def __str__(self) -> str:
        """The version as PEP 440 spells one, each label in its canonical form."""
        written = f"{self.epoch}!" if self.epoch is not None else ""
        written += ".".join(str(part) for part in self.release)
        if self.pre is not None:
            label, held = self.pre
            written += _PRE_LABELS.get(label, label) + _numbered(held)
        if self.post is not None:
            written += ".post" + _numbered(self.post[1])
        if self.dev is not None:
            written += ".dev" + _numbered(self.dev[1])
        if self.local is not None:
            written += "+" + self.local.replace("-", ".").replace("_", ".")
        if self.has_wildcard:
            written += ".*"
        return written

    def drop_redundant_zeros(self) -> None:
        """Drop the trailing `.0` a release names nothing by, keeping at least one number."""
        while len(self.release) > 1 and self.release[-1] == 0:
            self.release.pop()


def _numbered(held: int | None) -> str:
    """The digits a segment holds, or the zero PEP 440 reads where the file wrote none."""
    return "0" if held is None else str(held)
