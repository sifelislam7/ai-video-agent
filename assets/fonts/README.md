# Bundled fonts

| File | Family | License |
|---|---|---|
| `Cairo_400Regular.ttf`, `Cairo_700Bold.ttf`, `Cairo_900Black.ttf` | [Cairo](https://fonts.google.com/specimen/Cairo) | SIL Open Font License 1.1 |
| `NotoSansArabic_700Bold.ttf` | [Noto Sans Arabic](https://fonts.google.com/noto/specimen/Noto+Sans+Arabic) | SIL Open Font License 1.1 |

Both families cover Arabic **and** Latin, including the Arabic Presentation
Forms-B block (`U+FE70–U+FEFF`) that `arabic-reshaper` produces — this is what
makes Arabic captions render correctly with Pillow (which has no HarfBuzz
shaper in most wheels).

Add more families with:

```bash
python scripts/fetch_fonts.py --list
python scripts/fetch_fonts.py --font tajawal --font amiri
```
