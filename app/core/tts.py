from __future__ import annotations

GEMINI_TTS_VOICE_NAMES = {
    "achernar": "Achernar",
    "achird": "Achird",
    "algenib": "Algenib",
    "algieba": "Algieba",
    "alnilam": "Alnilam",
    "aoede": "Aoede",
    "autonoe": "Autonoe",
    "callirrhoe": "Callirrhoe",
    "charon": "Charon",
    "despina": "Despina",
    "enceladus": "Enceladus",
    "erinome": "Erinome",
    "fenrir": "Fenrir",
    "gacrux": "Gacrux",
    "iapetus": "Iapetus",
    "kore": "Kore",
    "laomedeia": "Laomedeia",
    "leda": "Leda",
    "orus": "Orus",
    "puck": "Puck",
    "pulcherrima": "Pulcherrima",
    "rasalgethi": "Rasalgethi",
    "sadachbia": "Sadachbia",
    "sadaltager": "Sadaltager",
    "schedar": "Schedar",
    "sulafat": "Sulafat",
    "umbriel": "Umbriel",
    "vindemiatrix": "Vindemiatrix",
    "zephyr": "Zephyr",
    "zubenelgenubi": "Zubenelgenubi",
}
DEFAULT_GEMINI_TTS_VOICES = ("Charon", "Puck")


def normalize_gemini_tts_voice_name(voice_name: str | None) -> str | None:
    if not voice_name:
        return None
    return GEMINI_TTS_VOICE_NAMES.get(voice_name.strip().lower())


def coerce_gemini_tts_voice_name(voice_name: str | None, speaker_index: int) -> str:
    normalized = normalize_gemini_tts_voice_name(voice_name)
    if normalized:
        return normalized
    return DEFAULT_GEMINI_TTS_VOICES[speaker_index % len(DEFAULT_GEMINI_TTS_VOICES)]
