"""EU AI Act risk classification engine.

GAP-343: EU AI Act Risk Classification Integration.
Implements EU AI Act 2024/1689 (effective August 2024).
Classifies AI models into risk tiers and enforces deployment gates
for high-risk systems requiring conformity assessments.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel

from aumos_common.observability import get_logger

logger = get_logger(__name__)


class EUAIActRiskTier(str, Enum):
    """EU AI Act risk tier classification (2024/1689).

    Values correspond to Articles 5, Annex III, and Article 50.
    """

    UNACCEPTABLE = "unacceptable"  # Prohibited — Article 5
    HIGH = "high"                  # Annex III — conformity assessment required
    LIMITED = "limited"            # Transparency obligations — Article 50
    MINIMAL = "minimal"            # No restrictions


# EU AI Act Annex III high-risk categories with keyword indicators.
# Used for keyword-based classification baseline.
# Production: enhance with LLM classification via aumos-llm-serving.
ANNEX_III_CATEGORIES: list[dict[str, Any]] = [
    {
        "category": 1,
        "description": "Biometric identification and categorization",
        "keywords": [
            "biometric", "facial recognition", "fingerprint", "iris scan",
            "voice recognition", "gait analysis",
        ],
    },
    {
        "category": 2,
        "description": "Critical infrastructure management",
        "keywords": [
            "power grid", "water treatment", "traffic management",
            "gas distribution", "rail network",
        ],
    },
    {
        "category": 3,
        "description": "Education and vocational training",
        "keywords": [
            "student assessment", "exam scoring", "educational placement",
            "academic performance", "admissions screening",
        ],
    },
    {
        "category": 4,
        "description": "Employment and worker management",
        "keywords": [
            "recruitment", "hiring", "employee monitoring", "promotion",
            "termination", "cv screening", "interview scoring",
        ],
    },
    {
        "category": 5,
        "description": "Essential services (credit, insurance, social benefits)",
        "keywords": [
            "credit scoring", "loan assessment", "insurance underwriting",
            "social benefits", "creditworthiness", "debt collection",
        ],
    },
    {
        "category": 6,
        "description": "Law enforcement",
        "keywords": [
            "criminal detection", "risk assessment law enforcement",
            "evidence assessment", "lie detection", "crime prediction",
        ],
    },
    {
        "category": 7,
        "description": "Migration and border control",
        "keywords": [
            "visa assessment", "asylum determination", "border control",
            "immigration risk", "travel document verification",
        ],
    },
    {
        "category": 8,
        "description": "Administration of justice and democratic processes",
        "keywords": [
            "judicial decision", "court ruling", "election integrity",
            "legal judgment", "sentence recommendation",
        ],
    },
]

# Article 5 prohibited AI practices
PROHIBITED_INDICATORS: list[str] = [
    "social scoring",
    "emotional manipulation",
    "subliminal manipulation",
    "real-time remote biometric identification in public spaces",
    "exploit vulnerable groups",
]

# Article 50 limited-risk transparency triggers
LIMITED_RISK_INDICATORS: list[str] = [
    "chatbot",
    "deepfake",
    "emotion recognition",
    "ai-generated content",
    "synthetic media",
]


class EUAIActClassificationResult(BaseModel):
    """Result of EU AI Act risk classification.

    Attributes:
        risk_tier: Classified risk tier.
        matching_annex_iii_categories: List of matched Annex III category numbers.
        prohibited_indicators_found: List of matched Article 5 prohibited indicators.
        requires_conformity_assessment: Whether a notified body assessment is required.
        requires_ce_marking: Whether CE marking is required before EU deployment.
        requires_registration: Whether registration in the EU database is required.
        deployment_blocked: True if deployment in the EU is blocked.
        classification_reasoning: Human-readable explanation.
    """

    risk_tier: EUAIActRiskTier
    matching_annex_iii_categories: list[int]
    prohibited_indicators_found: list[str]
    requires_conformity_assessment: bool
    requires_ce_marking: bool
    requires_registration: bool
    deployment_blocked: bool
    classification_reasoning: str


class EUAIActClassifier:
    """EU AI Act risk tier classifier enforced at model approval time.

    Evaluation order:
    1. Article 5 prohibited practices (UNACCEPTABLE — always blocked).
    2. Annex III high-risk categories (HIGH — blocked without conformity assessment).
    3. Article 50 transparency obligations (LIMITED — allowed with disclosures).
    4. Default minimal risk (MINIMAL — no restrictions).

    For production accuracy on ambiguous use cases, integrate LLM classification
    via aumos-llm-serving (keyword matching is the baseline only).
    """

    def classify(
        self,
        model_name: str,
        model_description: str,
        model_use_cases: list[str],
        provider_conformity_evidence: dict | None = None,
    ) -> EUAIActClassificationResult:
        """Classify an AI model under EU AI Act risk tiers.

        Args:
            model_name: Human-readable model name.
            model_description: Model description and stated purpose.
            model_use_cases: Intended use case strings.
            provider_conformity_evidence: Optional dict with {assessment_body,
                certificate_number, valid_until} for high-risk compliance.

        Returns:
            EUAIActClassificationResult with tier and deployment decision.
        """
        combined_text = " ".join(
            [model_name, model_description] + model_use_cases
        ).lower()

        # Step 1: Check prohibited practices (Article 5) — always blocked
        prohibited_found = [
            indicator for indicator in PROHIBITED_INDICATORS if indicator in combined_text
        ]
        if prohibited_found:
            logger.warning(
                "eu_ai_act_prohibited_detected",
                model=model_name,
                indicators=prohibited_found,
            )
            return EUAIActClassificationResult(
                risk_tier=EUAIActRiskTier.UNACCEPTABLE,
                matching_annex_iii_categories=[],
                prohibited_indicators_found=prohibited_found,
                requires_conformity_assessment=False,
                requires_ce_marking=False,
                requires_registration=False,
                deployment_blocked=True,
                classification_reasoning=(
                    f"Prohibited AI practices detected (EU AI Act Article 5): {prohibited_found}. "
                    "Deployment in the EU is permanently blocked."
                ),
            )

        # Step 2: Check Annex III high-risk categories
        matching_categories = [
            cat["category"]
            for cat in ANNEX_III_CATEGORIES
            if any(kw in combined_text for kw in cat["keywords"])
        ]

        if matching_categories:
            has_conformity = (
                provider_conformity_evidence is not None
                and "certificate_number" in provider_conformity_evidence
            )
            deployment_blocked = not has_conformity
            reasoning = (
                f"Matches Annex III categories {matching_categories}. "
                + (
                    "Conformity assessment certificate provided — deployment approved."
                    if has_conformity
                    else "Deployment BLOCKED — no conformity assessment certificate provided. "
                    "Contact a notified body for assessment before EU deployment."
                )
            )
            logger.info(
                "eu_ai_act_high_risk_classified",
                model=model_name,
                categories=matching_categories,
                has_conformity=has_conformity,
            )
            return EUAIActClassificationResult(
                risk_tier=EUAIActRiskTier.HIGH,
                matching_annex_iii_categories=matching_categories,
                prohibited_indicators_found=[],
                requires_conformity_assessment=True,
                requires_ce_marking=True,
                requires_registration=True,
                deployment_blocked=deployment_blocked,
                classification_reasoning=reasoning,
            )

        # Step 3: Article 50 limited risk (transparency obligations only)
        if any(indicator in combined_text for indicator in LIMITED_RISK_INDICATORS):
            return EUAIActClassificationResult(
                risk_tier=EUAIActRiskTier.LIMITED,
                matching_annex_iii_categories=[],
                prohibited_indicators_found=[],
                requires_conformity_assessment=False,
                requires_ce_marking=False,
                requires_registration=False,
                deployment_blocked=False,
                classification_reasoning=(
                    "Limited risk — transparency disclosure to end users required (EU AI Act Article 50). "
                    "Users must be informed they are interacting with an AI system."
                ),
            )

        # Step 4: Minimal risk — no restrictions
        return EUAIActClassificationResult(
            risk_tier=EUAIActRiskTier.MINIMAL,
            matching_annex_iii_categories=[],
            prohibited_indicators_found=[],
            requires_conformity_assessment=False,
            requires_ce_marking=False,
            requires_registration=False,
            deployment_blocked=False,
            classification_reasoning="Minimal risk — no EU AI Act restrictions apply.",
        )
