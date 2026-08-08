#!/usr/bin/env python3
"""運用カード_戸田7R-12R.html を 予想_戸田20260809_7R-12R.md（＝正）に対して監査する。

検証項目:
  1. 忠実性     — 買い目・口数・想定確率・口数合計が原文と一致するか
  2. 機械化     — 下限オッズ = 1.2 ÷ 想定確率 が全点で正しいか、
                   かつ記載値ちょうどで買ったとき §7ルール1（想定確率×オッズ ≥ 1.2）を満たすか
  3. 内部整合性 — 想定確率が確率分布として成立しているか
                   （掲載点の合計／1着最有力艇の「1着時カバー率」／Plackett-Luce との比較）

使い方:
    python3 audit_card.py [運用カード.html]

標準ライブラリのみ。実行環境にPDF/HTMLの外部ツールが無くても動く。
"""
import math
import re
import sys

CARD = sys.argv[1] if len(sys.argv) > 1 else '../運用カード_戸田7R-12R.html'

# ---------------------------------------------------------------------------
# 正（予想_戸田20260809_7R-12R.md §9 買い目一覧 ＋ §4 各レース⑤の想定確率）
# (買い目, 口数, 想定確率%) — 手で転記した唯一の入力。ここが正である。
# ---------------------------------------------------------------------------
MD = {
    '7R':  {'alloc': 15, 'rows': [('1-3-5', 3, 8), ('1-5-3', 3, 7), ('1-3-4', 2, 6),
                                  ('1-4-3', 1, 5), ('1-5-4', 1, 4), ('1-3-2', 1, 5),
                                  ('3-1-5', 2, 5), ('3-1-4', 1, 3), ('4-1-3', 1, 3)]},
    '8R':  {'alloc': 8,  'rows': [('1-6-3', 2, 9), ('6-1-3', 2, 6), ('1-3-6', 1, 6),
                                  ('1-6-5', 1, 5), ('1-3-5', 1, 4), ('3-1-6', 1, 4)]},
    '9R':  {'alloc': 10, 'rows': [('1-4-3', 3, 10), ('1-3-4', 2, 8), ('4-1-3', 2, 6),
                                  ('1-4-2', 1, 5), ('3-1-4', 1, 4), ('4-3-1', 1, 3)]},
    '10R': {'alloc': 18, 'rows': [('1-2-3', 3, 12), ('1-3-2', 3, 10), ('2-1-3', 3, 9),
                                  ('3-1-2', 3, 8), ('2-3-1', 2, 6), ('3-2-1', 2, 6),
                                  ('1-2-5', 1, 4), ('2-1-4', 1, 3)]},
    '11R': {'alloc': 14, 'rows': [('1-2-3', 2, 9), ('1-3-2', 2, 8), ('2-1-3', 2, 8),
                                  ('3-1-2', 2, 7), ('2-3-1', 1, 5), ('3-2-1', 1, 5),
                                  ('1-2-5', 1, 4), ('1-3-5', 1, 4), ('2-1-5', 1, 3),
                                  ('3-2-5', 1, 3)]},
    '12R': {'alloc': 27, 'rows': [('1-2-3', 3, 11), ('1-3-2', 3, 10), ('2-1-3', 3, 6),
                                  ('1-3-4', 2, 8), ('1-2-4', 2, 7), ('1-4-3', 2, 6),
                                  ('2-3-1', 2, 4), ('3-1-2', 2, 5), ('3-1-4', 2, 4),
                                  ('1-3-6', 1, 4), ('1-2-6', 1, 4), ('2-1-4', 1, 3),
                                  ('3-2-1', 1, 3), ('4-1-3', 1, 3), ('4-3-1', 1, 2)]},
}

# 予想_… §4④ 展開シナリオの1着率（艇番 -> 確率）。'x' は「その他」で分布から除く。
ATAMA = {
    '7R':  {'1': .55, '3': .16, '4': .09, '5': .07, '2': .07, '6': .06},
    '8R':  {'1': .44, '6': .15, '3': .13, '2': .08, '4': .07, '5': .06, 'x': .07},
    '9R':  {'1': .46, '4': .18, '3': .15, '2': .08, '5': .05, '6': .03, 'x': .05},
    '10R': {'1': .36, '2': .23, '3': .21, '4': .08, '5': .05, '6': .02, 'x': .05},
    '11R': {'1': .33, '2': .24, '3': .22, '5': .10, '6': .06, '4': .02, 'x': .03},
    '12R': {'1': .52, '2': .17, '3': .15, '4': .09, '5': .04, '6': .03},
}

ORDER = ['7R', '8R', '9R', '10R', '11R', '12R']
ROW_RE = (r'<span class="cb">([\d-]+)</span><span class="ku">(\d+)</span>'
          r'<span class="pr">(\d+)%</span><span class="od">([\d.]+)</span>')


def parse_card(path):
    src = open(path, encoding='utf-8').read()
    blocks = re.split(r'<!-- (\d+R) -->', src)
    out = {}
    for i in range(1, len(blocks), 2):
        rno, body = blocks[i], blocks[i + 1]
        alloc = re.search(r'class="alloc">(\d+)口', body)
        out[rno] = {
            'alloc': int(alloc.group(1)) if alloc else None,
            'rows': [(c, int(k), int(p), float(o))
                     for c, k, p, o in re.findall(ROW_RE, body)],
        }
    return out


def check_fidelity(card):
    print('=' * 78)
    print(' 1. 忠実性照合（.md を正とする）')
    print('=' * 78)
    bad = []
    for r in ORDER:
        md, ht = MD[r], card[r]
        md_map = {c: (k, p) for c, k, p in md['rows']}
        ht_map = {c: (k, p) for c, k, p, _ in ht['rows']}
        if set(md_map) != set(ht_map):
            bad.append((r, '買い目集合',
                        sorted(set(md_map) - set(ht_map)), sorted(set(ht_map) - set(md_map))))
        for c in sorted(set(md_map) & set(ht_map)):
            if md_map[c][0] != ht_map[c][0]:
                bad.append((r, f'{c} 口数', md_map[c][0], ht_map[c][0]))
            if md_map[c][1] != ht_map[c][1]:
                bad.append((r, f'{c} 想定確率', f'{md_map[c][1]}%', f'{ht_map[c][1]}%'))
        ms = sum(k for _, k, _ in md['rows'])
        hs = sum(k for _, k, _, _ in ht['rows'])
        if not (ms == hs == md['alloc'] == ht['alloc']):
            bad.append((r, '口数合計', f"md {ms}/配分{md['alloc']}", f"html {hs}/配分{ht['alloc']}"))
        print(f"  {r:>4}: 点数 {len(md['rows'])}/{len(ht['rows'])}  "
              f"口数合計 {ms}={hs}  配分 {md['alloc']}={ht['alloc']}  "
              f"→ {'一致' if not any(b[0] == r for b in bad) else '★不一致'}")
    total = sum(sum(k for _, k, _, _ in card[r]['rows']) for r in ORDER)
    print(f"\n  総口数 {total}（＋留保8 ＝ 100）／ 不一致 {len(bad)} 件")
    for b in bad:
        print('   ★', b)
    return bad


def check_odds(card):
    print()
    print('=' * 78)
    print(' 2. 下限オッズ = 1.2 ÷ 想定確率 の検算')
    print('=' * 78)
    arith, rule = [], []
    n = 0
    for r in ORDER:
        for c, _, p, o in card[r]['rows']:
            n += 1
            if abs(round(1.2 / (p / 100), 1) - o) > 0.051:
                arith.append((r, c, p, o, round(1.2 / (p / 100), 1)))
            if o * p / 100 < 1.2 - 1e-9:
                rule.append((r, c, p, o, o * p / 100, math.ceil(1.2 / (p / 100) * 10) / 10))
    print(f"  対象 {n} 点 ／ 算術誤り {len(arith)} 点")
    for a in arith:
        print('   ★算術誤り', a)
    print(f"\n  ★丸め方向の欠陥: {len(rule)} 点が「記載値ちょうどで買うと 想定確率×オッズ < 1.2」")
    print(f"  {'R':>5} {'買い目':<8}{'想定%':>6}{'記載':>7}{'実EV':>9}   切上げ後")
    for r, c, p, o, ev, ce in rule:
        print(f"  {r:>5} {c:<8}{p:>5}%{o:>7}{ev:>9.4f}   → {ce}")
    return arith, rule


def check_coherence(card):
    print()
    print('=' * 78)
    print(' 3. 想定確率の内部整合性')
    print('=' * 78)
    for r in ORDER:
        rows = card[r]['rows']
        tot = sum(p for _, _, p, _ in rows)
        # Plackett-Luce（Harville）で3連単を生成
        a = {k: v for k, v in ATAMA[r].items() if k != 'x'}
        s = sum(a.values())
        a = {k: v / s for k, v in a.items()}
        model = 0.0
        detail = []
        for c, _, p, o in rows:
            i, j, l = c.split('-')
            pm = a[i] * (a[j] / (1 - a[i])) * (a[l] / (1 - a[i] - a[j]))
            model += pm * 100
            detail.append((c, p, pm * 100, o))
        print(f"\n  {r}: 掲載{len(rows)}点の想定確率合計 {tot}%  "
              f"vs モデル {model:.1f}%  → 過大倍率 {tot / model:.2f}x")
        for head, hp in sorted(ATAMA[r].items(), key=lambda x: -x[1]):
            if head == 'x':
                continue
            sub = [p for c, _, p, _ in rows if c.startswith(head + '-')]
            if not sub:
                continue
            cov = 100 * sum(sub) / (hp * 100)
            flag = ' ★過大' if cov > 85 else (' ▲高い' if cov > 70 else '')
            print(f"     {head}頭: {len(sub)}点で{sum(sub)}%  vs 1着率{hp * 100:.0f}%  "
                  f"→ 1着時カバー率 {cov:.0f}%（20通り中{len(sub)}通り）{flag}")
        worst = sorted(detail, key=lambda d: -(d[1] / d[2]))[:3]
        print('     過大倍率ワースト3: ' + ' / '.join(
            f"{c} {p}% vs {pm:.1f}% ({p / pm:.2f}x, 下限{o}→{1.2 / (pm / 100):.1f})"
            for c, p, pm, o in worst))


if __name__ == '__main__':
    card = parse_card(CARD)
    check_fidelity(card)
    check_odds(card)
    check_coherence(card)
