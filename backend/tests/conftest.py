"""테스트가 backend 모듈(import jobs 등)과 루트의 make_mv 를 찾도록 경로 등록."""
import os
import sys
import tempfile

HERE = os.path.dirname(__file__)
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(BACKEND)
for p in (BACKEND, ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

# jobs.py/settings.py 는 import 시점에 paths.data_dir() 를 호출한다.
# 실제 사용자 "문서" 폴더가 생성되지 않도록, 첫 import 이전에 임시 경로로 고정한다
# (개별 테스트는 필요하면 monkeypatch 로 각자 격리해서 쓴다).
os.environ.setdefault("MV_DATA_DIR", os.path.join(tempfile.gettempdir(), "mv-test-data"))
