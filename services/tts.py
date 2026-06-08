import logging
import io
from gtts import gTTS

logger = logging.getLogger(__name__)

def get_tts_voice(text, lang='en'):
    """
    Tạo file âm thanh (BytesIO) từ văn bản.
    lang: 'en' cho tiếng Anh, 'zh-CN' cho tiếng Trung, 'ja' cho tiếng Nhật.
    """
    try:
        tts = gTTS(text=text, lang=lang)
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        return fp
    except Exception as e:
        logger.error(f"Lỗi khi tạo TTS ({lang}): {e}")
        return None
