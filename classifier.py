"""Intent classification using LLM."""

import json
import logging
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Optional

from openai import OpenAI

from config import LLMConfig

logger = logging.getLogger("ses-daemon-bot")

# Path to the prompt template
PROMPT_TEMPLATE_PATH = Path(__file__).parent / "prompts" / "intent_classifier.txt"


class Intent(IntEnum):
    """Email intent categories."""

    SEND_INFO = 0
    CREATE_ACCOUNT = 1
    UNKNOWN = 2
    SPEAK_TO_HUMAN = 3
    EMAIL_TO_HUMAN = 4
    RESERVED = 5

    @classmethod
    def from_index(cls, index: int) -> "Intent":
        """Get Intent from array index."""
        return cls(index)

    @property
    def label(self) -> str:
        """Human-readable label."""
        labels = {
            Intent.SEND_INFO: "send_info",
            Intent.CREATE_ACCOUNT: "create_account",
            Intent.UNKNOWN: "unknown",
            Intent.SPEAK_TO_HUMAN: "speak_to_human",
            Intent.EMAIL_TO_HUMAN: "email_to_human",
            Intent.RESERVED: "reserved",
        }
        return labels[self]

    @property
    def description(self) -> str:
        """Description of what this intent means."""
        descriptions = {
            Intent.SEND_INFO: "User wants information, pricing, or documentation",
            Intent.CREATE_ACCOUNT: "User wants to sign up, register, or start trial",
            Intent.UNKNOWN: "Intent cannot be confidently determined",
            Intent.SPEAK_TO_HUMAN: "User requests phone or voice support",
            Intent.EMAIL_TO_HUMAN: "User requests human contact via email",
            Intent.RESERVED: "Reserved for future use",
        }
        return descriptions[self]


@dataclass
class ClassificationResult:
    """Result of intent classification."""

    intent: Intent
    intent_flags: list[bool]
    raw_response: str
    confidence: Optional[float] = None

    @property
    def intent_label(self) -> str:
        """Get the intent label."""
        return self.intent.label

    def to_json(self) -> str:
        """Convert to JSON string for database storage."""
        return json.dumps(self.intent_flags)


class Classifier:
    """LLM-based email intent classifier."""

    def __init__(self, config: LLMConfig):
        """Initialize the classifier.

        Args:
            config: LLM configuration with API key and model.
        """
        self.config = config
        self.model = config.model

        # Initialize OpenAI client
        client_kwargs = {"api_key": config.api_key}
        if config.base_url:
            client_kwargs["base_url"] = config.base_url
        self.client = OpenAI(**client_kwargs)

        # Load prompt template
        self.prompt_template = self._load_prompt_template()

    def _load_prompt_template(self) -> str:
        """Load the prompt template from file."""
        try:
            return PROMPT_TEMPLATE_PATH.read_text()
        except FileNotFoundError:
            logger.warning(f"Prompt template not found at {PROMPT_TEMPLATE_PATH}, using default")
            return self._default_prompt_template()

    def _default_prompt_template(self) -> str:
        """Default prompt template if file not found."""
        return """You are an intent classification engine.

You will be given an email message sent to me.
Your task is to determine the sender's primary intent.

You MUST return a single JSON array of exactly 5 items.
Each item corresponds to a fixed intent slot.

Intent slots (fixed order):
0 = send_info
1 = create_account
2 = unknown
3 = speak_to_human
4 = reserved_for_future

Rules:
- Exactly ONE item must be true.
- All other items must be false.
- If the intent is unclear or ambiguous, set index 2 (unknown) to true.
- Index 4 must always be false.
- Do NOT include any explanation or extra text.
- Output MUST be valid JSON only.

Classify based solely on the email content.

Email message:
<<<
{EMAIL_TEXT}
>>>

Return the JSON array now."""

    def classify(self, email_text: str) -> ClassificationResult:
        """Classify the intent of an email.

        Args:
            email_text: The email content to classify.

        Returns:
            ClassificationResult with the determined intent.
        """
        # Build the prompt
        prompt = self.prompt_template.replace("{EMAIL_TEXT}", email_text)

        try:
            # Call the LLM
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,  # Deterministic output
                max_tokens=50,  # Short response expected
            )

            raw_response = response.choices[0].message.content.strip()
            logger.debug(f"LLM response: {raw_response}")

            # Parse the response
            return self._parse_response(raw_response)

        except Exception as e:
            logger.error(f"Classification error: {e}")
            # Return unknown intent on error
            return ClassificationResult(
                intent=Intent.UNKNOWN,
                intent_flags=[False, False, True, False, False, False],
                raw_response=str(e),
            )

    def _parse_response(self, raw_response: str) -> ClassificationResult:
        """Parse the LLM response into a ClassificationResult.

        Args:
            raw_response: The raw LLM response string.

        Returns:
            Parsed ClassificationResult.
        """
        try:
            # Parse JSON array
            intent_flags = json.loads(raw_response)

            # Validate format
            if not isinstance(intent_flags, list) or len(intent_flags) != 6:
                raise ValueError(f"Invalid response format: expected list of 6, got {intent_flags}")

            # Convert to bools
            intent_flags = [bool(x) for x in intent_flags]

            # Find the true index
            true_count = sum(intent_flags)
            if true_count != 1:
                logger.warning(f"Expected exactly 1 true value, got {true_count}")
                # Default to unknown if invalid
                intent_flags = [False, False, True, False, False, False]

            # Get the intent
            intent_index = intent_flags.index(True)
            intent = Intent.from_index(intent_index)

            return ClassificationResult(
                intent=intent,
                intent_flags=intent_flags,
                raw_response=raw_response,
            )

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response as JSON: {e}")
            return ClassificationResult(
                intent=Intent.UNKNOWN,
                intent_flags=[False, False, True, False, False, False],
                raw_response=raw_response,
            )
        except Exception as e:
            logger.warning(f"Error parsing classification response: {e}")
            return ClassificationResult(
                intent=Intent.UNKNOWN,
                intent_flags=[False, False, True, False, False, False],
                raw_response=raw_response,
            )

    def classify_with_context(
        self, subject: str, body: str, sender: str = ""
    ) -> ClassificationResult:
        """Classify email with structured context.

        Args:
            subject: Email subject line.
            body: Email body text.
            sender: Optional sender address.

        Returns:
            ClassificationResult with the determined intent.
        """
        # Build structured email text
        parts = []
        if sender:
            parts.append(f"From: {sender}")
        if subject:
            parts.append(f"Subject: {subject}")
        if body:
            parts.append(f"\n{body}")

        email_text = "\n".join(parts)
        return self.classify(email_text)
