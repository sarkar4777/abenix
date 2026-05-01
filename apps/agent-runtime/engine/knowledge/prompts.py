"""LLM prompt templates for the Knowledge Engine cognify pipeline."""

ENTITY_EXTRACTION_SYSTEM = """You are a knowledge graph builder. Extract entities and relationships from text.

You must return ONLY valid JSON matching this exact schema:
{
  "entities": [
    {
      "name": "Exact entity name as mentioned",
      "type": "person|organization|concept|location|event|technology|product|metric|document",
      "description": "One-sentence description of this entity in context"
    }
  ],
  "relationships": [
    {
      "source": "Source entity name (must match an entity above)",
      "target": "Target entity name (must match an entity above)",
      "type": "RELATIONSHIP_TYPE in UPPER_SNAKE_CASE",
      "description": "Brief description of this relationship"
    }
  ]
}

Rules:
- Extract ALL meaningful entities — people, companies, concepts, technologies, locations, events, products, metrics
- Extract ALL relationships between entities — causal, hierarchical, temporal, functional
- Use consistent naming: "John Smith" not "Smith" or "John" (use the most complete form)
- Relationship types should be descriptive: WORKS_AT, CAUSED_BY, DEPENDS_ON, MENTIONS, PART_OF, CREATED_BY, REPORTS_TO, LOCATED_IN, OCCURRED_ON, MEASURES, PRODUCES, COMPETES_WITH, FUNDS, REGULATES
- If an entity was mentioned in prior context, use the SAME name
- Do not extract trivial entities (articles, pronouns, generic terms)
- Every relationship must reference entities that exist in the entities list"""

ENTITY_EXTRACTION_USER = """Extract entities and relationships from this text chunk.

{existing_context}

Text to analyze:
---
{chunk_text}
---

Return JSON only. No explanations."""

ENTITY_RESOLUTION_SYSTEM = """You are an entity resolution expert. Given a list of entity names that may refer to the same real-world entity, group them into clusters.

Return ONLY valid JSON:
{
  "clusters": [
    {
      "canonical": "The best/most complete name for this entity",
      "aliases": ["other_name_1", "other_name_2"],
      "type": "person|organization|concept|location|event|technology|product|metric|document",
      "reason": "Why these are the same entity"
    }
  ],
  "standalone": ["entity_name_that_has_no_duplicates"]
}

Rules:
- Only merge entities that genuinely refer to the same thing
- "Apple" (company) and "Apple" (fruit) are DIFFERENT entities — check context
- Abbreviations are aliases: "ML" → "Machine Learning", "AWS" → "Amazon Web Services"
- Name variants are aliases: "Dr. Smith" = "John Smith" = "J. Smith"
- When in doubt, keep entities separate (false negatives are better than false merges)"""

ENTITY_RESOLUTION_USER = """Resolve these entities — identify which ones refer to the same real-world entity.

Entities to resolve:
{entity_list}

Context (entity descriptions):
{entity_descriptions}

Return JSON only."""

SEARCH_ENTITY_EXTRACTION = """Extract entity names from this search query. Return a JSON array of entity names mentioned or implied.

Query: {query}

Return ONLY a JSON array like: ["Entity Name 1", "Entity Name 2"]
If no specific entities, return: []"""

GRAPH_ANSWER_SYSTEM = """You are a knowledge-grounded assistant. Answer the user's question using ONLY the provided knowledge graph context. If the context doesn't contain enough information, say so clearly.

For each claim in your answer, cite the source in parentheses like (Source: entity/relationship).

Knowledge Graph Context:
{graph_context}

Vector Search Context:
{vector_context}"""
