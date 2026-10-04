# ANSI Color Codes for Terminal Output
# Usage: print(f"{Colors.RED}Error{Colors.RESET}")

class Colors:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    
    # Foreground colors
    RED = '\033[91m'       # Errors
    GREEN = '\033[92m'     # Success
    YELLOW = '\033[93m'    # Warnings
    BLUE = '\033[94m'      # Info
    MAGENTA = '\033[95m'   # Titles/Important
    CYAN = '\033[96m'      # Secondary info
    WHITE = '\033[97m'     # Regular text
    GREY = '\033[90m'      # User messages / dim text
    BROWN = '\033[33m'     # Titles/Important (orange/brown)
    ORANGE = '\033[38;5;208m'  # Alternative brown/orange
    
    # Background colors (rarely needed)
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_YELLOW = '\033[43m'
    BG_BLUE = '\033[44m'

def colorize(text: str, color: str) -> str:
    """Wrap text with color codes."""
    return f"{color}{text}{Colors.RESET}"

def error(text: str) -> str:
    return colorize(text, Colors.RED)

def success(text: str) -> str:
    return colorize(text, Colors.GREEN)

def warning(text: str) -> str:
    return colorize(text, Colors.YELLOW)

def info(text: str) -> str:
    return colorize(text, Colors.BLUE)

def title(text: str) -> str:
    return colorize(text, Colors.BROWN)

def dim(text: str) -> str:
    return colorize(text, Colors.GREY)

def user_msg(text: str) -> str:
    return colorize(text, Colors.GREY)

def important(text: str) -> str:
    return colorize(text, Colors.MAGENTA)

def secondary(text: str) -> str:
    return colorize(text, Colors.CYAN)

def bold(text: str) -> str:
    return colorize(text, Colors.BOLD)