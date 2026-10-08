"""从悬赏进度区域读取当前值和目标值，不固定每期上限。"""
import re
import unicodedata


def parse_progress_text(text: str) -> tuple[int, int] | None:
    text = unicodedata.normalize('NFKC', str(text)).replace('⁄', '/')
    text = re.sub(r'\s+', '', text).translate(str.maketrans({'O': '0', 'o': '0'}))
    # 多组进度不能合并成一个数字，也不能把单独的目标值当成已完成。
    if text.count('/') != 1:
        return None
    number = r'(?:\d{1,3}(?:,\d{3})+|\d+)'
    match = re.search(rf'(?<![\d,.+\-])({number})/({number})(?![\d,.])', text)
    if match is None:
        return None
    current, target = (int(value.replace(',', '')) for value in match.groups())
    return (current, target) if target > 0 and 0 <= current <= target else None


def read_progress(results) -> tuple[int, int] | None:
    """兼容 OCR 将分子、斜线、分母分成同行相邻文本框的情况。"""
    texts = [str(item.data or '') for item in results]
    rows = []
    for item in sorted(results, key=lambda match: (match.y + match.h / 2, match.x)):
        center = item.y + item.h / 2
        row = next((row for row in rows
                    if abs(center - row[0]) <= max(item.h, row[1]) / 2), None)
        if row is None:
            rows.append([center, item.h, [item]])
        else:
            row[2].append(item)
    for _center, _height, row in rows:
        pieces = []
        previous = None
        for item in sorted(row, key=lambda match: match.x):
            if previous is not None and item.x - (previous.x + previous.w) > 2 * max(item.h, previous.h):
                texts.append(''.join(pieces))
                pieces = []
            pieces.append(str(item.data or ''))
            previous = item
        texts.append(''.join(pieces))
    candidates = {value for text in texts if (value := parse_progress_text(text)) is not None}
    return next(iter(candidates)) if len(candidates) == 1 else None
