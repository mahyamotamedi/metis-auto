"""Within-message chunk dedup (sprint winner S-6, ADR-XXXX (demo-sprint-winners);
semantics of exp-ctx-001, re-implemented in the domain). Pure. All text is
SYNTHETIC; Persian and mixed-script chunks are engineered."""

from metis_auto.contracts import (
    Component,
    Request,
    RetrievedContext,
    RetrievedItem,
    Role,
    Turn,
)
from metis_auto.domain.context import DedupConfig, deduplicate

A = "[SYNTHETIC] ارسال رایگان برای سفارش‌های بالای یک میلیون تومان است."
B = "[SYNTHETIC] Returns are accepted within 7 days."
C = "[SYNTHETIC] مهلت بازگشت 7 روز / return window 7 days."


def req(*texts: str, **kw) -> Request:
    items = tuple(RetrievedItem(text=t) for t in texts)
    base = dict(
        message="[SYNTHETIC] question",
        history=Component.present(
            (
                Turn(role=Role.USER, text=A),
                Turn(role=Role.ASSISTANT, text=A),
            )
        ),
        instructions=Component.present(A),
        retrieved=Component.present(RetrievedContext(items=items))
        if items
        else Component.absent(),
        attachments=Component.absent(),
        structured_input=Component.absent(),
    )
    base.update(kw)
    return Request(**base)


def texts(request: Request) -> list[str]:
    return [i.text for i in request.retrieved.value.items]


def test_config_is_off_by_default():
    assert DedupConfig().enabled is False


def test_exact_duplicates_are_removed_keeping_the_first_in_order():
    result = deduplicate(req(A, B, A, C, B, A))
    assert texts(result.request) == [A, B, C]
    assert result.items_total == 6
    assert result.items_removed == 3
    assert result.chars_removed == len(A) * 2 + len(B)


def test_nothing_changes_without_duplicates():
    original = req(A, B, C)
    result = deduplicate(original)
    assert result.request is original
    assert (result.items_removed, result.chars_removed) == (0, 0)


def test_near_duplicates_are_kept():
    # Only exact text counts: a different space, case or ZWNJ is another chunk.
    variants = [B, B + " ", B.upper(), A.replace("‌", "")]
    result = deduplicate(req(*variants))
    assert texts(result.request) == variants
    assert result.items_removed == 0


def test_instructions_history_and_message_are_untouched():
    original = req(A, A, B)
    result = deduplicate(original)
    assert result.request.instructions == original.instructions
    assert result.request.history == original.history  # history repeats A, kept
    assert result.request.message == original.message


def test_it_is_idempotent():
    once = deduplicate(req(A, B, A, B, C)).request
    twice = deduplicate(once)
    assert twice.request == once
    assert twice.items_removed == 0


def test_persian_and_mixed_script_chunks():
    result = deduplicate(req(C, A, C, C, A))
    assert texts(result.request) == [C, A]
    assert result.items_removed == 3


def test_empty_and_single_chunk_contexts():
    none = req()
    assert deduplicate(none).request is none
    assert deduplicate(none).items_total == 0
    single = req(A)
    assert deduplicate(single).request is single
    assert deduplicate(single).items_total == 1


def test_blank_chunks_are_never_duplicates():
    # A row without text is not an exact duplicate (exp-ctx-001).
    blank = req("", "", " ", " ")
    assert deduplicate(blank).items_removed == 0


def test_one_document_ref_with_two_texts_is_not_a_duplicate_and_two_refs_one_text_is():
    items = (
        RetrievedItem(text=A, document_ref="doc-1"),
        RetrievedItem(text=B, document_ref="doc-1"),
        RetrievedItem(text=A, document_ref="doc-2"),
    )
    request = req(A).model_copy(
        update={"retrieved": Component.present(RetrievedContext(items=items))}
    )
    result = deduplicate(request)
    assert [i.document_ref for i in result.request.retrieved.value.items] == [
        "doc-1",
        "doc-1",
    ]


def test_an_unknown_or_absent_retrieved_component_is_carried_unchanged():
    unknown = req().model_copy(update={"retrieved": Component.unknown()})
    assert deduplicate(unknown).request is unknown
