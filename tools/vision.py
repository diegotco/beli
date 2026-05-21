"""
tools/vision.py - Shared image description via Claude Vision (Haiku).

Used by both Telegram and WhatsApp to describe images / read screenshots.
"""
import base64
import logging

logger = logging.getLogger("beli.vision")

_VISION_MODEL = "claude-haiku-4-5-20251001"


async def describe_image(api_key: str, image_bytes: bytes, caption: str = "") -> str:
    """
    Describes an image using Claude Vision.

    If the image looks like a screenshot or contains text, extracts the full text.
    For photos without important text, returns a brief visual description.

    Args:
        api_key:     Anthropic API key
        image_bytes: Raw image bytes (JPEG, PNG, WebP, GIF)
        caption:     Optional caption the sender attached to the image

    Returns:
        Description / extracted text, or "[imagen — no se pudo describir]" on failure.
    """
    if not api_key:
        return "[imagen — falta clave de Anthropic]"

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
        b64 = base64.b64encode(image_bytes).decode()

        # Detect media type from magic bytes (JPEG vs PNG vs WebP)
        media_type = _detect_media_type(image_bytes)

        prompt = (
            "Analiza esta imagen. "
            "Si contiene texto (captura de pantalla, mensaje, documento, etc.), "
            "transcribe TODO el texto visible de forma exacta. "
            "Si es una foto o imagen sin texto relevante, descríbela en 1-2 oraciones. "
            "Responde solo con el contenido, sin introducción ni explicación. "
            "Responde en español."
        )
        if caption:
            prompt += f" El caption del mensaje es: '{caption}'."

        response = await client.messages.create(
            model=_VISION_MODEL,
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.warning(f"[Vision] Image description failed: {e}")
        return "[imagen — no se pudo describir]"


def _detect_media_type(image_bytes: bytes) -> str:
    """Detects image MIME type from magic bytes."""
    if image_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image_bytes[:4] in (b"RIFF", b"WEBP"):
        return "image/webp"
    if image_bytes[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"  # safe default
