"""
安全工具函数

提供 SQL 注入防护、输入清理等安全相关的工具。
"""

import re


# 控制字符正则（防止 ANSI escape / 换行符伪造等）
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def escape_like_pattern(value: str) -> str:
    """
    转义 SQL LIKE 通配符，防止 ILIKE 注入。

    Args:
        value: 用户输入的搜索关键词

    Returns:
        转义后的安全字符串
    """
    if not value:
        return value
    return value.replace('%', r'\%').replace('_', r'\_')


def sanitize_search_input(value: str, max_length: int = 200) -> str:
    """
    清理搜索输入：去除控制字符 + 长度限制。
    不再过度过滤 Unicode（emoji/多语言都允许），主要靠参数化查询防注入。

    Args:
        value: 用户输入
        max_length: 最大长度限制

    Returns:
        清理后的安全字符串
    """
    if not value:
        return ""

    value = value.strip()
    if len(value) > max_length:
        value = value[:max_length]
    # 只去控制字符，保留所有可见 Unicode（emoji/中日韩/阿拉伯等都允许）
    value = _CONTROL_CHARS.sub("", value)
    return value


def validate_session_id(session_id: str) -> bool:
    """
    校验 session_id 格式，防止注入和异常长度。

    Args:
        session_id: 会话 ID

    Returns:
        是否合法
    """
    if not session_id:
        return False
    # 仅允许字母数字下划线短串，长度 ≤ 128
    if len(session_id) > 128:
        return False
    return bool(re.match(r'^[a-zA-Z0-9_\-]{1,128}$', session_id))