"""자막용으로 쓸 수 있는(한글 지원) 폰트 목록.

libass 는 family 이름으로 폰트를 찾으므로 (label, family) 를 돌려준다.
설치 파일이 실제 존재하는 것만 노출. 없으면 최소한 기본(맑은 고딕)은 포함."""
import glob
import os

_DIRS = [
    "C:/Windows/Fonts",
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    os.path.expanduser("~/.fonts"),
    os.path.expanduser("~/Library/Fonts"),
]

# (표시 이름, libass family, 파일명 후보들)
_CANDIDATES = [
    ("맑은 고딕", "Malgun Gothic", ["malgun.ttf", "malgun.ttc"]),
    ("나눔고딕", "NanumGothic", ["NanumGothic.ttf", "NanumGothic-Regular.ttf"]),
    ("나눔명조", "NanumMyeongjo", ["NanumMyeongjo.ttf"]),
    ("나눔손글씨 펜", "NanumPen", ["NanumPen.ttf", "NanumPenScript-Regular.ttf"]),
    ("나눔스퀘어", "NanumSquare", ["NanumSquareR.ttf", "NanumSquare.ttf"]),
    ("굴림", "Gulim", ["gulim.ttc"]),
    ("돋움", "Dotum", ["dotum.ttc"]),
    ("바탕", "Batang", ["batang.ttc"]),
    ("본고딕(Noto)", "Noto Sans CJK KR", ["NotoSansCJK-Regular.ttc",
                                          "NotoSansKR-Regular.otf",
                                          "NotoSansCJKkr-Regular.otf"]),
]


def _exists(files):
    for d in _DIRS:
        for f in files:
            if os.path.exists(os.path.join(d, f)):
                return True
        # 나눔 계열은 하위 폴더에 흩어져 있을 수 있어 glob 로도 확인
        for f in files:
            if glob.glob(os.path.join(d, "**", f), recursive=True):
                return True
    return False


def list_fonts():
    out = [{"label": lbl, "family": fam}
           for (lbl, fam, files) in _CANDIDATES if _exists(files)]
    if not any(f["family"] == "Malgun Gothic" for f in out):
        out.insert(0, {"label": "맑은 고딕", "family": "Malgun Gothic"})
    return out
