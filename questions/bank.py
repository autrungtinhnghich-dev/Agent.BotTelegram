import random
from datetime import datetime

# Ngân hàng câu hỏi chia theo các chủ đề
QUESTION_BANK = {
    "EMOTION": [
        "Hôm nay bạn cảm thấy thế nào? (1 từ hoặc emoji cũng được 😊)",
        "Điều gì làm bạn mỉm cười hôm nay?",
        "Có khoảnh khắc nào hôm nay làm bạn thấy biết ơn không?",
        "Hôm nay tâm trạng của bạn giống thời tiết nào nhất? ☀️🌧️☁️",
        "Điều gì khiến bạn thấy tự hào về bản thân ngày hôm nay?",
        "Hôm nay bạn có cảm thấy bình yên không?",
        "Một từ duy nhất để mô tả năng lượng của bạn lúc này là gì?"
    ],
    "EVENT": [
        "Điều gì đáng nhớ nhất hôm nay của bạn?",
        "Bạn đã hoàn thành công việc gì quan trọng nhất hôm nay?",
        "Hôm nay có sự kiện gì bất ngờ xảy ra không?",
        "Bạn đã gặp gỡ hay trò chuyện với ai thú vị hôm nay?",
        "Có thử thách nào bạn đã vượt qua trong ngày hôm nay?",
        "Bữa ăn ngon nhất hôm nay của bạn là gì?",
        "Bạn đã dành thời gian cho sở thích nào hôm nay?"
    ],
    "REFLECTION": [
        "Bạn học được gì mới hôm nay, dù nhỏ thôi?",
        "Nếu được làm lại một việc hôm nay, bạn sẽ làm gì khác đi?",
        "Hôm nay bạn đã làm điều gì tốt cho người khác chưa?",
        "Điều gì bạn muốn duy trì vào ngày mai?",
        "Bạn đã chăm sóc bản thân như thế nào hôm nay?",
        "Có điều gì bạn đang trăn trở sau ngày hôm nay không?",
        "Một mục tiêu nhỏ bạn muốn đặt ra cho ngày mai là gì?"
    ]
}

def get_daily_question(date_obj=None):
    """
    Lấy câu hỏi cho ngày cụ thể. 
    Sử dụng day_of_year để đảm bảo tất cả user nhận cùng 1 câu hỏi mỗi ngày.
    """
    if not date_obj:
        date_obj = datetime.now()
        
    day_of_year = date_obj.timetuple().tm_yday
    categories = list(QUESTION_BANK.keys())
    
    # Xoay vòng category theo ngày
    cat_index = day_of_year % len(categories)
    category = categories[cat_index]
    
    # Xoay vòng câu hỏi trong category
    questions = QUESTION_BANK[category]
    q_index = (day_of_year // len(categories)) % len(questions)
    
    return questions[q_index]

def get_random_question():
    """Lấy một câu hỏi ngẫu nhiên bất kỳ."""
    category = random.choice(list(QUESTION_BANK.keys()))
    return random.choice(QUESTION_BANK[category])
