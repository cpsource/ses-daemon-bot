"""Tests for classifier intent detection."""

import pytest
from classifier import Classifier, Intent
from config import load_config


@pytest.fixture(scope="module")
def classifier():
    """Create a classifier instance for testing."""
    config = load_config()
    return Classifier(config.llm)


class TestClassifierIntents:
    """Test that the classifier correctly identifies email intents."""

    def test_send_info_intent(self, classifier):
        """Email asking for information should return send_info intent."""
        result = classifier.classify_with_context(
            subject="Pricing question",
            body="""Hi there,

I came across your website and I'm interested in learning more about FrFlashy.
Could you please send me information about your pricing and features?

Thanks,
John""",
            sender="john@example.com",
        )

        assert result.intent == Intent.SEND_INFO, (
            f"Expected send_info, got {result.intent_label}"
        )
        assert result.intent_flags[0] is True  # send_info is index 0

    def test_speak_to_human_intent(self, classifier):
        """Email asking for help/human contact should return speak_to_human intent."""
        result = classifier.classify_with_context(
            subject="Need help urgently",
            body="""Hello,

I've been having problems with my account and I really need to speak
to someone about this. Can a real person please call me back?

My phone number is 555-1234.

Thanks,
Jane""",
            sender="jane@example.com",
        )

        assert result.intent == Intent.SPEAK_TO_HUMAN, (
            f"Expected speak_to_human, got {result.intent_label}"
        )
        assert result.intent_flags[3] is True  # speak_to_human is index 3

    def test_unknown_intent(self, classifier):
        """Email about unrelated topic should return unknown intent."""
        result = classifier.classify_with_context(
            subject="Weather question",
            body="""Hey,

What's the weather going to be like tomorrow? I'm thinking of
going to the beach.

Cheers,
Bob""",
            sender="bob@example.com",
        )

        assert result.intent == Intent.UNKNOWN, (
            f"Expected unknown, got {result.intent_label}"
        )
        assert result.intent_flags[2] is True  # unknown is index 2

    def test_create_account_intent(self, classifier):
        """Email asking to sign up should return create_account intent."""
        result = classifier.classify_with_context(
            subject="Want to sign up",
            body="""Hi,

I'd like to create an account and start using your service.
How do I register for a trial?

Best,
Alice""",
            sender="alice@example.com",
        )

        assert result.intent == Intent.CREATE_ACCOUNT, (
            f"Expected create_account, got {result.intent_label}"
        )
        assert result.intent_flags[1] is True  # create_account is index 1

    def test_email_to_human_intent(self, classifier):
        """Email explicitly asking to email a human should return email_to_human intent."""
        result = classifier.classify_with_context(
            subject="Email to a human",
            body="""Hi,

I need to discuss a billing issue with someone on your team.
Please have someone email me back.

Thanks,
Mike""",
            sender="mike@example.com",
        )

        assert result.intent == Intent.EMAIL_TO_HUMAN, (
            f"Expected email_to_human, got {result.intent_label}"
        )
        assert result.intent_flags[4] is True  # email_to_human is index 4

    def test_spam_or_auto_reply_intent(self, classifier):
        """Out-of-office or auto-reply should return spam_or_auto_reply intent."""
        result = classifier.classify_with_context(
            subject="Out of Office: Re: Your inquiry",
            body="""I am currently out of the office with limited access to email.

I will return on Monday, January 10th.

For urgent matters, please contact support@example.com.

This is an automated response.""",
            sender="vacation@example.com",
        )

        assert result.intent == Intent.SPAM_OR_AUTO_REPLY, (
            f"Expected spam_or_auto_reply, got {result.intent_label}"
        )
        assert result.intent_flags[5] is True  # spam_or_auto_reply is index 5

    def test_unsubscribe_intent(self, classifier):
        """Email asking to unsubscribe should return unsubscribe intent."""
        result = classifier.classify_with_context(
            subject="Unsubscribe request",
            body="""Hello,

Please remove me from your mailing list. I no longer wish to receive
emails from your company.

Thank you,
Sarah""",
            sender="sarah@example.com",
        )

        assert result.intent == Intent.UNSUBSCRIBE, (
            f"Expected unsubscribe, got {result.intent_label}"
        )
        assert result.intent_flags[6] is True  # unsubscribe is index 6
