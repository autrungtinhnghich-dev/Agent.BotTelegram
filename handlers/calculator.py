import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import operator

logger = logging.getLogger(__name__)

# Allowed operators and functions for safe evaluation
OPERATORS = {
    '+': operator.add,
    '-': operator.sub,
    '*': operator.mul,
    '/': operator.truediv,
}

def safe_eval(expression: str):
    """
    Safely evaluates a mathematical expression.
    Only allows basic arithmetic operations and numbers.
    """
    # Remove any whitespace
    expression = expression.replace(' ', '')

    # Basic check for allowed characters (numbers, operators, parentheses, dot for float)
    if not all(c.isdigit() or c in '+-*/().' for c in expression):
        raise ValueError("Biểu thức chứa ký tự không hợp lệ.")

    # Prevent potential code injection by disallowing function calls or keywords
    if any(keyword in expression for keyword in ['import', 'exec', 'eval', 'os', '__', 'lambda', ':', ';', '[', ']', '{', '}', '"', "'"]):
        raise ValueError("Biểu thức chứa từ khóa hoặc ký tự không được phép.")

    try:
        # Evaluate the expression using a limited global and local scope
        # The 'OPERATORS' dict only exposes basic operations, preventing direct function calls
        return eval(expression, {"__builtins__": None}, OPERATORS)
    except (SyntaxError, TypeError, NameError) as e:
        raise ValueError(f"Biểu thức toán học không hợp lệ: {e}")
    except ZeroDivisionError:
        raise ValueError("Không thể chia cho 0.")

async def start_calculator(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a message when the command /calc is issued without an expression."""
    logger.info(f"Received /calc command from user {update.effective_user.id}")
    await update.message.reply_text("Chào! Tôi có thể tính toán các biểu thức toán học. Hãy gửi cho tôi biểu thức của bạn kèm theo lệnh /calc (ví dụ: /calc 2+2*3).")

async def calculate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Calculates the given mathematical expression from the /calc command."""
    if not context.args:
        await start_calculator(update, context)
        return

    expression = " ".join(context.args)
    logger.info(f"Received expression '{expression}' from user {update.effective_user.id} via /calc command")
    try:
        result = safe_eval(expression)
        await update.message.reply_text(f"Kết quả là: {result}")
    except ValueError as e:
        await update.message.reply_text(f"Có lỗi xảy ra khi tính toán: {e}. Vui lòng kiểm tra lại biểu thức của bạn.")
    except Exception as e:
        logger.error(f"Unexpected error in calculator: {e}", exc_info=True)
        await update.message.reply_text(f"Đã xảy ra lỗi không mong đợi. Vui lòng thử lại sau.")

def register_calculator_handlers(application: Application):
    """Register handlers for the calculator feature."""
    application.add_handler(CommandHandler("calc", calculate_command))
    logger.info("Calculator handlers registered.")
