"""
tools/transcriber.py - Audio transcription via Groq Whisper.

Converts voice notes (.ogg from Telegram, or any audio format) to text
before passing them to Claude. Groq's Whisper is fast and free within limits.
"""
import logging

logger = logging.getLogger("beli.transcriber")

SUPPORTED_FORMATS = {"ogg", "mp3", "mp4", "mpeg", "mpga", "m4a", "wav", "webm", "flac"}
WHISPER_MODEL = "whisper-large-v3-turbo"

# If the average no_speech_prob across all segments exceeds this threshold,
# the audio is considered silence/noise and we refuse to return a transcription
# (Whisper hallucinates plausible-sounding text on silent/noisy input).
_NO_SPEECH_THRESHOLD = 0.65


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

        # verbose_json gives us segment-level confidence (no_speech_prob) so we can
        # detect hallucinations on silent/noisy input.  temperature=0 reduces creativity.
        transcription = client.audio.transcriptions.create(
            model=WHISPER_MODEL,
            file=(filename, audio_bytes),
            response_format="verbose_json",
            temperature=0,
        )

        # Hallucination guard — reject if Whisper thinks there's no speech
        segments = getattr(transcription, "segments", None) or []
        if segments:
            probs = [
                (s["no_speech_prob"] if isinstance(s, dict) else getattr(s, "no_speech_prob", 0))
                for s in segments
            ]
            avg_no_speech = sum(probs) / len(probs)
            logger.info(f"[Transcriber] avg_no_speech_prob={avg_no_speech:.3f} over {len(segments)} segments")
            if avg_no_speech > _NO_SPEECH_THRESHOLD:
                logger.warning(
                    f"[Transcriber] Rejecting transcription — likely noise/silence "
                    f"(avg_no_speech={avg_no_speech:.2f})"
                )
                return "ERROR: No se detectó voz clara en el audio (posible ruido o silencio)."

        text = (getattr(transcription, "text", "") or "").strip()
        if not text:
            return "ERROR: El audio no contiene texto reconocible."

        logger.info(f"[Transcriber] OK ({len(text)} chars, {len(segments)} segs): {text[:80]}")
        return text

    except Exception as e:
        logger.exception(f"[Transcriber] Error: {e}")
        return f"ERROR: Could not transcribe audio — {e}"
