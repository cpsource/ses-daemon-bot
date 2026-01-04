"""Tests for intent classifier."""

import os
import sys
from unittest.mock import MagicMock, patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from classifier import Classifier, ClassificationResult, Intent
from config import LLMConfig


def test_intent_enum():
    """Test Intent enum values and properties."""
    assert Intent.SEND_INFO == 0
    assert Intent.CREATE_ACCOUNT == 1
    assert Intent.UNKNOWN == 2
    assert Intent.SPEAK_TO_HUMAN == 3
    assert Intent.EMAIL_TO_HUMAN == 4
    assert Intent.SPAM_OR_AUTO_REPLY == 5
    assert Intent.UNSUBSCRIBE == 6
    assert Intent.RESERVED == 7

    assert Intent.SEND_INFO.label == "send_info"
    assert Intent.UNKNOWN.label == "unknown"

    assert "information" in Intent.SEND_INFO.description.lower()


def test_intent_from_index():
    """Test creating Intent from index."""
    assert Intent.from_index(0) == Intent.SEND_INFO
    assert Intent.from_index(2) == Intent.UNKNOWN
    assert Intent.from_index(3) == Intent.SPEAK_TO_HUMAN


def test_classification_result():
    """Test ClassificationResult dataclass."""
    result = ClassificationResult(
        intent=Intent.SEND_INFO,
        intent_flags=[True, False, False, False, False, False, False, False],
        raw_response="[true, false, false, false, false, false, false, false]",
    )

    assert result.intent == Intent.SEND_INFO
    assert result.intent_label == "send_info"
    assert result.to_json() == "[true, false, false, false, false, false, false, false]"


@patch("classifier.OpenAI")
def test_classifier_init(mock_openai):
    """Test Classifier initialization."""
    config = LLMConfig(
        api_key="test-key",
        model="gpt-4",
    )

    classifier = Classifier(config)

    assert classifier.model == "gpt-4"
    mock_openai.assert_called_once_with(api_key="test-key")


@patch("classifier.OpenAI")
def test_classifier_parse_valid_response(mock_openai):
    """Test parsing valid LLM response."""
    config = LLMConfig(api_key="test-key", model="gpt-4")
    classifier = Classifier(config)

    # Test send_info
    result = classifier._parse_response("[true, false, false, false, false, false, false, false]")
    assert result.intent == Intent.SEND_INFO
    assert result.intent_flags == [True, False, False, False, False, False, False, False]

    # Test create_account
    result = classifier._parse_response("[false, true, false, false, false, false, false, false]")
    assert result.intent == Intent.CREATE_ACCOUNT

    # Test speak_to_human
    result = classifier._parse_response("[false, false, false, true, false, false, false, false]")
    assert result.intent == Intent.SPEAK_TO_HUMAN

    # Test unsubscribe
    result = classifier._parse_response("[false, false, false, false, false, false, true, false]")
    assert result.intent == Intent.UNSUBSCRIBE


@patch("classifier.OpenAI")
def test_classifier_parse_invalid_json(mock_openai):
    """Test parsing invalid JSON response defaults to unknown."""
    config = LLMConfig(api_key="test-key", model="gpt-4")
    classifier = Classifier(config)

    result = classifier._parse_response("not valid json")
    assert result.intent == Intent.UNKNOWN
    assert result.intent_flags == [False, False, True, False, False, False, False, False]


@patch("classifier.OpenAI")
def test_classifier_parse_wrong_length(mock_openai):
    """Test parsing response with wrong array length."""
    config = LLMConfig(api_key="test-key", model="gpt-4")
    classifier = Classifier(config)

    result = classifier._parse_response("[true, false, false]")
    assert result.intent == Intent.UNKNOWN


@patch("classifier.OpenAI")
def test_classifier_parse_multiple_true(mock_openai):
    """Test parsing response with multiple true values defaults to unknown."""
    config = LLMConfig(api_key="test-key", model="gpt-4")
    classifier = Classifier(config)

    result = classifier._parse_response("[true, true, false, false, false, false, false, false]")
    assert result.intent == Intent.UNKNOWN


@patch("classifier.OpenAI")
def test_classify_call(mock_openai):
    """Test full classify call."""
    # Setup mock
    mock_client = MagicMock()
    mock_openai.return_value = mock_client

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "[false, true, false, false, false, false, false, false]"
    mock_client.chat.completions.create.return_value = mock_response

    config = LLMConfig(api_key="test-key", model="gpt-4")
    classifier = Classifier(config)

    result = classifier.classify("I want to sign up for your service")

    assert result.intent == Intent.CREATE_ACCOUNT
    mock_client.chat.completions.create.assert_called_once()


@patch("classifier.OpenAI")
def test_classify_with_context(mock_openai):
    """Test classify_with_context builds proper email text."""
    mock_client = MagicMock()
    mock_openai.return_value = mock_client

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "[true, false, false, false, false, false, false, false]"
    mock_client.chat.completions.create.return_value = mock_response

    config = LLMConfig(api_key="test-key", model="gpt-4")
    classifier = Classifier(config)

    result = classifier.classify_with_context(
        subject="Pricing question",
        body="How much does your service cost?",
        sender="test@example.com",
    )

    assert result.intent == Intent.SEND_INFO

    # Check that the call included all context
    call_args = mock_client.chat.completions.create.call_args
    prompt = call_args.kwargs["messages"][0]["content"]
    assert "test@example.com" in prompt
    assert "Pricing question" in prompt
    assert "How much does your service cost?" in prompt


@patch("classifier.OpenAI")
def test_classify_api_error(mock_openai):
    """Test classify handles API errors gracefully."""
    mock_client = MagicMock()
    mock_openai.return_value = mock_client
    mock_client.chat.completions.create.side_effect = Exception("API Error")

    config = LLMConfig(api_key="test-key", model="gpt-4")
    classifier = Classifier(config)

    result = classifier.classify("test email")

    # Should return unknown on error
    assert result.intent == Intent.UNKNOWN
    assert "API Error" in result.raw_response
