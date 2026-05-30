import hashlib
import json
import logging
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = REPO_ROOT / ".tmp"
OUTBOX_PATH = TMP_DIR / "notification_outbox.jsonl"
DEAD_LETTER_PATH = TMP_DIR / "notification_dead_letters.jsonl"
SENT_LEDGER_PATH = TMP_DIR / "notification_sent_ledger.jsonl"
EVENT_OUTBOX_PATH = TMP_DIR / "notification_events.jsonl"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_tmp_dir() -> None:
    TMP_DIR.mkdir(parents=True, exist_ok=True)


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_hexdigest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def structured_log(level: int, event: str, **fields: Any) -> None:
    payload = {"event": event, "timestamp": utc_now_iso(), **fields}
    LOGGER.log(level, canonical_json(payload))


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    ensure_tmp_dir()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_json(record) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def is_valid_email(value: str) -> bool:
    return bool(value) and "@" in parseaddr(value)[1]


def build_success(message: str, data: Any = None, status_code: int = 200) -> dict[str, Any]:
    return {
        "success": True,
        "message": message,
        "data": data,
        "errors": None,
        "status_code": status_code,
    }


def build_failure(
    message: str,
    errors: Any = None,
    data: Any = None,
    status_code: int = 400,
) -> dict[str, Any]:
    return {
        "success": False,
        "message": message,
        "data": data,
        "errors": errors or {},
        "status_code": status_code,
    }


def dedupe_key_for_notification(payload: dict[str, Any]) -> str:
    stable_payload = {
        "recipient_email": payload.get("recipient_email"),
        "subject": payload.get("subject"),
        "text_body": payload.get("text_body"),
        "html_body": payload.get("html_body"),
        "notification_type": payload.get("notification_type"),
        "correlation_id": payload.get("correlation_id"),
    }
    return sha256_hexdigest(canonical_json(stable_payload))


def notification_outbox_record(payload: dict[str, Any], queue_id: str) -> dict[str, Any]:
    return {
        "queue_id": queue_id,
        "queued_at": utc_now_iso(),
        "payload": payload,
    }


def dead_letter_record(payload: dict[str, Any], reason: str, attempt: int = 0) -> dict[str, Any]:
    return {
        "dead_letter_id": sha256_hexdigest(
            canonical_json(
                {
                    "payload": payload,
                    "reason": reason,
                    "attempt": attempt,
                    "at": utc_now_iso(),
                }
            )
        ),
        "dead_lettered_at": utc_now_iso(),
        "reason": reason,
        "attempt": attempt,
        "payload": payload,
    }


def event_outbox_record(
    event_type: str,
    payload: dict[str, Any],
    correlation_id: str | None = None,
) -> dict[str, Any]:
    return {
        "event_id": sha256_hexdigest(
            canonical_json(
                {
                    "event_type": event_type,
                    "payload": payload,
                    "correlation_id": correlation_id,
                }
            )
        ),
        "event_type": event_type,
        "correlation_id": correlation_id,
        "created_at": utc_now_iso(),
        "payload": payload,
    }


def send_email_payload(payload: dict[str, Any]) -> dict[str, Any]:
    from django.conf import settings
    from django.core.mail import send_mail

    correlation_id = payload.get("correlation_id") or payload.get("notification_id")

    if not is_valid_email(payload.get("recipient_email", "")):
        failure = build_failure(
            message="Invalid recipient email",
            errors={"recipient_email": "invalid-email"},
            data={
                "notification_id": payload.get("notification_id"),
                "correlation_id": correlation_id,
                "retryable": False,
            },
            status_code=400,
        )
        append_jsonl(
            DEAD_LETTER_PATH,
            dead_letter_record(payload, "invalid-recipient", attempt=payload.get("attempt", 0)),
        )
        structured_log(
            logging.ERROR,
            "notification.send.invalid_recipient",
            notification_id=payload.get("notification_id"),
            correlation_id=correlation_id,
            recipient_email=payload.get("recipient_email"),
        )
        return failure

    notification_id = payload.get("notification_id") or dedupe_key_for_notification(payload)
    dedupe_key = payload.get("dedupe_key") or notification_id
    ledger_records = read_jsonl(SENT_LEDGER_PATH)
    if any(record.get("dedupe_key") == dedupe_key for record in ledger_records):
        structured_log(
            logging.INFO,
            "notification.send.duplicate_skipped",
            notification_id=notification_id,
            correlation_id=correlation_id,
            dedupe_key=dedupe_key,
            recipient_email=payload.get("recipient_email"),
        )
        return build_success(
            message="Notification already sent",
            data={
                "notification_id": notification_id,
                "dedupe_key": dedupe_key,
                "recipient_email": payload.get("recipient_email"),
                "correlation_id": correlation_id,
                "duplicate": True,
                "retryable": False,
                "dead_lettered": False,
            },
        )

    try:
        structured_log(
            logging.INFO,
            "notification.send.start",
            notification_id=notification_id,
            correlation_id=correlation_id,
            recipient_email=payload.get("recipient_email"),
            notification_type=payload.get("notification_type"),
        )
        send_mail(
            subject=payload["subject"],
            message=payload["text_body"],
            from_email=payload.get("from_email") or settings.DEFAULT_FROM_EMAIL,
            recipient_list=[payload["recipient_email"]],
            fail_silently=False,
            html_message=payload.get("html_body"),
        )
        ledger_entry = {
            "notification_id": notification_id,
            "dedupe_key": dedupe_key,
            "recipient_email": payload.get("recipient_email"),
            "notification_type": payload.get("notification_type"),
            "sent_at": utc_now_iso(),
        }
        append_jsonl(SENT_LEDGER_PATH, ledger_entry)
        structured_log(logging.INFO, "notification.send.success", **ledger_entry)
        return build_success(
            message="Notification sent",
            data={
                "notification_id": notification_id,
                "dedupe_key": dedupe_key,
                "recipient_email": payload.get("recipient_email"),
                "correlation_id": correlation_id,
                "duplicate": False,
                "retryable": False,
                "dead_lettered": False,
                "provider": "smtp",
            },
        )
    except Exception as exc:
        retryable = exc.__class__.__name__ in {
            "SMTPException",
            "ConnectionError",
            "TimeoutError",
            "SMTPServerDisconnected",
        }
        dead_letter = dead_letter_record(payload, exc.__class__.__name__, attempt=payload.get("attempt", 0))
        append_jsonl(DEAD_LETTER_PATH, dead_letter)
        structured_log(
            logging.ERROR,
            "notification.send.failed",
            notification_id=notification_id,
            correlation_id=correlation_id,
            recipient_email=payload.get("recipient_email"),
            error_type=exc.__class__.__name__,
            retryable=retryable,
        )
        return build_failure(
            message="Notification delivery failed",
            errors={"error_type": exc.__class__.__name__, "retryable": retryable},
            data={
                "notification_id": notification_id,
                "dedupe_key": dedupe_key,
                "recipient_email": payload.get("recipient_email"),
                "correlation_id": correlation_id,
                "retryable": retryable,
                "dead_lettered": True,
                "dead_letter_path": str(DEAD_LETTER_PATH),
            },
            status_code=503,
        )


def render_notification_payload(template_name: str, context: dict[str, Any]) -> dict[str, Any]:
    recipient_email = context.get("recipient_email") or context.get("email")
    if not recipient_email:
        raise ValueError("recipient_email is required")

    if template_name == "credentials_email":
        login_url = context["login_url"].rstrip("/")
        subject = "Welcome to Leapfrog Connect - Your Account Credentials"
        text_body = (
            "Welcome to Leapfrog Connect!\n\n"
            f"Organization Email (Login): {context['user_email']}\n"
            f"Temporary Password: {context['temp_password']}\n"
            f"Role: {context.get('role_label', '')}\n\n"
            "You must change your password on first login.\n"
            f"Login URL: {login_url}\n"
        )
        html_body = (
            "<html><body style='font-family: Arial, sans-serif; padding: 20px;'>"
            "<h2>Welcome to Leapfrog Connect</h2>"
            f"<p>Organization Email (Login): {context['user_email']}</p>"
            f"<p><strong>Temporary Password:</strong> {context['temp_password']}</p>"
            f"<p>Role: {context.get('role_label', '')}</p>"
            f"<p>Login URL: {login_url}</p>"
            "</body></html>"
        )
    elif template_name == "password_reset":
        reset_url = context["reset_url"].rstrip("/")
        subject = "Password Reset Request - Leapfrog Connect"
        text_body = f"Reset your password: {reset_url}"
        html_body = (
            "<html><body style='font-family: Arial, sans-serif; padding: 20px;'>"
            "<h2>Password Reset Request</h2>"
            f"<p>Organization Email: {context['user_email']}</p>"
            f"<p>Role: {context.get('role_label', '')}</p>"
            f"<p><a href='{reset_url}'>Reset Password</a></p>"
            "<p>This link expires in 24 hours.</p>"
            "</body></html>"
        )
    elif template_name == "course_notification":
        subject = context["subject"]
        text_body = context["message"]
        html_body = context.get("html_body")
    else:
        raise ValueError(f"Unsupported notification template: {template_name}")

    payload = {
        "notification_id": context.get("notification_id")
        or sha256_hexdigest(
            canonical_json(
                {
                    "template_name": template_name,
                    "recipient_email": recipient_email,
                    "context": context,
                }
            )
        ),
        "dedupe_key": context.get("dedupe_key")
        or sha256_hexdigest(
            canonical_json(
                {
                    "template_name": template_name,
                    "recipient_email": recipient_email,
                    "subject": subject,
                    "text_body": text_body,
                }
            )
        ),
        "notification_type": template_name,
        "recipient_email": recipient_email,
        "subject": subject,
        "text_body": text_body,
        "html_body": html_body,
        "from_email": context.get("from_email"),
        "correlation_id": context.get("correlation_id"),
        "metadata": context.get("metadata") or {},
    }
    return payload
