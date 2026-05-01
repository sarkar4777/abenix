"""Text analysis: entity extraction, comparison, section parsing, keyword extraction."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Any

from engine.tools.base import BaseTool, ToolResult

STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "i",
        "you",
        "he",
        "she",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
        "his",
        "our",
        "their",
        "not",
        "no",
        "nor",
        "if",
        "then",
        "else",
        "when",
        "where",
        "how",
        "what",
        "which",
        "who",
        "whom",
        "all",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "than",
        "too",
        "very",
        "just",
        "about",
        "above",
        "after",
        "again",
        "also",
        "any",
        "because",
        "before",
        "between",
        "during",
        "into",
        "only",
        "over",
        "same",
        "so",
        "through",
        "under",
        "until",
        "up",
        "while",
        "as",
    }
)


class TextAnalyzerTool(BaseTool):
    name = "text_analyzer"
    description = (
        "Analyze text content: extract keywords and phrases, compute readability metrics, "
        "compare two texts for similarity, extract named entities (names, organizations, "
        "locations), parse document sections, compute word/sentence statistics, and "
        "generate text summaries with key points."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Primary text to analyze",
            },
            "second_text": {
                "type": "string",
                "description": "Second text for comparison operations",
            },
            "operation": {
                "type": "string",
                "enum": [
                    "keywords",
                    "statistics",
                    "readability",
                    "compare",
                    "entities",
                    "sections",
                    "ngrams",
                    "sentiment_words",
                ],
                "description": "Analysis operation to perform",
                "default": "statistics",
            },
            "top_n": {
                "type": "integer",
                "description": "Number of top results to return",
                "default": 20,
            },
        },
        "required": ["text"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        text = arguments.get("text", "")
        operation = arguments.get("operation", "statistics")

        # Coerce non-string text (from upstream node outputs) to a string
        if not isinstance(text, str):
            import json as _j

            text = _j.dumps(text, default=str)

        if not text.strip():
            return ToolResult(content="Error: text is required", is_error=True)

        ops = {
            "keywords": self._keywords,
            "statistics": self._statistics,
            "readability": self._readability,
            "compare": self._compare,
            "entities": self._entities,
            "sections": self._sections,
            "ngrams": self._ngrams,
            "sentiment_words": self._sentiment_words,
            "sentiment": self._sentiment_words,  # alias
        }

        fn = ops.get(operation)
        if not fn:
            return ToolResult(content=f"Unknown operation: {operation}", is_error=True)

        try:
            result = fn(text, arguments)
            output = json.dumps(result, indent=2, default=str)
            return ToolResult(content=output, metadata={"operation": operation})
        except Exception as e:
            return ToolResult(content=f"Analysis error: {e}", is_error=True)

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"\b[a-zA-Z]+(?:'[a-zA-Z]+)?\b", text.lower())

    def _sentences(self, text: str) -> list[str]:
        return [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]

    def _keywords(self, text: str, args: dict[str, Any]) -> dict[str, Any]:
        top_n = args.get("top_n", 20)
        words = self._tokenize(text)
        filtered = [w for w in words if w not in STOP_WORDS and len(w) > 2]
        counter = Counter(filtered)

        total = len(filtered)
        keywords = [
            {"word": word, "count": count, "frequency": round(count / total * 100, 2)}
            for word, count in counter.most_common(top_n)
        ]

        bigrams = []
        for i in range(len(filtered) - 1):
            bigrams.append(f"{filtered[i]} {filtered[i+1]}")
        bigram_counter = Counter(bigrams)
        top_phrases = [
            {"phrase": phrase, "count": count}
            for phrase, count in bigram_counter.most_common(top_n // 2)
        ]

        return {
            "keywords": keywords,
            "key_phrases": top_phrases,
            "total_meaningful_words": total,
        }

    def _statistics(self, text: str, args: dict[str, Any]) -> dict[str, Any]:
        words = self._tokenize(text)
        sentences = self._sentences(text)
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        word_lengths = [len(w) for w in words]
        sentence_lengths = [len(self._tokenize(s)) for s in sentences]

        unique_words = set(words)
        return {
            "character_count": len(text),
            "word_count": len(words),
            "sentence_count": len(sentences),
            "paragraph_count": len(paragraphs),
            "unique_words": len(unique_words),
            "vocabulary_richness": (
                round(len(unique_words) / len(words), 4) if words else 0
            ),
            "avg_word_length": (
                round(sum(word_lengths) / len(word_lengths), 1) if word_lengths else 0
            ),
            "avg_sentence_length": (
                round(sum(sentence_lengths) / len(sentence_lengths), 1)
                if sentence_lengths
                else 0
            ),
            "longest_sentence_words": max(sentence_lengths) if sentence_lengths else 0,
            "shortest_sentence_words": min(sentence_lengths) if sentence_lengths else 0,
        }

    def _readability(self, text: str, args: dict[str, Any]) -> dict[str, Any]:
        words = self._tokenize(text)
        sentences = self._sentences(text)

        if not words or not sentences:
            return {"error": "Text too short for readability analysis"}

        word_count = len(words)
        sentence_count = len(sentences)

        syllable_count = sum(self._count_syllables(w) for w in words)
        complex_words = sum(1 for w in words if self._count_syllables(w) >= 3)

        asl = word_count / sentence_count
        asw = syllable_count / word_count

        flesch_reading = 206.835 - 1.015 * asl - 84.6 * asw
        flesch_kincaid = 0.39 * asl + 11.8 * asw - 15.59
        gunning_fog = 0.4 * (asl + 100 * complex_words / word_count)
        coleman_liau = (
            0.0588 * (len("".join(words)) / word_count * 100)
            - 0.296 * (sentence_count / word_count * 100)
            - 15.8
        )

        if flesch_reading >= 90:
            level = "Very Easy (5th grade)"
        elif flesch_reading >= 80:
            level = "Easy (6th grade)"
        elif flesch_reading >= 70:
            level = "Fairly Easy (7th grade)"
        elif flesch_reading >= 60:
            level = "Standard (8th-9th grade)"
        elif flesch_reading >= 50:
            level = "Fairly Difficult (10th-12th grade)"
        elif flesch_reading >= 30:
            level = "Difficult (College)"
        else:
            level = "Very Difficult (Graduate)"

        return {
            "flesch_reading_ease": round(flesch_reading, 1),
            "flesch_kincaid_grade": round(flesch_kincaid, 1),
            "gunning_fog_index": round(gunning_fog, 1),
            "coleman_liau_index": round(coleman_liau, 1),
            "reading_level": level,
            "avg_syllables_per_word": round(asw, 2),
            "complex_word_pct": round(complex_words / word_count * 100, 1),
            "estimated_reading_time_min": round(word_count / 250, 1),
        }

    def _count_syllables(self, word: str) -> int:
        word = word.lower()
        if len(word) <= 3:
            return 1
        count = 0
        vowels = "aeiouy"
        prev_vowel = False
        for char in word:
            is_vowel = char in vowels
            if is_vowel and not prev_vowel:
                count += 1
            prev_vowel = is_vowel
        if word.endswith("e") and count > 1:
            count -= 1
        return max(1, count)

    def _compare(self, text: str, args: dict[str, Any]) -> dict[str, Any]:
        second_text = args.get("second_text", "")
        if not second_text:
            return {"error": "second_text is required for comparison"}

        words1 = set(self._tokenize(text))
        words2 = set(self._tokenize(second_text))

        common = words1 & words2
        only_first = words1 - words2
        only_second = words2 - words1

        jaccard = len(common) / len(words1 | words2) if (words1 | words2) else 0

        counter1 = Counter(self._tokenize(text))
        counter2 = Counter(self._tokenize(second_text))
        all_words = set(counter1.keys()) | set(counter2.keys())
        dot = sum(counter1.get(w, 0) * counter2.get(w, 0) for w in all_words)
        mag1 = math.sqrt(sum(v**2 for v in counter1.values()))
        mag2 = math.sqrt(sum(v**2 for v in counter2.values()))
        cosine = dot / (mag1 * mag2) if mag1 and mag2 else 0

        stats1 = self._statistics(text, {})
        stats2 = self._statistics(second_text, {})

        return {
            "jaccard_similarity": round(jaccard, 4),
            "cosine_similarity": round(cosine, 4),
            "common_words": len(common),
            "unique_to_first": len(only_first),
            "unique_to_second": len(only_second),
            "top_common": sorted(
                common,
                key=lambda w: counter1.get(w, 0) + counter2.get(w, 0),
                reverse=True,
            )[:20],
            "top_unique_first": list(only_first)[:10],
            "top_unique_second": list(only_second)[:10],
            "length_comparison": {
                "text1_words": stats1["word_count"],
                "text2_words": stats2["word_count"],
                "text1_sentences": stats1["sentence_count"],
                "text2_sentences": stats2["sentence_count"],
            },
        }

    def _entities(self, text: str, args: dict[str, Any]) -> dict[str, Any]:
        entities: dict[str, list[str]] = {
            "potential_names": [],
            "organizations": [],
            "locations": [],
            "dates": [],
            "money": [],
            "percentages": [],
        }

        name_pattern = r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b"
        names = re.findall(name_pattern, text)
        entities["potential_names"] = list(set(names))[:20]

        org_pattern = r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Inc|LLC|Ltd|Corp|Corporation|Company|Co|Group|Partners|Bank|University|Institute)\.?)"
        entities["organizations"] = list(set(re.findall(org_pattern, text)))[:20]

        location_indicators = (
            r"(?:in|at|from|near|to)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)"
        )
        entities["locations"] = list(set(re.findall(location_indicators, text)))[:20]

        date_pattern = r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})\b"
        entities["dates"] = list(set(re.findall(date_pattern, text, re.IGNORECASE)))[
            :20
        ]

        money_pattern = r"\$[\d,]+(?:\.\d{2})?"
        entities["money"] = list(set(re.findall(money_pattern, text)))[:20]

        pct_pattern = r"\d+(?:\.\d+)?%"
        entities["percentages"] = list(set(re.findall(pct_pattern, text)))[:20]

        return entities

    def _sections(self, text: str, args: dict[str, Any]) -> dict[str, Any]:
        sections = []
        lines = text.split("\n")
        current: dict[str, Any] | None = None

        heading_patterns = [
            r"^(#{1,6})\s+(.+)$",
            r"^(ARTICLE|SECTION|CHAPTER|PART)\s+(\d+[\d.]*)[:\s]*(.*)$",
            r"^(\d+\.(?:\d+\.)*)\s+([A-Z].{3,})$",
            r"^([A-Z][A-Z\s]{5,})$",
        ]

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue

            is_heading = False
            for pattern in heading_patterns:
                if re.match(pattern, stripped):
                    is_heading = True
                    break

            if is_heading:
                if current:
                    current["end_line"] = i
                    current["word_count"] = len(
                        self._tokenize(current.get("_content", ""))
                    )
                    del current["_content"]
                    sections.append(current)

                current = {
                    "heading": stripped,
                    "start_line": i + 1,
                    "end_line": 0,
                    "_content": "",
                }
            elif current:
                current["_content"] += " " + stripped

        if current:
            current["end_line"] = len(lines)
            current["word_count"] = len(self._tokenize(current.get("_content", "")))
            del current["_content"]
            sections.append(current)

        return {"section_count": len(sections), "sections": sections}

    def _ngrams(self, text: str, args: dict[str, Any]) -> dict[str, Any]:
        top_n = args.get("top_n", 20)
        words = [w for w in self._tokenize(text) if w not in STOP_WORDS and len(w) > 2]

        result: dict[str, list[dict[str, Any]]] = {}
        for n in [2, 3]:
            grams = []
            for i in range(len(words) - n + 1):
                grams.append(" ".join(words[i : i + n]))
            counter = Counter(grams)
            result[f"{n}-grams"] = [
                {"phrase": phrase, "count": count}
                for phrase, count in counter.most_common(top_n)
                if count > 1
            ]

        return result

    def _sentiment_words(self, text: str, args: dict[str, Any]) -> dict[str, Any]:
        positive = {
            "good",
            "great",
            "excellent",
            "positive",
            "strong",
            "favorable",
            "advantage",
            "benefit",
            "opportunity",
            "growth",
            "profit",
            "gain",
            "success",
            "improve",
            "increase",
            "efficient",
            "effective",
            "innovative",
            "reliable",
            "secure",
            "stable",
            "superior",
            "optimal",
            "robust",
            "significant",
            "substantial",
            "promising",
        }
        negative = {
            "bad",
            "poor",
            "negative",
            "weak",
            "unfavorable",
            "risk",
            "loss",
            "decline",
            "decrease",
            "failure",
            "problem",
            "issue",
            "concern",
            "threat",
            "danger",
            "liability",
            "penalty",
            "deteriorate",
            "volatile",
            "uncertain",
            "default",
            "breach",
            "terminate",
            "damage",
            "adverse",
            "limited",
            "insufficient",
        }

        words = self._tokenize(text)
        pos_found = [w for w in words if w in positive]
        neg_found = [w for w in words if w in negative]

        pos_count = len(pos_found)
        neg_count = len(neg_found)
        total = pos_count + neg_count

        if total == 0:
            tone = "neutral"
            score = 0.0
        else:
            score = (pos_count - neg_count) / total
            if score > 0.2:
                tone = "positive"
            elif score < -0.2:
                tone = "negative"
            else:
                tone = "mixed"

        return {
            "tone": tone,
            "score": round(score, 3),
            "positive_count": pos_count,
            "negative_count": neg_count,
            "positive_words": Counter(pos_found).most_common(10),
            "negative_words": Counter(neg_found).most_common(10),
        }
