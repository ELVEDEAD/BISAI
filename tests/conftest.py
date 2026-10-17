"""conftest.py —— 将项目根目录加入 sys.path，使测试可直接 import core 包"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)