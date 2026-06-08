import random
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from services.journal_db import get_random_vocabs
from services.markdown import escape, bold, italic, build

logger = logging.getLogger(__name__)

async def generate_vocab_quiz():
    """
    Tạo một bộ câu hỏi trắc nghiệm từ lịch sử từ vựng.
    Returns: (question_text, reply_markup, correct_answer_text)
    """
    # Lấy 4 từ ngẫu nhiên
    vocabs = await get_random_vocabs(limit=4)
    if not vocabs or len(vocabs) < 2:
        return None, None, None

    # Chọn từ đầu tiên làm câu hỏi chính
    target = vocabs[0]
    distractors = vocabs[1:]

    # Loại câu hỏi: 
    # 1. EN -> VI (dịch từ tiếng Anh sang tiếng Việt)
    # 2. ZH -> VI
    # 3. JA -> VI
    # Random chọn loại câu hỏi dựa trên các trường có sẵn
    available_langs = []
    if target['word_en']: available_langs.append(('en', '🇬🇧 Tiếng Anh'))
    if target['word_zh']: available_langs.append(('zh', '🇨🇳 Tiếng Trung'))
    if target['word_ja']: available_langs.append(('ja', '🇯🇵 Tiếng Nhật'))

    if not available_langs:
        return None, None, None

    lang_code, lang_name = random.choice(available_langs)
    word_to_ask = target[f'word_{lang_code}']
    correct_meaning = target['meaning_vi']

    # Chuẩn bị các phương án trả lời
    options = [correct_meaning]
    for d in distractors:
        if d['meaning_vi'] not in options:
            options.append(d['meaning_vi'])
    
    # Nếu không đủ 4 phương án do trùng lặp (hiếm), lấy thêm từ DB
    if len(options) < 4:
        more = await get_random_vocabs(limit=10)
        for m in more:
            if m['meaning_vi'] not in options:
                options.append(m['meaning_vi'])
            if len(options) >= 4:
                break

    random.shuffle(options)

    # Format nội dung
    question_text = build(
        bold("🧠 Quiz Từ vựng Mỗi ngày"),
        "",
        f"Từ {lang_name}: {bold(escape(word_to_ask))}",
        "",
        escape("Có nghĩa là gì trong tiếng Việt?")
    )

    # Tạo bàn phím inline
    keyboard = []
    # Chia 4 phương án thành 2 hàng
    row1 = []
    row2 = []
    for i, opt in enumerate(options):
        # Callback data format: quiz:is_correct:vocab_id:index
        is_correct = 1 if opt == correct_meaning else 0
        btn = InlineKeyboardButton(
            text=opt, 
            callback_data=f"quiz:{is_correct}:{target['id']}:{i}"
        )
        if i < 2:
            row1.append(btn)
        else:
            row2.append(btn)
    
    keyboard.append(row1)
    if row2:
        keyboard.append(row2)

    return question_text, InlineKeyboardMarkup(keyboard), correct_meaning
