# Chatbot Authority Addon Prompt Design

## Goal

`POST /chat/prompt` must use the active chatbot assigned to the authenticated user's authority. The chat pipeline must apply that chatbot's `addon_prompt` as a permanent LLM constraint.

## Scope

In scope:
- Resolve chatbot from authenticated user role/authority.
- Require one active chatbot for that authority.
- Fail the chat request before pipeline execution if no active matching chatbot exists.
- Inject `addon_prompt` into chat pipeline LLM prompts as an additional constraint.
- Test matching, inactive/missing chatbot failures, and prompt injection.

Out of scope:
- Letting clients select a chatbot.
- Changing chatbot management rules.
- Changing RBAC route permissions.
- Adding fallback chatbot behavior.

## Architecture

The chat controller keeps using authenticated request state. The chat service resolves the active chatbot for `request.state.role` before ambiguity detection or SQL generation. Chatbot lookup belongs in repository/service code, not JWT middleware, because it is chat-domain business logic.

A repository method should return the active chatbot for one authority. The service should call it once per chat request and stop immediately if no chatbot exists. Failure should be explicit and client-visible.

## Data Flow

1. `POST /chat/prompt` receives authenticated request.
2. Controller reads `request.state.role` and passes it to chat service.
3. Chat service fetches active chatbot where `Chatbot.authority == role` and `Chatbot.is_active == True`.
4. If no chatbot exists, request fails before ambiguity detection, NL-to-SQL, SQL validation, SQL execution, graphic generation, or analysis.
5. If chatbot exists, chat service carries `chatbot.addon_prompt` through pipeline context.
6. LLM prompt builders receive the addon prompt and include it as a permanent constraint.

## Prompt Behavior

`addon_prompt` is additive. Existing prompt instructions, database schema constraints, SQL safety rules, and anti-hallucination instructions remain authoritative. The addon prompt cannot replace or weaken safety rules.

Null or empty `addon_prompt` means no extra instruction is added.

Inject addon prompt into LLM prompts where response behavior or generation may be affected:
- ambiguity detection or clarification prompt, if that prompt asks the LLM to reason about user intent or ask follow-up questions;
- NL-to-SQL prompt, as a permanent behavioral constraint while preserving schema and SQL safety requirements;
- result analysis prompt, so final answer style and constraints match the active chatbot.

## Error Handling

If no active chatbot matches authenticated authority, return a clear error before pipeline work starts. Use an HTTP error status consistent with existing service/controller patterns. Message should state that no active chatbot is configured for the user's authority.

Inactive matching chatbot counts as missing. Chatbots with other authorities must not be used.

## Testing

Add or update tests to cover:
- user role resolves matching active chatbot;
- missing matching active chatbot fails before pipeline execution;
- inactive matching chatbot fails;
- active chatbot with other authority is ignored;
- addon prompt appears in LLM prompt input;
- null addon prompt keeps current prompt behavior.

Use existing test style for async service/controller tests and mock LLM calls where current tests already mock them.
