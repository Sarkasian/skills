# Finding current facts

This skill stores principles. It does not store host-specific facts: frontmatter keys, folder paths, size limits, CLI commands, settings keys, manifest fields, telemetry event names, model rankings. Those change between releases, and a stale one produces a skill that silently does nothing.

## Before you rely on a host-specific fact
1. Fetch the page for that host and topic from the table below. If the URL has moved, search the host's documentation site for the words in the "look up" column.
2. Prefer the reference page over a blog post, and check the page's date or changelog when it has one.
3. Confirm on the machine where you can: run the host CLI's `--help`, run its validate command on the skill or plugin, or install the skill and check that the host lists it.
4. If you can neither fetch nor confirm, write the fact as unverified in your report and tell the user what to check. Do not state it from memory.

Write the looked-up fact into the skill you are authoring only when that skill needs it, and next to it the host it applies to.

## Where to look
| Topic | Start here | Look up |
|---|---|---|
| Skill format (all hosts) | https://agentskills.io/specification | allowed frontmatter keys, name and description limits, folder layout |
| Writing skills | https://agentskills.io/skill-creation/best-practices · https://agentskills.io/skill-creation/using-scripts · https://agentskills.io/skill-creation/optimizing-descriptions · https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices | current guidance on body size, scripts, descriptions |
| Claude Code | https://code.claude.com/docs/en/skills · https://code.claude.com/docs/en/features-overview · https://code.claude.com/docs/en/sub-agents · https://code.claude.com/docs/en/memory | skill folders, host-only frontmatter keys, invocation control, description budget, compaction behaviour |
| Cursor | https://cursor.com/docs/skills · https://cursor.com/docs/plugins | skill folders, host-only keys, plugin manifest, team marketplaces |
| Codex | https://developers.openai.com/codex/skills · https://developers.openai.com/codex/plugins/build | skill folders, the per-skill policy file, implicit invocation, marketplace file |
| Gemini CLI | https://geminicli.com/docs/extensions/reference/ | extension manifest, settings, skill activation and consent |
| Other hosts | the host's documentation site | search "skills", "agent skills", "plugins", "extensions" |
| Portable plugins | https://agent-plugins.org/specification | manifest schema and version |
| Native plugin manifests, settings, dependencies | https://code.claude.com/docs/en/plugins/manifest-reference · https://code.claude.com/docs/en/plugins/dependencies · the Cursor, Codex and Gemini pages above | manifest fields, user settings block, plugin-root and data-directory variables, dependency support |
| Marketplaces and org rollout | https://code.claude.com/docs/en/plugins/host-marketplace · https://code.claude.com/docs/en/plugins/org · https://support.claude.com/en/articles/13837433-manage-plugins-for-your-organization · the Cursor and Codex pages above | marketplace file, pinning, renames and removal, managed-settings keys, provisioning modes |
| Eval tooling | https://code.claude.com/docs/en/plugin-evals · https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md · https://www.promptfoo.dev/docs/guides/test-agent-skills/ · https://developers.openai.com/blog/eval-skills | whether the host has an eval runner, its flags, how to prove a skill ran |
| Telemetry | https://code.claude.com/docs/en/monitoring-usage · https://code.claude.com/docs/en/plugins/measure · https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md · each host's telemetry page | skill-activation event, attribute names, redaction and privacy defaults |
| MCP | https://modelcontextprotocol.io/seps/2640-skills-extension · https://modelcontextprotocol.io/registry/versioning | whether servers can serve skills, approval rules, registry version states |
| Security | https://github.com/cisco-ai-defense/skill-scanner/ · https://genai.owasp.org/llmrisk/llm01-prompt-injection/ | scanner options and policies, the current OWASP LLM risk list |
| Model capability | a current tool-calling leaderboard | the ranking of the target models today |

## Background reading
These explain why the principles hold. They are dated articles and papers, so they do not go stale the way host documentation does.
- Anthropic engineering: code execution with MCP https://www.anthropic.com/engineering/code-execution-with-mcp · multi-agent research https://www.anthropic.com/engineering/multi-agent-research-system · context engineering https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents · long-running harnesses https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents · evals https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents · tools https://www.anthropic.com/engineering/writing-tools-for-agents
- Multi-agent: https://cognition.com/blog/multi-agents-working · https://cognition.ai/blog/dont-build-multi-agents
- Always-on index vs skill: https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals
- Evals: https://hamel.dev/blog/posts/evals-faq/ · memory: https://docs.langchain.com/oss/python/deepagents/memory
- Papers: ACE https://arxiv.org/abs/2510.04618 · IFScale https://arxiv.org/abs/2507.11538 · Less is More https://arxiv.org/abs/2411.15399 · Skill-Inject https://arxiv.org/abs/2602.20156 · Skills in the Wild https://arxiv.org/abs/2601.10338 · Voyager https://arxiv.org/abs/2305.16291 · Reflexion https://arxiv.org/abs/2303.11366
- Skill security survey: https://snyk.io/blog/toxicskills-malicious-ai-agent-skills-clawhub/

## Where the sources disagree
MUST vs explain-why (Vercel's post reports that the wording of the instruction to use a skill changed the results; read it before relying on either form). Third person vs imperative descriptions (combine them). Scripts by default (Anthropic) vs instructions by default (Codex). Binary vs partial credit. One judge vs one per dimension. Grade outcome vs path (path also matters for stateful agents). Undertriggering (be "pushy") vs balance. Auto-updated vs human-gated memory. Tokens vs words for the 5k limit.

## Conventions, not host features
These are recommendations of this skill with no host or specification behind them: the redirect skill, file + schema contracts between skills, the layered config for plain skills, `schema_version` with a migration script, and numbered steps as a help to small models (inferred from the research, not tested directly).
