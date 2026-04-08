"""
Sample inputs for each Helix agent eval.

Each entry is a dict with:
  - "inputs":   the arguments the eval target function receives
  - "metadata": human-readable label for display in LangSmith

These are intentionally minimal, realistic examples — enough to catch prompt
regressions without being expensive to run. Inputs are uploaded to a LangSmith
dataset (one dataset per agent) and reused across eval runs.

Agents covered:
  CRASH_HANDLER_EXAMPLES  — crash_handler.prompts.user()
  QA_EXAMPLES             — qa.prompts.user()
  DEV_EXAMPLES            — dev.prompts.build_suggestion()
"""

# ---------------------------------------------------------------------------
# Crash Handler eval examples
#
# Each example represents a normalised crash event. The eval target calls the
# crash_handler prompt with these inputs and checks that the LLM returns a
# valid, well-structured CrashReport JSON.
# ---------------------------------------------------------------------------

CRASH_HANDLER_EXAMPLES = [
    {
        "inputs": {
            "event_title": "AttributeError: 'NoneType' object has no attribute 'email'",
            "level": "error",
            "culprit": "api/views.py in send_welcome_email at line 42",
            "stack_trace": (
                "Traceback (most recent call last):\n"
                "  File 'api/views.py', line 42, in send_welcome_email\n"
                "    recipient = user.email\n"
                "AttributeError: 'NoneType' object has no attribute 'email'"
            ),
            "raw_summary": "Triggered by POST /api/v1/register when user object is None",
            "known_language": "python",
            "source": "sentry",
        },
        "metadata": {
            "label": "None dereference on user.email — Python/Sentry",
            "expected_severity": "high",
            "expected_error_type": "AttributeError",
        },
    },
    {
        "inputs": {
            "event_title": "KeyError: 'item_id'",
            "level": "error",
            "culprit": "services/cart.py in process_checkout at line 78",
            "stack_trace": (
                "Traceback (most recent call last):\n"
                "  File 'services/cart.py', line 78, in process_checkout\n"
                "    item = cart['item_id']\n"
                "KeyError: 'item_id'"
            ),
            "raw_summary": "Cart dict missing item_id key — affects checkout flow",
            "known_language": "python",
            "source": "rollbar",
        },
        "metadata": {
            "label": "Missing cart key — Python/Rollbar",
            "expected_severity": "high",
            "expected_error_type": "KeyError",
        },
    },
    {
        "inputs": {
            "event_title": "TypeError: Cannot read properties of undefined (reading 'id')",
            "level": "error",
            "culprit": "src/components/UserProfile.tsx line 31",
            "stack_trace": (
                "TypeError: Cannot read properties of undefined (reading 'id')\n"
                "    at UserProfile (src/components/UserProfile.tsx:31:18)\n"
                "    at renderWithHooks (react-dom.development.js:14985:18)"
            ),
            "raw_summary": "React component crashes when user prop is undefined",
            "known_language": "typescript",
            "source": "sentry",
        },
        "metadata": {
            "label": "Undefined prop access — TypeScript/React/Sentry",
            "expected_severity": "high",
            "expected_error_type": "TypeError",
        },
    },
    {
        "inputs": {
            "event_title": "ZeroDivisionError: division by zero",
            "level": "critical",
            "culprit": "billing/invoices.py in calculate_unit_price at line 115",
            "stack_trace": (
                "Traceback (most recent call last):\n"
                "  File 'billing/invoices.py', line 115, in calculate_unit_price\n"
                "    price_per_unit = total_price / quantity\n"
                "ZeroDivisionError: division by zero"
            ),
            "raw_summary": "Invoice calculation crashes when quantity is 0 — blocks billing",
            "known_language": "python",
            "source": "sentry",
        },
        "metadata": {
            "label": "Zero quantity in billing — Python/Sentry critical",
            "expected_severity": "critical",
            "expected_error_type": "ZeroDivisionError",
        },
    },
]


# ---------------------------------------------------------------------------
# QA Agent eval examples
#
# Each example is a CrashReport-level summary plus a snippet of relevant source
# code. The eval target calls the QA prompt and checks that the LLM returns a
# JSON object with file_path, test_name, and content fields.
# ---------------------------------------------------------------------------

QA_EXAMPLES = [
    {
        "inputs": {
            "error_type": "AttributeError",
            "error_message": "'NoneType' object has no attribute 'email'",
            "stack_trace": (
                "File 'api/views.py', line 42, in send_welcome_email\n"
                "    recipient = user.email\n"
                "AttributeError: 'NoneType' object has no attribute 'email'"
            ),
            "affected_component": "auth",
            "affected_endpoint": "/api/v1/register",
            "summary": (
                "send_welcome_email crashes when user is None. "
                "Affects new user registration — welcome email is not sent."
            ),
            "source_files": {
                "api/views.py": (
                    "def send_welcome_email(user):\n"
                    "    recipient = user.email\n"
                    "    send_email(recipient, subject='Welcome!')\n"
                ),
            },
            "language": "python",
            "test_format": "pytest",
        },
        "metadata": {"label": "None user — pytest test generation"},
    },
    {
        "inputs": {
            "error_type": "KeyError",
            "error_message": "'item_id'",
            "stack_trace": (
                "File 'services/cart.py', line 78, in process_checkout\n"
                "    item = cart['item_id']\n"
                "KeyError: 'item_id'"
            ),
            "affected_component": "checkout",
            "affected_endpoint": "/api/v1/checkout",
            "summary": (
                "process_checkout raises KeyError when cart dict lacks item_id. "
                "Blocks all checkout flows with incomplete cart data."
            ),
            "source_files": {
                "services/cart.py": (
                    "def process_checkout(cart):\n"
                    "    item = cart['item_id']\n"
                    "    return {'status': 'ok', 'item': item}\n"
                ),
            },
            "language": "python",
            "test_format": "pytest",
        },
        "metadata": {"label": "Missing dict key — pytest test generation"},
    },
]


# ---------------------------------------------------------------------------
# Dev Agent eval examples
#
# Each example represents a bug with full context: error details, the failing
# test written by the QA Agent, and the relevant source file(s). The eval
# target calls dev.prompts.build_suggestion() and checks that the LLM returns
# a structured fix proposal with a root cause, BEFORE/AFTER blocks, and an
# explanation — without introducing new dependencies or modifying the test.
# ---------------------------------------------------------------------------

DEV_EXAMPLES = [
    {
        "inputs": {
            "error_type": "AttributeError",
            "error_message": "'NoneType' object has no attribute 'email'",
            "summary": (
                "send_welcome_email crashes when user is None. "
                "Affects new user registration — welcome email is not sent."
            ),
            "test_file_path": "tests/test_auth.py",
            "test_name": "test_send_welcome_email_returns_none_when_user_is_none",
            "test_content": (
                "def test_send_welcome_email_returns_none_when_user_is_none():\n"
                "    result = send_welcome_email(None)\n"
                "    assert result is None\n"
            ),
            "source_files": {
                "api/views.py": (
                    "def send_welcome_email(user):\n"
                    "    recipient = user.email\n"
                    "    send_email(recipient, subject='Welcome!')\n"
                    "    return recipient\n"
                ),
            },
        },
        "metadata": {"label": "None user — fix suggestion"},
    },
    {
        "inputs": {
            "error_type": "KeyError",
            "error_message": "'item_id'",
            "summary": (
                "process_checkout raises KeyError when cart dict lacks item_id. "
                "Blocks all checkout flows with incomplete cart data."
            ),
            "test_file_path": "tests/test_cart.py",
            "test_name": "test_process_checkout_returns_none_for_missing_item_id",
            "test_content": (
                "def test_process_checkout_returns_none_for_missing_item_id():\n"
                "    result = process_checkout({})\n"
                "    assert result is None\n"
            ),
            "source_files": {
                "services/cart.py": (
                    "def process_checkout(cart):\n"
                    "    item = cart['item_id']\n"
                    "    return {'status': 'ok', 'item': item}\n"
                ),
            },
        },
        "metadata": {"label": "Missing cart key — fix suggestion"},
    },
    {
        "inputs": {
            "error_type": "ZeroDivisionError",
            "error_message": "division by zero",
            "summary": (
                "calculate_unit_price crashes when quantity is 0. "
                "Blocks invoice generation for orders with zero-quantity line items."
            ),
            "test_file_path": "tests/test_billing.py",
            "test_name": "test_calculate_unit_price_returns_none_when_quantity_is_zero",
            "test_content": (
                "def test_calculate_unit_price_returns_none_when_quantity_is_zero():\n"
                "    result = calculate_unit_price(total_price=100, quantity=0)\n"
                "    assert result is None\n"
            ),
            "source_files": {
                "billing/invoices.py": (
                    "def calculate_unit_price(total_price, quantity):\n"
                    "    price_per_unit = total_price / quantity\n"
                    "    return price_per_unit\n"
                ),
            },
        },
        "metadata": {"label": "Zero quantity division — fix suggestion"},
    },
]
