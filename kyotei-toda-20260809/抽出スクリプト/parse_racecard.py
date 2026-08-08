#!/usr/bin/env python3
"""extract_pdf.py の座標付きアイテムから戸田出走表を構造化する。

列位置（x）はPDF内のヘッダ行から実測してマップした:
  79.8 枠番 / 102.4 級別 / 108.6 艇色 / 127.4 登番(上) 129.8 期別(下)
  169.8 選手名 / 283.8 支部(上) 出身地(下) / 311-312 年齢(上) 体重(下)
  340付近 F・L / 362-366 平均ST
  386.7 勝率(上=全国 下=当地) / 412.2 2連率3連率(連結)
  474.9 前走地 / 464-503 前回成績(下)
  516-546 出走回数・2着(上) / 519-546(下)
  567.7-634.4 全国コース別 上段=進入回数 下段=1・2・3着回数(6コース)
  647.2 モーター番号 / 670.7 モーター2連率 / 677.9 前回使用者 / 708.3 前回成績
  752.3 ボート番号 / 775.8 ボート2連率 / 783.0 前回使用者
  今節成績: 初日=803 2日目=835 3日目=868 4日目=900 (各 +0=着順 +11.4=コース +19.5=ST)
"""
import re
import sys
from collections import defaultdict

import extract_pdf as ex

DAY_BASE = [803.0, 835.5, 868.0, 900.5, 933.0, 965.5, 998.0]
SUB = {'着': 0.0, 'コ': 11.4, 'ST': 19.5}


def near(x, target, tol=3.0):
    return abs(x - target) <= tol


def in_range(x, lo, hi):
    return lo <= x <= hi


def page_items(page_index):
    num, head = ex.find_pages()[page_index]
    fonts = ex.resolve_font_map(head)
    return sorted(ex.extract_page(ex.page_contents(head), fonts))


def split_races(items):
    """レースヘッダ(◯Ｒ)の y でレース区間に切る。"""
    heads = []
    for y, x, t in items:
        if 150 <= x <= 200 and re.fullmatch(r'[０-９1-9１２]{1,3}Ｒ', t):
            heads.append((y, t))
    heads.sort()
    races = []
    for i, (y, name) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else 1e9
        races.append((name, y, end))
    return races


def race_meta(items, y0):
    meta = {}
    for y, x, t in items:
        if not (y0 - 3 <= y <= y0 + 6):
            continue
        if re.fullmatch(r'\d{1,2}:\d{2}', t):
            meta['締切'] = t
        elif 300 <= x <= 448 and len(t) >= 2 and '進入' not in t and '予定' not in t:
            meta.setdefault('レース名', t)
    return meta


def split2(s):
    """'44.261.0' のように連結した2つの小数を分ける。"""
    m = re.fullmatch(r'(\d{1,3}\.\d)(\d{1,3}\.\d)', s)
    return f'{m.group(1)}/{m.group(2)}' if m else s


def parse_boat(block_up, block_mid, block_lo):
    """上段/中段/下段のアイテム列から1艇分の辞書を作る。

    中段（登番行と当地行の間）には 級別・選手名・平均ST・モーター番号・
    ボート番号が置かれている。
    """
    d = {}
    up = {round(x, 1): t for y, x, t in block_up}
    mid = {round(x, 1): t for y, x, t in block_mid}
    lo = {round(x, 1): t for y, x, t in block_lo}

    def pick(src, target, tol=3.0):
        for x, t in src.items():
            if near(x, target, tol):
                return t
        return ''

    def pick_all(src, lo_x, hi_x):
        return [(x, t) for x, t in sorted(src.items()) if in_range(x, lo_x, hi_x)]

    both = dict(up)
    both.update(mid)
    both.update(lo)

    d['枠'] = pick(both, 79.8, 4)
    d['級別'] = pick(mid, 102.4, 4) or pick(both, 102.4, 4)
    d['登番'] = pick(up, 127.4, 4)
    d['期別'] = pick(lo, 129.8, 4)
    d['選手名'] = pick(both, 169.8, 12).replace('　', '')
    d['支部'] = pick(up, 283.8, 5)
    d['出身'] = pick(lo, 283.8, 5)
    d['年齢'] = pick(up, 312.0, 4)
    d['体重'] = pick(lo, 311.5, 4)
    # F/L は 級別のすぐ右、年齢の右あたりに "F1"/"L1" で出る
    fl = [t for x, t in both.items() if in_range(x, 325, 352) and re.fullmatch(r'[FL]\d', t)]
    fl += [t for x, t in both.items() if re.fullmatch(r'[FL]\d', t) and in_range(x, 95, 115)]
    d['F/L'] = ','.join(sorted(set(fl))) or '-'
    d['平均ST'] = pick(mid, 363.5, 6) or pick(both, 363.5, 6)
    d['全国勝率'] = pick(up, 386.7, 4)
    d['当地勝率'] = pick(lo, 386.7, 4)
    d['全国2/3連率'] = split2(''.join(t for x, t in pick_all(up, 404, 452)))
    d['当地2/3連率'] = split2(''.join(t for x, t in pick_all(lo, 404, 452)))
    d['前走地'] = pick(up, 474.9, 6)
    d['モーター'] = pick(mid, 647.2, 4) or pick(both, 647.2, 4)
    d['M前回使用'] = pick(up, 677.9, 5)
    d['ボート'] = pick(mid, 752.3, 4) or pick(both, 752.3, 4)
    d['B前回使用'] = pick(up, 783.0, 5)

    # 全国コース別: 上段=進入回数, 下段=1・2・3着回数（右詰めなので連結を分解）
    d['進入回数'] = [t for x, t in pick_all(up, 560, 648)]
    d['コース別3連対'] = [t for x, t in pick_all(lo, 560, 648)]
    d['前回成績'] = ''.join(t for x, t in pick_all(lo, 455, 510))

    # 今節成績
    def day_cells(src):
        out = []
        for base in DAY_BASE:
            chaku = koh = st = ''
            for x, t in src.items():
                if near(x, base + SUB['着'], 2.0):
                    chaku = t
                elif near(x, base + SUB['コ'], 2.0):
                    koh = t
                elif near(x, base + SUB['ST'], 2.0):
                    st = t
            out.append((chaku, koh, st) if (chaku or koh or st) else None)
        return out

    d['今節_前'] = day_cells(up)
    d['今節_後'] = day_cells(lo)
    return d


def parse_page(page_index, out):
    items = page_items(page_index)
    races = split_races(items)
    for name, y0, y1 in races:
        seg = [(y, x, t) for y, x, t in items if y0 <= y < y1]
        meta = race_meta(items, y0)
        # 登番アンカー（4桁数字, x≈127.4）
        anchors = sorted(y for y, x, t in seg
                         if near(x, 127.4, 3) and re.fullmatch(r'\d{4}', t))
        boats = []
        for ay in anchors:
            up = [(y, x, t) for y, x, t in seg if ay - 1.6 <= y <= ay + 3.6]
            mid = [(y, x, t) for y, x, t in seg if ay + 3.6 < y < ay + 11.4]
            lo = [(y, x, t) for y, x, t in seg if ay + 11.4 <= y <= ay + 17.6]
            boats.append(parse_boat(up, mid, lo))
        out.append((name, meta, boats))


def fmt(name, meta, boats):
    L = []
    L.append(f"\n## {name}  {meta.get('レース名','')}  締切 {meta.get('締切','')}  H1800m")
    L.append('')
    L.append('| 枠 | 級 | 登番 | 選手名 | 支部/出身 | 年齢 | 体重 | F/L | 平均ST | 全国勝率 | 全国2/3連 | 当地勝率 | 当地2/3連 | M# | B# | 前走地 |')
    L.append('|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|')
    for b in boats:
        L.append('| {枠} | {級別} | {登番} | {選手名} | {支部}/{出身} | {年齢} | {体重} | {F/L} | .{平均ST} | {全国勝率} | {全国2/3連率} | {当地勝率} | {当地2/3連率} | {モーター} | {ボート} | {前走地} |'.format(**b))
    L.append('')
    L.append('**全国コース別（上段=進入回数[1-6コース] / 下段=1・2・3着回数）と今節成績**')
    L.append('')
    for b in boats:
        L.append(f"- **{b['枠']}号艇 {b['選手名']}**")
        L.append(f"  - 全国コース別 進入回数(1→6コース): {' '.join(b['進入回数'])}")
        L.append(f"  - 全国コース別 3連対数(1→6コース): {' '.join(b['コース別3連対'])}")
        L.append(f"  - 前回成績: {b['前回成績']}")
        for label, cells in (('前半', b['今節_前']), ('後半', b['今節_後'])):
            s = []
            for i, c in enumerate(cells, 1):
                if c:
                    s.append(f"{i}日目[着{c[0]}/{c[1]}コース/ST.{c[2]}]")
            if s:
                L.append(f"  - 今節{label}: " + ' '.join(s))
    return '\n'.join(L)


def main():
    out = []
    parse_page(0, out)
    parse_page(1, out)
    print('# 戸田 2026/8/9（アサヒスーパードライカップ 最終日・4日目）出走表')
    print('\n※ モーター/ボートともに使用開始日 2026/8/5 の**新機**（2連率データなし）')
    print('※ 節間: 初日8/6(木) 2日目8/7(金) 3日目8/8(土) 最終日8/9(日)')
    for name, meta, boats in out:
        print(fmt(name, meta, boats))


if __name__ == '__main__':
    main()
