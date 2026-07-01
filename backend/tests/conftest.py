"""테스트가 backend 모듈(import jobs 등)과 루트의 make_mv 를 찾도록 경로 등록."""
import os
import sys

HERE = os.path.dirname(__file__)
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(BACKEND)
for p in (BACKEND, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)
