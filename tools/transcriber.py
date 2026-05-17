"""
tools/transcriber.py - Audio transcription via Groq Whisper.

Converts voice notes (.ogg from Telegram, or any audio format) to text
before passing them to Claude. Groq's Whisper is fast and free within limits.
"""
import logging

logger = logging.getLogger("beli.transcriber")

SUPPORTED_FORMATS = {"ogg", "mp3", "mp4", "mpeg", "mpga", "m4a", "wav", "webm", "flac"}
WHISPER_MODEL = "whisper-large-v3-turbo"


def transcribe_audio(api_key: str, audio_bytes: bytes, filename: str = "voice.ogg") -> str:
    """
    Transcribes an audio file using Groq Whisper.

    Args:
        api_key:     Groq API key
        audio_bytes: Raw audio file contents
        filename:    Filename with extension (used by Groq to detect format)

    Returns:
        Transcribed text, or an error string starting with "ERROR:" if it fails.
    """
    if not api_key:
        return "ERROR: GROQ_API_KEY is not set in the .env file."

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "ogg"
    if ext not in SUPPORTED_FORMATS:
        return f"ERROR: Audio format '.{ext}' is not supported. Supported: {', '.join(SUPPORTED_FORMATS)}."

    try:
        from groq import Groq
        client = Groq(api_key=api_key)

        transcription = client.audio.transcriptions.create(
            model=WHISPER_MODEL,
            file=(filename, audio_bytes),
            response_format="text",
        )
        text = transcription.strip() if isinstance(transcription, str) else transcription.text.strip()
        logger.info(f"Transcription successful ({len(text)} chars): {text[:80]}...")
        return text

    except Exception as e:
        logger.exception(f"Transcription error: {e}")
        return f"ERROR: Could not transcribe audio — {e}"
