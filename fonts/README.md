# 번들 폰트

자막·썸네일 기본 폰트. 모두 **SIL Open Font License 1.1** (재배포/상업 사용 가능).

| 파일 | 패밀리명 | 느낌 | 출처 |
|---|---|---|---|
| `Jua-Regular.ttf` | Jua | 둥글둥글 귀여움 + 높은 가독성 (기본) | 우아한형제들 배포, [Google Fonts](https://fonts.google.com/specimen/Jua) |
| `GowunDodum-Regular.ttf` | Gowun Dodum | 부드럽고 깔끔 | 류양희, [Google Fonts](https://fonts.google.com/specimen/Gowun+Dodum) |

`make_mv.py` 가 이 폴더를 libass `fontsdir` 로 등록하므로 시스템 설치 없이 동작한다.
다른 폰트를 쓰려면 ttf/otf 를 이 폴더에 넣고 `--font <패밀리명>` 으로 지정.
