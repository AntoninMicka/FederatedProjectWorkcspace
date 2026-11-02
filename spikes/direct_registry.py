# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""The direct text providers known to this node, in display order."""
from spikes.claude_backend import ClaudeBinding
from spikes.gemini_backend import GeminiBinding
from spikes.xai_backend import GrokBinding


DIRECT_BINDINGS = {binding.adapter_id: binding
                   for binding in (ClaudeBinding, GeminiBinding, GrokBinding)}
DIRECT_EXECUTIONS = {'external-claude': ClaudeBinding.adapter_id,
                     'external-gemini': GeminiBinding.adapter_id,
                     'external-grok': GrokBinding.adapter_id}
