"""Structured Analyzer Tool — LLM-powered structured data extraction from any conte"""

from __future__ import annotations

import json
from typing import Any

from engine.tools.base import BaseTool, ToolResult

# Pre-built analysis prompts for each type
ANALYSIS_PROMPTS = {
    "security_audit": """Analyze this code for security vulnerabilities. For EVERY issue found, provide:
- severity: critical/high/medium/low
- type: SQL injection, XSS, hardcoded secrets, insecure crypto, broken auth, SSRF, path traversal, etc.
- location: approximate line number or function name
- description: what the vulnerability is
- fix_suggestion: how to fix it
Also check for: OWASP Top 10, hardcoded API keys/passwords, insecure HTTP, missing input validation.
Output as JSON array of findings.""",
    "code_quality": """Analyze this code for quality metrics:
- complexity_score: 0-100 (100 = very complex)
- naming_conventions: consistent/mixed/poor
- code_smells: list of detected smells (long methods, god objects, magic numbers, etc.)
- duplication_risk: low/medium/high
- maintainability_index: 0-100 (100 = highly maintainable)
- dead_code: any unused functions/variables detected
- test_friendly: how testable is this code (dependency injection, interfaces, etc.)
Output as JSON object.""",
    "architecture": """Analyze the architecture of this code:
- patterns: design patterns used (MVC, repository, factory, observer, etc.)
- layers: identified layers (presentation, business, data)
- coupling: tight/loose between components
- cohesion: high/low within modules
- api_surface: exposed interfaces/endpoints
- data_models: key data structures/entities
- external_deps: external libraries and services used
Output as JSON object.""",
    "dependencies": """Extract ALL dependencies from this code:
- imports: list of imported modules/packages
- external_libs: third-party libraries with versions if specified
- internal_deps: references to other project modules
- circular_risks: potential circular dependency patterns
- outdated_risk: any deprecated APIs or EOL libraries
Output as JSON object.""",
    "business_context": """Describe what this code DOES in business terms:
- purpose: one-sentence description of business function
- domain_entities: business objects managed (customers, orders, invoices, etc.)
- workflows: business processes implemented
- data_flows: how data moves through the system
- business_rules: embedded business logic and validations
- stakeholders: who uses or is affected by this code
- failure_impact: what happens to the business if this code fails
Output as JSON object.""",
    "api_surface": """Map the API surface of this code:
- endpoints: list of exposed routes/methods with HTTP method, path, params
- input_types: request body/query param schemas
- output_types: response schemas
- auth_required: which endpoints need authentication
- rate_limits: any rate limiting mentioned
- versioning: API version strategy
Output as JSON object.""",
    "test_coverage": """Assess test coverage quality:
- test_files: identified test files and their targets
- assertion_types: types of assertions used
- mock_patterns: mocking strategy
- edge_cases: are edge cases tested
- integration_tests: presence of integration tests
- coverage_estimate: rough percentage estimate
- gaps: areas likely missing test coverage
Output as JSON object.""",
    "documentation": """Assess documentation quality:
- docstring_coverage: percentage of functions/classes with docstrings
- readme_quality: comprehensive/basic/missing
- api_docs: present/absent
- inline_comments: too many/appropriate/too few
- type_hints: present/partial/absent
- changelog: present/absent
Output as JSON object.""",
    "compliance": """Check for compliance-related patterns:
- licenses: detected license type
- pii_handling: how personal data is processed/stored
- gdpr_patterns: consent, right-to-forget, data portability
- logging_sensitive: does code log sensitive data
- encryption: data at rest/in transit encryption
- access_control: RBAC/ABAC patterns
Output as JSON object.""",
    "performance": """Analyze for performance issues:
- n_plus_one: potential N+1 query patterns
- unbounded_loops: loops without limits
- memory_leaks: potential memory leak patterns
- resource_cleanup: proper close/dispose patterns
- caching_opportunities: where caching would help
- concurrency_safety: thread safety issues
- database_indexes: missing index hints
Output as JSON object.""",
}


class StructuredAnalyzerTool(BaseTool):
    name = "structured_analyzer"
    description = (
        "Extract structured data from ANY content using LLM analysis. "
        "Supports code (all languages), documents, and images. "
        "10+ pre-built analysis types: security_audit, code_quality, architecture, "
        "dependencies, business_context, api_surface, test_coverage, documentation, "
        "compliance, performance, custom. Outputs structured JSON."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The content to analyze (code, text, or description)",
            },
            "analysis_type": {
                "type": "string",
                "enum": [
                    "security_audit",
                    "code_quality",
                    "architecture",
                    "dependencies",
                    "business_context",
                    "api_surface",
                    "test_coverage",
                    "documentation",
                    "compliance",
                    "performance",
                    "custom",
                ],
                "description": "Type of analysis to perform",
                "default": "code_quality",
            },
            "language": {
                "type": "string",
                "description": "Programming language (auto-detected if omitted)",
            },
            "custom_prompt": {
                "type": "string",
                "description": "Custom analysis instructions (for 'custom' type)",
            },
            "output_schema": {
                "type": "object",
                "description": "Target JSON schema for output (optional, helps structure results)",
            },
        },
        "required": ["content"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        content = arguments.get("content", "")
        analysis_type = arguments.get("analysis_type", "code_quality")
        language = arguments.get("language", "")
        custom_prompt = arguments.get("custom_prompt", "")
        output_schema = arguments.get("output_schema")

        if not content:
            return ToolResult(content="Error: content is required", is_error=True)

        # Truncate very large content
        if len(content) > 100_000:
            content = content[:100_000] + "\n\n[Content truncated at 100KB]"

        # Build the analysis prompt
        if analysis_type == "custom" and custom_prompt:
            system = "You are an expert analyst. Always respond with valid JSON."
            prompt = f"{custom_prompt}\n\nContent to analyze:\n```\n{content}\n```"
        else:
            base_prompt = ANALYSIS_PROMPTS.get(
                analysis_type, ANALYSIS_PROMPTS["code_quality"]
            )
            lang_hint = f" (Language: {language})" if language else ""
            system = f"You are an expert code and document analyst{lang_hint}. Always respond with valid JSON only — no markdown, no explanations, just the JSON object."
            prompt = (
                f"{base_prompt}\n\nContent to analyze:\n```{language}\n{content}\n```"
            )

        if output_schema:
            prompt += f"\n\nTarget output schema: {json.dumps(output_schema)}"

        # Call LLM
        try:
            from engine.llm_router import LLMRouter

            router = LLMRouter()
            response = await router.complete(
                messages=[{"role": "user", "content": prompt}],
                system=system,
                model="claude-sonnet-4-5-20250929",
                temperature=0.1,  # Low temp for structured extraction
                stream=False,
            )

            # Try to parse as JSON
            text = response.content.strip()
            # Remove markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3].strip()

            try:
                parsed = json.loads(text)
                return ToolResult(
                    content=json.dumps(
                        {
                            "status": "success",
                            "analysis_type": analysis_type,
                            "language": language or "auto-detected",
                            "result": parsed,
                            "tokens": response.input_tokens + response.output_tokens,
                            "cost": response.cost,
                        },
                        default=str,
                    )
                )
            except json.JSONDecodeError:
                # Return raw text if not valid JSON
                return ToolResult(
                    content=json.dumps(
                        {
                            "status": "success",
                            "analysis_type": analysis_type,
                            "result": text,
                            "format": "text",
                            "tokens": response.input_tokens + response.output_tokens,
                        }
                    )
                )

        except Exception as e:
            return ToolResult(content=f"Analysis error: {str(e)[:500]}", is_error=True)
