"""Demo cache settings (bot-level scope rule, demo seed key) and the
compression decisions (Demo milestone, ADR-0023). All text SYNTHETIC."""

from fixtures.synthetic import contract_examples as ex

from metis_auto.contracts import (
    Component,
    ComponentName,
    ContextAction,
    IneligibleReason,
    PolicyRef,
    Request,
    RetrievedContext,
    RetrievedItem,
    Role,
    ScopeKind,
    Turn,
)
from metis_auto.domain.caching import (
    CachePolicyConfig,
    DemoSeedConfig,
    ScopeRule,
    compose_seed_key,
    seed_eligibility,
    select_scope,
)
from metis_auto.domain.context import CompressionConfig, compression

LONG = "[SYNTHETIC] " + "متن طولانی تاریخچه برای فشرده‌سازی " * 12


def req(**kw) -> Request:
    base = dict(
        message="[SYNTHETIC] question",
        history=Component.absent(),
        instructions=Component.present("[SYNTHETIC] bot instructions"),
        retrieved=Component.absent(),
        attachments=Component.absent(),
        structured_input=Component.absent(),
        session_ref="sess-a",
        user_ref="user-a",
    )
    base.update(kw)
    return Request(**base)


# --- scope ------------------------------------------------------------------


def test_serving_default_scope_is_session_and_rule_fixed():
    config = CachePolicyConfig()
    assert config.scope_rule == ScopeRule.FIXED
    assert select_scope(req(), config).kind == ScopeKind.SESSION
    assert config.demo_seed.enabled is False


def test_demo_bot_level_shares_only_when_instructions_are_present():
    config = CachePolicyConfig(scope_rule=ScopeRule.DEMO_BOT_LEVEL)
    assert select_scope(req(), config).kind == ScopeKind.GLOBAL
    no_instructions = req(instructions=Component.absent())
    assert select_scope(no_instructions, config).kind == ScopeKind.SESSION
    unknown = req(instructions=Component.unknown())
    assert select_scope(unknown, config).kind == ScopeKind.SESSION


# --- demo seed ----------------------------------------------------------------


def test_seed_is_off_by_default_and_first_turn_only():
    assert seed_eligibility(req(), CachePolicyConfig()) == IneligibleReason.DISABLED
    on = CachePolicyConfig(demo_seed=DemoSeedConfig(enabled=True))
    assert seed_eligibility(req(), on) is None
    later = req(
        history=Component.present((Turn(role=Role.USER, text="[SYNTHETIC] a"),))
    )
    assert seed_eligibility(later, on) == IneligibleReason.NOT_FIRST_TURN
    unknown = req(attachments=Component.unknown())
    assert seed_eligibility(unknown, on) == IneligibleReason.UNKNOWN_COMPONENT


def test_seed_key_is_message_only_global_and_not_a_serving_variant():
    config = CachePolicyConfig(demo_seed=DemoSeedConfig(enabled=True))
    draft = compose_seed_key(ex.request_measurements(), config)
    assert [c.component for c in draft.components] == [ComponentName.MESSAGE]
    assert draft.target_group is None
    assert draft.scope.kind == ScopeKind.GLOBAL
    assert draft.serving_allowed is False
    assert draft.variant == "demo_seed_msg_only"


# --- compression decisions ------------------------------------------------------


def test_never_instructions_by_default_and_never_the_message():
    request = req(
        message=LONG,
        instructions=Component.present(LONG),
        history=Component.present(
            (Turn(role=Role.USER, text=LONG), Turn(role=Role.ASSISTANT, text="ok"))
        ),
        retrieved=Component.present(
            RetrievedContext(items=(RetrievedItem(text=LONG), RetrievedItem(text="x")))
        ),
    )
    found = compression.targets(request, CompressionConfig(enabled=True))
    assert {(t.component, t.index) for t in found} == {
        (ComponentName.HISTORY, 0),
        (ComponentName.RETRIEVED, 0),
    }  # short texts skipped; instructions and message never
    opt_in = CompressionConfig(enabled=True, compress_instructions=True)
    assert ComponentName.INSTRUCTIONS in {
        t.component for t in compression.targets(request, opt_in)
    }


def test_apply_summary_and_mark():
    request = req(
        history=Component.present(
            (Turn(role=Role.USER, text=LONG), Turn(role=Role.ASSISTANT, text="ok"))
        )
    )
    config = CompressionConfig(enabled=True)
    results = {
        (ComponentName.HISTORY, 0): compression.Compressed("[SYNTHETIC] short", 90, 30)
    }
    sent = compression.apply(request, results)
    assert sent.history.value[0].text == "[SYNTHETIC] short"
    assert sent.history.value[1].text == "ok"
    assert sent.instructions == request.instructions
    assert sent.message == request.message

    (row,) = compression.summary(request, config, results)
    assert (row.component, row.items_compressed, row.items_skipped) == (
        ComponentName.HISTORY,
        1,
        1,
    )
    assert (row.tokens_before, row.tokens_after) == (90, 30)
    assert row.chars_after < row.chars_before

    plan = ex.context_plan()
    kept = next(
        r.component for r in plan.record.components if r.action == ContextAction.KEPT
    )
    marked = compression.mark(plan, (kept,), PolicyRef(name="fake", version="1"))
    actions = {r.component: r.action for r in marked.record.components}
    assert actions[kept] == ContextAction.COMPRESSED
    assert marked.record.strategy.name.endswith(":fake")


def test_an_empty_compression_result_keeps_the_original_text():
    request = req(history=Component.present((Turn(role=Role.USER, text=LONG),)))
    sent = compression.apply(
        request, {(ComponentName.HISTORY, 0): compression.Compressed("  ", 9, 0)}
    )
    assert sent.history.value[0].text == LONG
