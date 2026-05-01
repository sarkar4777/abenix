"""Market/news sentiment analysis — cross-industry keyword + heuristic scoring."""

from __future__ import annotations

import json
import math
import re
from typing import Any

from engine.tools.base import BaseTool, ToolResult


class SentimentAnalyzerTool(BaseTool):
    name = "sentiment_analyzer"
    description = (
        "Analyze market sentiment from text, news, or structured data. Produces "
        "sentiment scores, trend direction, volatility indicators, and confidence "
        "intervals. Use for trading signals, risk assessment, competitive "
        "intelligence, or public opinion tracking."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "texts": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "News headlines, analyst reports, social media posts, "
                    "or any text corpus to analyze"
                ),
            },
            "domain": {
                "type": "string",
                "description": (
                    "Industry context for domain-specific scoring adjustments "
                    "(e.g. 'energy', 'tech', 'healthcare', 'commodities', "
                    "'finance', 'agriculture', 'real_estate')"
                ),
            },
            "aggregation": {
                "type": "string",
                "enum": ["simple_average", "weighted_recent", "momentum"],
                "description": (
                    "How to combine individual scores: simple_average, "
                    "weighted_recent (recency-weighted), or momentum "
                    "(emphasizes direction of change). Default: weighted_recent"
                ),
            },
        },
        "required": ["texts"],
    }

    # Core keyword dictionaries
    _POSITIVE_KEYWORDS: dict[str, float] = {
        "growth": 0.6,
        "surge": 0.8,
        "rally": 0.7,
        "profit": 0.6,
        "exceed": 0.5,
        "exceeded": 0.5,
        "exceeds": 0.5,
        "strong": 0.5,
        "upgrade": 0.7,
        "bullish": 0.8,
        "outperform": 0.7,
        "beat": 0.5,
        "beats": 0.5,
        "record": 0.4,
        "recovery": 0.6,
        "optimism": 0.6,
        "optimistic": 0.6,
        "gain": 0.5,
        "gains": 0.5,
        "positive": 0.4,
        "boom": 0.7,
        "booming": 0.7,
        "expand": 0.5,
        "expansion": 0.5,
        "improve": 0.5,
        "improved": 0.5,
        "improving": 0.5,
        "innovation": 0.4,
        "breakthrough": 0.7,
        "success": 0.5,
        "successful": 0.5,
        "soar": 0.8,
        "soaring": 0.8,
        "momentum": 0.5,
        "upbeat": 0.6,
        "robust": 0.5,
        "resilient": 0.5,
        "accelerate": 0.6,
        "accelerating": 0.6,
        "dividend": 0.3,
        "buyback": 0.4,
        "approval": 0.5,
        "approved": 0.5,
        "milestone": 0.4,
        "opportunity": 0.4,
        "demand": 0.3,
        "upturn": 0.6,
        "recover": 0.5,
        "rebound": 0.6,
        "confidence": 0.4,
    }

    _NEGATIVE_KEYWORDS: dict[str, float] = {
        "decline": -0.6,
        "crash": -0.9,
        "loss": -0.6,
        "losses": -0.6,
        "risk": -0.3,
        "downgrade": -0.7,
        "bearish": -0.8,
        "warning": -0.6,
        "default": -0.8,
        "recession": -0.8,
        "inflation": -0.4,
        "debt": -0.3,
        "plunge": -0.8,
        "plunging": -0.8,
        "slump": -0.7,
        "crisis": -0.8,
        "bankruptcy": -0.9,
        "fraud": -0.9,
        "scandal": -0.8,
        "layoff": -0.6,
        "layoffs": -0.6,
        "restructuring": -0.4,
        "volatility": -0.3,
        "uncertainty": -0.4,
        "sell-off": -0.7,
        "selloff": -0.7,
        "miss": -0.5,
        "missed": -0.5,
        "shortfall": -0.6,
        "underperform": -0.6,
        "weak": -0.5,
        "weaker": -0.5,
        "weakness": -0.5,
        "fear": -0.5,
        "concern": -0.3,
        "concerns": -0.3,
        "downside": -0.5,
        "contraction": -0.6,
        "stagnation": -0.5,
        "negative": -0.4,
        "penalty": -0.5,
        "fine": -0.4,
        "lawsuit": -0.5,
        "investigation": -0.4,
        "delay": -0.4,
        "delayed": -0.4,
        "overvalued": -0.5,
        "bubble": -0.6,
        "threat": -0.4,
        "turmoil": -0.7,
        "sanctions": -0.6,
        "tariff": -0.4,
        "tariffs": -0.4,
    }

    # Domain-specific keyword adjustments
    _DOMAIN_KEYWORDS: dict[str, dict[str, float]] = {
        "energy": {
            "curtailment": -0.5,
            "baseload": 0.0,
            "renewable": 0.3,
            "solar": 0.2,
            "wind": 0.1,
            "carbon": -0.2,
            "emissions": -0.3,
            "subsidy": 0.3,
            "subsidies": 0.3,
            "grid": 0.0,
            "blackout": -0.8,
            "outage": -0.6,
            "capacity": 0.2,
            "interconnection": 0.1,
            "storage": 0.3,
            "battery": 0.3,
            "nuclear": 0.1,
            "fossil": -0.2,
            "coal": -0.3,
            "decommission": -0.3,
            "ppa": 0.2,
            "offtake": 0.3,
            "merchant": -0.1,
        },
        "tech": {
            "ai": 0.4,
            "cloud": 0.3,
            "saas": 0.3,
            "ipo": 0.3,
            "valuation": 0.0,
            "disruption": 0.3,
            "cybersecurity": -0.1,
            "breach": -0.7,
            "hack": -0.7,
            "antitrust": -0.5,
            "regulation": -0.2,
            "open-source": 0.2,
            "acquisition": 0.3,
            "patent": 0.2,
            "chip": 0.1,
            "semiconductor": 0.1,
            "shortage": -0.5,
            "launch": 0.4,
            "adoption": 0.4,
            "scalable": 0.3,
        },
        "healthcare": {
            "fda": 0.0,
            "approval": 0.7,
            "trial": 0.1,
            "clinical": 0.1,
            "phase3": 0.4,
            "phase 3": 0.4,
            "efficacy": 0.5,
            "safety": 0.1,
            "recall": -0.7,
            "side effect": -0.5,
            "adverse": -0.6,
            "patent expiry": -0.5,
            "generic": -0.3,
            "pandemic": -0.6,
            "vaccine": 0.3,
            "therapy": 0.2,
            "pipeline": 0.3,
            "orphan drug": 0.4,
            "reimbursement": 0.2,
            "cms": 0.0,
        },
        "commodities": {
            "supply": -0.1,
            "shortage": -0.5,
            "surplus": -0.3,
            "opec": 0.0,
            "production cut": 0.3,
            "inventory": -0.1,
            "stockpile": 0.0,
            "weather": -0.2,
            "harvest": 0.2,
            "drought": -0.6,
            "export ban": -0.6,
            "futures": 0.0,
            "contango": -0.2,
            "backwardation": 0.2,
            "spot price": 0.0,
        },
        "finance": {
            "rate hike": -0.4,
            "rate cut": 0.4,
            "fed": 0.0,
            "ecb": 0.0,
            "quantitative easing": 0.3,
            "tightening": -0.4,
            "yield curve": 0.0,
            "inversion": -0.6,
            "liquidity": 0.2,
            "margin call": -0.7,
            "leverage": -0.2,
            "npl": -0.5,
            "write-off": -0.6,
            "write-down": -0.5,
            "capital raise": 0.2,
            "roe": 0.1,
            "eps": 0.1,
            "guidance": 0.1,
        },
        "agriculture": {
            "yield": 0.3,
            "crop": 0.1,
            "drought": -0.7,
            "flood": -0.6,
            "pest": -0.5,
            "fertilizer": 0.0,
            "harvest": 0.3,
            "planting": 0.2,
            "usda": 0.0,
            "subsidy": 0.3,
            "export": 0.3,
            "import ban": -0.5,
            "organic": 0.2,
            "gmo": 0.0,
            "livestock": 0.1,
        },
        "real_estate": {
            "vacancy": -0.5,
            "occupancy": 0.4,
            "rent": 0.2,
            "mortgage": 0.0,
            "foreclosure": -0.7,
            "housing starts": 0.4,
            "permits": 0.3,
            "zoning": 0.0,
            "appreciation": 0.5,
            "depreciation": -0.3,
            "cap rate": 0.0,
            "reit": 0.1,
            "development": 0.3,
            "construction": 0.2,
            "inventory": -0.1,
        },
    }

    # Negation words that flip the following keyword's sentiment
    _NEGATION_WORDS = {
        "not", "no", "never", "neither", "nor", "none", "nobody",
        "nothing", "nowhere", "hardly", "barely", "scarcely", "doesn't",
        "don't", "didn't", "isn't", "wasn't", "aren't", "weren't",
        "won't", "wouldn't", "shouldn't", "couldn't", "can't", "cannot",
        "without", "despite", "lack", "fail", "failed", "fails",
    }

    # Intensifier words that amplify sentiment
    _INTENSIFIERS: dict[str, float] = {
        "very": 1.3,
        "extremely": 1.5,
        "highly": 1.3,
        "significantly": 1.3,
        "substantially": 1.3,
        "dramatically": 1.5,
        "sharply": 1.4,
        "massive": 1.4,
        "huge": 1.3,
        "unprecedented": 1.5,
        "historic": 1.3,
        "record-breaking": 1.5,
        "slightly": 0.6,
        "marginally": 0.5,
        "somewhat": 0.7,
        "modestly": 0.6,
        "mildly": 0.5,
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        texts = arguments.get("texts")
        if not texts or not isinstance(texts, list) or len(texts) == 0:
            return ToolResult(
                content="Error: 'texts' must be a non-empty array of strings",
                is_error=True,
            )

        domain = (arguments.get("domain") or "").lower().strip()
        aggregation = arguments.get("aggregation", "weighted_recent")

        if aggregation not in ("simple_average", "weighted_recent", "momentum"):
            return ToolResult(
                content=(
                    f"Unknown aggregation '{aggregation}'. "
                    "Valid: simple_average, weighted_recent, momentum"
                ),
                is_error=True,
            )

        try:
            breakdown = []
            for text in texts:
                if not isinstance(text, str) or not text.strip():
                    breakdown.append({
                        "text": str(text)[:120],
                        "score": 0.0,
                        "keywords_matched": [],
                    })
                    continue

                score, matched = self._score_text(text, domain)
                breakdown.append({
                    "text": text[:200] + ("..." if len(text) > 200 else ""),
                    "score": round(score, 3),
                    "keywords_matched": matched,
                })

            scores = [b["score"] for b in breakdown]
            overall = self._aggregate_scores(scores, aggregation)
            confidence = self._compute_confidence(breakdown)
            trend = self._determine_trend(scores, aggregation)
            volatility = self._compute_volatility(scores)
            summary = self._generate_summary(overall, trend, volatility, confidence, domain)

            output = {
                "overall_score": round(overall, 3),
                "confidence": round(confidence, 3),
                "trend": trend,
                "volatility_indicator": volatility,
                "texts_analyzed": len(texts),
                "breakdown": breakdown,
                "summary": summary,
            }
            return ToolResult(
                content=json.dumps(output, indent=2),
                metadata={"domain": domain, "aggregation": aggregation},
            )
        except Exception as e:
            return ToolResult(content=f"Sentiment analysis error: {e}", is_error=True)

    # Text scoring
    def _score_text(
        self, text: str, domain: str,
    ) -> tuple[float, list[str]]:
        lower = text.lower()
        words = re.findall(r"[a-z'-]+", lower)
        matched_keywords: list[str] = []
        raw_score = 0.0
        keyword_count = 0

        # Build combined keyword dict: base + domain overlay
        combined: dict[str, float] = {}
        combined.update(self._POSITIVE_KEYWORDS)
        combined.update(self._NEGATIVE_KEYWORDS)
        if domain in self._DOMAIN_KEYWORDS:
            combined.update(self._DOMAIN_KEYWORDS[domain])

        # Scan for multi-word keywords first (phrases)
        for keyword, value in combined.items():
            if " " in keyword or "-" in keyword:
                if keyword in lower:
                    # Check for negation before the phrase
                    idx = lower.index(keyword)
                    prefix = lower[max(0, idx - 30):idx]
                    prefix_words = re.findall(r"[a-z'-]+", prefix)
                    negated = any(w in self._NEGATION_WORDS for w in prefix_words[-3:])

                    effective = -value * 0.8 if negated else value
                    raw_score += effective
                    keyword_count += 1
                    sign = "+" if effective > 0 else ""
                    matched_keywords.append(f"{keyword} ({sign}{effective:.2f})")

        # Scan individual words
        i = 0
        while i < len(words):
            word = words[i]
            if word in combined:
                value = combined[word]

                # Check negation (up to 3 words back)
                negated = False
                for j in range(max(0, i - 3), i):
                    if words[j] in self._NEGATION_WORDS:
                        negated = True
                        break

                # Check intensifier (1 word back)
                intensifier = 1.0
                if i > 0 and words[i - 1] in self._INTENSIFIERS:
                    intensifier = self._INTENSIFIERS[words[i - 1]]

                effective = (-value * 0.8 if negated else value) * intensifier
                raw_score += effective
                keyword_count += 1
                sign = "+" if effective > 0 else ""
                matched_keywords.append(f"{word} ({sign}{effective:.2f})")

            i += 1

        # Normalize to [-1, 1] range
        if keyword_count == 0:
            return 0.0, matched_keywords

        # Average keyword contribution, then clamp
        avg = raw_score / keyword_count
        # Scale: most individual keywords are in [-0.9, 0.8] range
        # Use tanh to smoothly compress
        normalized = math.tanh(avg * 1.5)
        return normalized, matched_keywords

    # Aggregation strategies
    def _aggregate_scores(
        self, scores: list[float], method: str,
    ) -> float:
        if not scores:
            return 0.0

        if method == "simple_average":
            return sum(scores) / len(scores)

        if method == "weighted_recent":
            # More recent texts (later in array) get higher weight
            n = len(scores)
            weights = [(i + 1) for i in range(n)]
            total_weight = sum(weights)
            return sum(s * w for s, w in zip(scores, weights)) / total_weight

        if method == "momentum":
            # Emphasize the direction of change — if scores are trending
            # more positive (or negative) towards the end, amplify that
            if len(scores) < 2:
                return scores[0] if scores else 0.0

            n = len(scores)
            mid = n // 2
            first_half = scores[:mid] if mid > 0 else scores[:1]
            second_half = scores[mid:]
            avg_first = sum(first_half) / len(first_half)
            avg_second = sum(second_half) / len(second_half)
            direction = avg_second - avg_first
            # Base is weighted_recent, then add a momentum bonus
            base = self._aggregate_scores(scores, "weighted_recent")
            return max(-1.0, min(1.0, base + direction * 0.3))

        return sum(scores) / len(scores)

    # Confidence — based on keyword coverage and agreement
    def _compute_confidence(self, breakdown: list[dict[str, Any]]) -> float:
        if not breakdown:
            return 0.0

        # Factors that increase confidence:
        # 1) Number of texts analyzed (more = higher)
        # 2) Number of keywords matched per text (more = higher)
        # 3) Agreement among texts (low variance = higher)
        n = len(breakdown)
        count_factor = min(1.0, n / 20.0)  # saturates at 20 texts

        keyword_counts = [len(b.get("keywords_matched", [])) for b in breakdown]
        avg_keywords = sum(keyword_counts) / n if n > 0 else 0
        keyword_factor = min(1.0, avg_keywords / 5.0)  # saturates at 5 keywords/text

        scores = [b["score"] for b in breakdown]
        if n > 1:
            mean = sum(scores) / n
            variance = sum((s - mean) ** 2 for s in scores) / n
            std = math.sqrt(variance)
            # Lower std = more agreement = higher confidence
            agreement_factor = max(0.0, 1.0 - std)
        else:
            agreement_factor = 0.5

        # Weighted combination
        confidence = (
            0.3 * count_factor
            + 0.35 * keyword_factor
            + 0.35 * agreement_factor
        )
        return min(1.0, max(0.0, confidence))

    # Trend determination
    def _determine_trend(
        self, scores: list[float], aggregation: str,
    ) -> str:
        if not scores:
            return "neutral"

        overall = self._aggregate_scores(scores, aggregation)

        if len(scores) >= 3:
            # Look at direction: compare last third vs first third
            n = len(scores)
            third = max(1, n // 3)
            first_avg = sum(scores[:third]) / third
            last_avg = sum(scores[-third:]) / third
            delta = last_avg - first_avg

            if overall > 0.15 and delta >= -0.1:
                return "bullish"
            if overall < -0.15 and delta <= 0.1:
                return "bearish"
            if delta > 0.15:
                return "bullish"
            if delta < -0.15:
                return "bearish"
            return "neutral"

        # For very few texts, just use the overall score
        if overall > 0.15:
            return "bullish"
        if overall < -0.15:
            return "bearish"
        return "neutral"

    # Volatility indicator
    def _compute_volatility(self, scores: list[float]) -> str:
        if len(scores) < 2:
            return "low"

        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        std = math.sqrt(variance)

        if std > 0.5:
            return "high"
        if std > 0.25:
            return "medium"
        return "low"

    # Natural language summary
    def _generate_summary(
        self,
        overall: float,
        trend: str,
        volatility: str,
        confidence: float,
        domain: str,
    ) -> str:
        # Strength descriptor
        abs_score = abs(overall)
        if abs_score > 0.6:
            strength = "strongly"
        elif abs_score > 0.3:
            strength = "moderately"
        elif abs_score > 0.1:
            strength = "slightly"
        else:
            strength = ""

        direction = "positive" if overall > 0 else "negative" if overall < 0 else "neutral"
        domain_label = f" {domain}" if domain else ""

        if strength:
            sentiment_desc = f"{strength} {direction}"
        else:
            sentiment_desc = "neutral"

        conf_desc = (
            "high" if confidence > 0.7
            else "moderate" if confidence > 0.4
            else "low"
        )

        parts = [
            f"Overall{domain_label} sentiment is {sentiment_desc} "
            f"(score: {overall:+.2f}, trend: {trend}).",
            f"Confidence is {conf_desc} ({confidence:.0%}) "
            f"with {volatility} sentiment volatility across the analyzed texts.",
        ]

        if trend == "bullish" and overall > 0:
            parts.append(
                "The positive trend suggests favorable conditions; "
                "recent signals reinforce the bullish outlook."
            )
        elif trend == "bearish" and overall < 0:
            parts.append(
                "The negative trend indicates deteriorating conditions; "
                "recent signals reinforce the bearish outlook."
            )
        elif trend == "bullish" and overall <= 0:
            parts.append(
                "Despite mixed or negative overall sentiment, "
                "recent signals show an improving trajectory."
            )
        elif trend == "bearish" and overall >= 0:
            parts.append(
                "Despite positive overall sentiment, recent signals "
                "suggest momentum may be shifting downward."
            )

        if volatility == "high":
            parts.append(
                "High sentiment volatility indicates significant disagreement "
                "or mixed signals across sources — exercise caution."
            )

        return " ".join(parts)
