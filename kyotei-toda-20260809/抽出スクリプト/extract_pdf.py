#!/usr/bin/env python3
"""標準ライブラリのみでテキストPDF(Identity-H + ToUnicode)から座標付きテキストを抽出する。

対象: ボートレース出走表PDF (Type0/CIDFontType2, Identity-H, ToUnicode CMap同梱)
出力: (page, y, x, text) を行復元して標準出力へ
"""
import re
import sys
import zlib
from collections import defaultdict

PDF = sys.argv[1] if len(sys.argv) > 1 else '/mnt/c/Users/momok/Downloads/2026.08.09.pdf'
data = open(PDF, 'rb').read()


# ---------- オブジェクト収集 ----------
def collect_objects(d):
    objs = {}
    for m in re.finditer(rb'(?<![0-9])(\d+)\s+(\d+)\s+obj\b', d):
        num = int(m.group(1))
        start = m.end()
        end = d.find(b'endobj', start)
        objs[num] = d[start:end]
    return objs


OBJS = collect_objects(data)


def raw_stream(body):
    """オブジェクト本体から stream…endstream の生バイト列を返す。無ければ None。"""
    j = body.find(b'stream')
    if j < 0:
        return None
    k = body.rfind(b'endstream')
    if k < 0:
        return None
    s = body[j + len(b'stream'):k]
    # stream キーワード直後の EOL を剥がす
    if s.startswith(b'\r\n'):
        s = s[2:]
    elif s[:1] in (b'\n', b'\r'):
        s = s[1:]
    return s.rstrip(b'\r\n')


def stream_data(num):
    """オブジェクト num のストリームを（必要なら Flate 展開して）返す。"""
    body = OBJS.get(num)
    if body is None:
        return None
    s = raw_stream(body)
    if s is None:
        return None
    if b'/FlateDecode' in body.split(b'stream')[0]:
        try:
            return zlib.decompress(s)
        except zlib.error:
            try:
                return zlib.decompressobj().decompress(s)
            except zlib.error:
                return None
    return s


# ---------- ToUnicode CMap ----------
def parse_tounicode(num):
    """ToUnicode ストリームを CID -> Unicode文字列 の dict にする。"""
    s = stream_data(num)
    if not s:
        return {}
    table = {}
    for blk in re.findall(rb'beginbfchar(.*?)endbfchar', s, re.S):
        for src, dst in re.findall(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', blk):
            table[int(src, 16)] = bytes.fromhex(dst.decode()).decode('utf-16-be', 'replace')
    for blk in re.findall(rb'beginbfrange(.*?)endbfrange', s, re.S):
        # <lo> <hi> <dstStart> 形式
        for lo, hi, dst in re.findall(
                rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', blk):
            lo_i, hi_i = int(lo, 16), int(hi, 16)
            base = bytes.fromhex(dst.decode()).decode('utf-16-be', 'replace')
            for i in range(lo_i, hi_i + 1):
                if len(base) == 1:
                    table[i] = chr(ord(base) + (i - lo_i))
                else:
                    table[i] = base
        # <lo> <hi> [ <d1> <d2> ... ] 形式
        for lo, hi, arr in re.findall(
                rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*\[(.*?)\]', blk, re.S):
            lo_i = int(lo, 16)
            dsts = re.findall(rb'<([0-9A-Fa-f]+)>', arr)
            for off, dst in enumerate(dsts):
                table[lo_i + off] = bytes.fromhex(dst.decode()).decode('utf-16-be', 'replace')
    return table


# ---------- ページ構造 ----------
def find_pages():
    """/Type /Page のオブジェクトを文書順に返す。"""
    pages = []
    for num, body in sorted(OBJS.items()):
        head = body.split(b'stream')[0]
        if re.search(rb'/Type\s*/Page\b(?!s)', head):
            pages.append((num, head))
    return pages


def resolve_font_map(page_head):
    """ページの /Resources /Font << /F1 9 0 R ... >> を {b'F1': cid_table} にする。"""
    fonts = {}
    m = re.search(rb'/Font\s*<<(.*?)>>', page_head, re.S)
    ref_src = m.group(1) if m else b''
    if not ref_src:
        # /Resources が間接参照の場合
        rm = re.search(rb'/Resources\s+(\d+)\s+\d+\s+R', page_head)
        if rm:
            rbody = OBJS.get(int(rm.group(1)), b'')
            m2 = re.search(rb'/Font\s*<<(.*?)>>', rbody, re.S)
            ref_src = m2.group(1) if m2 else b''
    for name, ref in re.findall(rb'/(\w+)\s+(\d+)\s+\d+\s+R', ref_src):
        font_body = OBJS.get(int(ref), b'')
        tu = re.search(rb'/ToUnicode\s+(\d+)\s+\d+\s+R', font_body)
        if not tu:
            # Type0 の場合 DescendantFonts 側にある可能性を一応見る
            df = re.search(rb'/DescendantFonts\s*\[\s*(\d+)\s+\d+\s+R', font_body)
            if df:
                tu = re.search(rb'/ToUnicode\s+(\d+)\s+\d+\s+R', OBJS.get(int(df.group(1)), b''))
        fonts[name.decode()] = parse_tounicode(int(tu.group(1))) if tu else {}
    return fonts


def page_contents(page_head):
    """ページの /Contents を展開して連結したバイト列で返す。"""
    m = re.search(rb'/Contents\s+(\d+)\s+\d+\s+R', page_head)
    if m:
        return stream_data(int(m.group(1))) or b''
    m = re.search(rb'/Contents\s*\[(.*?)\]', page_head, re.S)
    if m:
        parts = []
        for num in re.findall(rb'(\d+)\s+\d+\s+R', m.group(1)):
            parts.append(stream_data(int(num)) or b'')
        return b'\n'.join(parts)
    return b''


# ---------- コンテンツストリームのトークナイザ ----------
TOKEN_RE = re.compile(rb'''
      (?P<hexstr><[0-9A-Fa-f\s]*>)
    | (?P<lit>\()
    | (?P<name>/[^\s/\[\]<>(){}]*)
    | (?P<num>[-+]?[0-9]*\.?[0-9]+)
    | (?P<delim>[\[\]{}])
    | (?P<op>[A-Za-z'"*][A-Za-z0-9*'"]*)
''', re.X)


def read_literal(buf, i):
    """'(' 直後の位置 i から文字列を読み、(bytes, 次の位置) を返す。"""
    out = bytearray()
    depth = 1
    while i < len(buf):
        c = buf[i]
        if c == 0x5C:  # backslash
            out.append(buf[i + 1] if i + 1 < len(buf) else 0x20)
            i += 2
            continue
        if c == 0x28:
            depth += 1
        elif c == 0x29:
            depth -= 1
            if depth == 0:
                return bytes(out), i + 1
        out.append(c)
        i += 1
    return bytes(out), i


def extract_page(content, fonts):
    """content から (y, x, text) のリストを返す。"""
    items = []
    stack = []          # オペランドスタック
    cur_font = None
    tm = [1, 0, 0, 1, 0, 0]   # テキスト行列
    tlm = list(tm)            # 行頭行列
    i = 0
    n = len(content)
    while i < n:
        m = TOKEN_RE.match(content, i)
        if not m:
            i += 1
            continue
        i = m.end()
        if m.lastgroup == 'lit':
            s, i = read_literal(content, i)
            stack.append(('str', s, False))
        elif m.lastgroup == 'hexstr':
            h = re.sub(rb'\s', b'', m.group()[1:-1])
            stack.append(('str', h, True))
        elif m.lastgroup == 'num':
            stack.append(('num', float(m.group())))
        elif m.lastgroup == 'name':
            stack.append(('name', m.group()[1:].decode('latin-1')))
        elif m.lastgroup == 'delim':
            stack.append(('delim', m.group()))
        else:
            op = m.group().decode('latin-1')
            if op == 'Tf':
                names = [v for t, *v in [(x[0],) + tuple(x[1:]) for x in stack] if t == 'name']
                if names:
                    cur_font = names[-1][0] if isinstance(names[-1], tuple) else names[-1]
                # 直前の name オペランドを font 名として採用
                for tok in reversed(stack):
                    if tok[0] == 'name':
                        cur_font = tok[1]
                        break
                stack = []
            elif op == 'BT':
                tm = [1, 0, 0, 1, 0, 0]
                tlm = list(tm)
                stack = []
            elif op == 'Tm':
                nums = [t[1] for t in stack if t[0] == 'num'][-6:]
                if len(nums) == 6:
                    tm = nums
                    tlm = list(nums)
                stack = []
            elif op in ('Td', 'TD'):
                nums = [t[1] for t in stack if t[0] == 'num'][-2:]
                if len(nums) == 2:
                    tlm = [tlm[0], tlm[1], tlm[2], tlm[3],
                           tlm[4] + nums[0] * tlm[0] + nums[1] * tlm[2],
                           tlm[5] + nums[0] * tlm[1] + nums[1] * tlm[3]]
                    tm = list(tlm)
                stack = []
            elif op == 'T*':
                stack = []
            elif op in ('Tj', 'TJ', "'", '"'):
                table = fonts.get(cur_font, {})
                pieces = []
                for tok in stack:
                    if tok[0] != 'str':
                        continue
                    payload, is_hex = tok[1], tok[2]
                    if is_hex:
                        h = payload.decode('latin-1')
                        if len(h) % 4:
                            h = h + '0' * (4 - len(h) % 4)
                        for k in range(0, len(h), 4):
                            cid = int(h[k:k + 4], 16)
                            pieces.append(table.get(cid, '�'))
                    else:
                        for k in range(0, len(payload) - 1, 2):
                            cid = (payload[k] << 8) | payload[k + 1]
                            pieces.append(table.get(cid, '�'))
                text = ''.join(pieces)
                if text.strip():
                    items.append((round(tm[5], 1), round(tm[4], 1), text))
                stack = []
            else:
                stack = []
    return items


# ---------- 行復元 ----------
def to_lines(items, ytol=2.0):
    rows = defaultdict(list)
    for y, x, t in items:
        key = None
        for existing in rows:
            if abs(existing - y) <= ytol:
                key = existing
                break
        rows[y if key is None else key].append((x, t))
    out = []
    for y in sorted(rows):
        cells = sorted(rows[y])
        parts = []
        prev_x = None
        for x, t in cells:
            if prev_x is not None and x - prev_x > 6:
                parts.append('\t')
            parts.append(t)
            prev_x = x
        out.append((y, ''.join(parts)))
    return out


def main():
    pages = find_pages()
    print(f'# pages={len(pages)}  objects={len(OBJS)}', file=sys.stderr)
    for pno, (num, head) in enumerate(pages, 1):
        fonts = resolve_font_map(head)
        print(f'# page{pno}: obj={num} fonts=' +
              ', '.join(f'{k}({len(v)})' for k, v in fonts.items()), file=sys.stderr)
        content = page_contents(head)
        items = extract_page(content, fonts)
        print(f'# page{pno}: text items={len(items)}', file=sys.stderr)
        print(f'\n===== PAGE {pno} =====')
        for y, line in to_lines(items):
            print(f'{y:8.1f} | {line}')


if __name__ == '__main__':
    main()
