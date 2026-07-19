"""pytest 부트스트랩 — repo 루트를 sys.path 에 넣어 `db` 패키지 import 가능하게."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
