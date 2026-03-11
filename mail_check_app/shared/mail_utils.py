from typing import List


def extract_body_text(message) -> str:
    """Extrahiert den Textinhalt (Plaintext) aus einer E-Mail-Nachricht."""
    if message.is_multipart():
        text_parts: List[str] = []
        for part in message.walk():
            if part.get_content_maintype() != "text":
                continue
            if part.get_content_disposition() == "attachment":
                continue
            try:
                text_parts.append(part.get_content())
            except Exception:
                payload = part.get_payload(decode=True) or b""
                text_parts.append(payload.decode("utf-8", errors="replace"))
        return "\n".join(text_parts)

    try:
        return message.get_content()
    except Exception:
        payload = message.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="replace")
