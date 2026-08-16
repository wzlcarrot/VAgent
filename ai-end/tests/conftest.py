"""
共享 pytest 配置：确保 `app` 包可导入（支持从任意目录执行 pytest）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
