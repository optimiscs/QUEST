# Portable tool prompt profile

The profile is independent of the served model name and is disabled by default.
Set `QUEST_TOOL_PROMPT_PROFILE` to the absolute path of a JSON profile (for
example `inference/tool_prompts/portable_v1.json`) before starting the agent.
The profile contains `instruction` and a mapping of `examples` keyed by tool
name. Each example is a JSON tool-call object. Examples are included only when
the corresponding tool is enabled. The Python example uses the existing
`<code>` protocol.

The adapter operates on QUEST text-tool prompts containing one `<tools>` block
and the existing tool-call instruction marker. It validates each schema and
fails explicitly for incompatible prompts, so a new model may reuse the profile
when using this protocol; it does not assume native function-calling support or
claim that every model follows the format reliably. Other model-specific prompt
formats can be supplied through another adapter/profile. Without the environment
variable the legacy prompt is unchanged.
