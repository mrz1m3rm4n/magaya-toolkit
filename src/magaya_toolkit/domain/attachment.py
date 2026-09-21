"""Domain read models for Magaya transaction attachments and documents.

Magaya keeps two distinct kinds of file on a transaction, and they are read
differently:

- **Attachments** — files someone attached (a scan, an invoice XML). Listed by
  `GetAllAttachments`, fetched one at a time by `GetAttachment`.
- **Documents** — Magaya's own generated paperwork (a Bill of Lading, an
  invoice layout). Listed inside the transaction itself when it is read with
  the `AttachDocsSummary` flag, then rendered to PDF by `GetWebDocument`.

Both are two-step trips: bytes never ship inside a transaction read, so you
list first and fetch what you want second. The models mirror that split — a
`*Ref` to choose from, and a content model with the bytes.

Read-only: these models are only ever populated from data the API returns.
"""

from __future__ import annotations

from pydantic import BaseModel


class AttachmentRef(BaseModel):
    """A pointer to one attachment, as listed by `GetAllAttachments`.

    The three fields `GetAttachment` needs are `owner_type`, `owner_guid` and
    `identifier` — the API reference calls them `app`, `trans_uuid` and
    `attach_id`. `size` is the decoded size in bytes, so you can decide whether
    to fetch before you do.
    """

    name: str | None = None
    extension: str | None = None
    is_image: bool | None = None
    is_internal: bool | None = None
    size: int | None = None

    owner_type: str | None = None
    owner_guid: str | None = None
    identifier: str | None = None


class Attachment(BaseModel):
    """One attachment with its content, as returned by `GetAttachment`.

    `data` is the decoded file content. Magaya sends it Base64-encoded in a
    `<Data>` element; the parser decodes it so callers get bytes they can write
    straight to disk. It is None when the element is absent or not valid
    Base64.

    Note this record carries no owner fields — `GetAttachment` returns only the
    file itself. Keep the `AttachmentRef` you fetched it with if you need them.
    """

    name: str | None = None
    extension: str | None = None
    is_image: bool | None = None
    is_internal: bool | None = None
    size: int | None = None
    data: bytes | None = None

    @property
    def size_matches(self) -> bool | None:
        """Whether the decoded content is as long as Magaya said it would be.

        None when either side is missing. A False here means a truncated or
        mis-decoded transfer, which is worth noticing before writing the file.
        """
        if self.size is None or self.data is None:
            return None
        return len(self.data) == self.size

    def suggested_filename(self) -> str:
        """`name.extension`, falling back to the name or a generic one."""
        stem = self.name or "attachment"
        return f"{stem}.{self.extension}" if self.extension else stem


class DocumentRef(BaseModel):
    """A pointer to one Magaya-generated document on a transaction.

    These are listed inside the transaction XML (read it with the
    `AttachDocsSummary` flag), not by a call of their own. `owner_guid` and
    `identifier` are what `GetWebDocument` needs.

    `extension` is the format Magaya STORES the document in (often `dff`, its
    own layout format) — not the format you get back. `GetWebDocument` renders
    the document to PDF regardless.
    """

    name: str | None = None
    extension: str | None = None
    is_magaya_doc: bool | None = None
    is_ole_doc: bool | None = None
    owner_guid: str | None = None
    identifier: str | None = None


class WebDocument(BaseModel):
    """A transaction document rendered to PDF by `GetWebDocument`.

    `data` is the decoded PDF. `encoded_length` is what Magaya reports
    alongside it — and despite what the API reference says, it is the length of
    the Base64 STRING, not of the file. `len(data)` is the real size; the two
    differ by Base64's 4/3 expansion. `encoded_length` is kept because it is
    what the API actually returns, but reach for `len(data)`.
    """

    data: bytes | None = None
    encoded_length: int | None = None
    is_ole_doc: bool | None = None

    @property
    def size(self) -> int | None:
        """The document's real size in bytes, or None when there is no content."""
        return None if self.data is None else len(self.data)


# `GetTransaction` flag that makes Magaya list a transaction's attachments and
# documents (descriptions only, no content). Without it a transaction read
# carries no <Documents> at all.
ATTACH_DOCS_SUMMARY = 0x40
