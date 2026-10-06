# -*- coding: utf-8 -*-
"""把霞鹜文楷（LXGW WenKai Regular）子集化為自托管的 woff2，分兩級：

  1. fonts/zy-ui.woff2    ——「介面字集」：不查詢、不開彈窗時頁面會用到的全部字
                             （三語介面文案、查詢結果卡片的固定框架文字、說明彈窗）。
                             約 0.1 MB，訪客的第一個字型請求只需要這一個檔案。
  2. fonts/zy-dict.woff2  ——「字典字集」：查詢結果裡會出現的漢字（data/DB_suhu.json
                             的全部漢字，約 8100 字）＋ 羅馬字 ＋ 音值符號。
                             約 1.7 MB，使用者第一次查詢才下載。

與韻圖站（wugniu_yuntu/make_font.py）同源同法，差別只在分級：

  · 韻圖站分三片，多一塊 wk-ext（7.4 MB）當「完整 CJK 回退」。那是因為韻圖頁會把
    字典裡大量生僻字鋪在表格裡，介面片＋字典片仍可能漏字。本站不會：查詢結果只可能
    來自 DB_suhu.json 與介面文案兩處，兩片聯集即為全集，加 ext 只是白下載 7 MB。
    漏掉的字（霞鹜文楷本身沒有的 107 個擴展 B 生僻字）直接交給系統字型。
  · 韻圖站的兩片共用同一 font-family「LXGW WenKai」，靠互不重疊的精確 unicode-range
    決定誰出場。本站照做。

「精確 unicode-range」是關鍵：每個檔案宣告的 unicode-range 不是整塊 CJK 區段，而是由它
自己 cmap 裡真實存在的碼位壓縮而成。這樣瀏覽器一遇到霞鹜文楷根本沒有的字（本站有 107 個
擴展 B 區生僻字，以及 ᵝᶽ 兩個 IPA 修飾字母），立刻知道回退字型也幫不上忙，直接交給
系統字型。

重跑：python make_font.py
（改了介面文案之後，請先跑 measure_firstpaint.py 重測 firstpaint.txt）
"""
import os, sys, json, re, hashlib, time

from fontTools import subset
from fontTools.ttLib import TTFont

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = r"D:\Wu\NetDisk Download\lxgw-wenkai-v1.522\lxgw-wenkai-v1.522\LXGWWenKai-Regular.ttf"
DB = os.path.join(HERE, "data", "DB_suhu.json")
OUT = os.path.join(HERE, "fonts")

BASE_ARGS = [
    "--flavor=woff2", "--no-hinting", "--desubroutinize", "--layout-features=",
    "--drop-tables+=GSUB,GPOS,GDEF,BASE,JSTF,vhea,vmtx,VORG,DSIG,mort,kerx,ankr,trak,kern,opbd,prop",
    "--notdef-outline", "--recalc-bounds",
]

FAMILY = "LXGW WenKai"
# 與韻圖站同一個字型版本（對應源字體檔名 lxgw-wenkai-v1.522），用來破 CDN 快取
FONT_V = "1522b"


# ---------------------------------------------------------------- 工具
def cmap_codepoints(path):
    f = TTFont(path, lazy=True)
    cps = set()
    for t in f["cmap"].tables:
        cps |= set(t.cmap.keys())
    f.close()
    return cps


def compact_ranges(cps):
    """把碼位集合壓縮成 CSS unicode-range 用的區間字串清單。"""
    cps = sorted(cps)
    out, i = [], 0
    while i < len(cps):
        j = i
        while j + 1 < len(cps) and cps[j + 1] == cps[j] + 1:
            j += 1
        out.append("U+%04X" % cps[i] if cps[i] == cps[j]
                   else "U+%04X-%04X" % (cps[i], cps[j]))
        i = j + 1
    return out


def clean(s):
    """去掉控制字元。"""
    return {c for c in s if ord(c) >= 0x20 and c != "\x7f"}


# ---------------------------------------------------------------- 字集
def dict_chars():
    """字典裡可能出現在查詢結果中的字：漢字 ＋ 詞語解釋裡的字。"""
    if not os.path.exists(DB):
        print("  ⚠ 找不到 %s，字典片會是空的" % DB)
        return set()
    db = json.load(open(DB, encoding="utf-8"))
    s = set()
    for e in db:
        s.update(e.get("character", ""))
        for m in e.get("meaning", []):
            if m and isinstance(m[0], str):
                s.update(m[0])
    return s


def interface_chars():
    """介面字集：優先用瀏覽器實測的 firstpaint.txt（含彈窗與查詢結果的框架文字）。"""
    p = os.path.join(HERE, "firstpaint.txt")
    if os.path.exists(p):
        s = set(open(p, encoding="utf-8").read())
        print("  介面字表來自 firstpaint.txt（瀏覽器實測）")
        return clean(s)

    # 沒有 firstpaint.txt 時的保守後備：靜態 HTML 文字 + i18n 字典字串 + 羅馬字／IPA。
    print("  ⚠ 找不到 firstpaint.txt，改用靜態估算（可跑 measure_firstpaint.py 重測）")
    h = open(os.path.join(HERE, "templates/index_static.html"), encoding="utf-8").read()
    s = set()
    body = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", h)
    s.update(re.sub(r"<[^>]+>", " ", body))
    for m in re.finditer(r"var i18n = \{([\s\S]*?)\n\};", h):
        for lit in re.findall(r"'((?:[^'\\]|\\.)*)'", m.group(1)):
            s.update(lit.replace("\\'", "'"))
            for u in re.findall(r"\\u([0-9a-fA-F]{4})", lit):
                s.add(chr(int(u, 16)))
    # 羅馬字與音值符號
    s |= set("abcdefghijklmnopqrstuvwxyz")
    s |= set("ɑɒɓɔəɚɛɜɝɞɟʄɡɠɢʛɦɨɪʝɭɮɯɰŋɳɲɴøɵɸθœɶʈʂʃʒʔʡʢǀǁǂǃ")
    s |= set("ːˑˤˈˌβθʰʷʲˠ")
    s |= set("⁰¹²³⁴⁵⁶⁷⁸⁹ⁿˡ")
    s |= set("ᵝᶽ")
    s |= set("，。、；：？！（）「」『』〈〉《》〔〕【】…—～·")
    return clean(s)


# ---------------------------------------------------------------- 產出
CACHE = os.path.join(HERE, "font_cache.json")


def _sig(payload):
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _src_fingerprint():
    st = os.stat(SRC)
    return "%d-%d" % (st.st_size, int(st.st_mtime))


def run(dst, args, label):
    t = time.time()
    subset.main([SRC, "--output-file=" + dst] + args + BASE_ARGS)
    mb = os.path.getsize(dst) / 1048576
    print("  %-16s %6.2f MB  %5.1fs  %s" % (os.path.basename(dst), mb, time.time() - t, label))
    return mb


def run_cached(key, dst, args, label, payload):
    """輸入沒變就跳過子集化。"""
    cache = {}
    if os.path.exists(CACHE):
        try:
            cache = json.load(open(CACHE, encoding="utf-8"))
        except Exception:
            cache = {}
    sig = _sig(payload + "|" + _src_fingerprint())
    if os.path.exists(dst) and cache.get(key) == sig:
        mb = os.path.getsize(dst) / 1048576
        print("  %-16s %6.2f MB    （輸入未變，跳過）  %s" % (os.path.basename(dst), mb, label))
        return mb
    mb = run(dst, args, label)
    cache[key] = sig
    json.dump(cache, open(CACHE, "w", encoding="utf-8"))
    return mb


def main():
    if not os.path.exists(SRC):
        print("找不到源字體：", SRC)
        sys.exit(1)
    os.makedirs(OUT, exist_ok=True)

    print("· 收集字集")
    vis = interface_chars()
    dic = dict_chars()
    # 關鍵：dict 片必須**排除** ui 片已有的字，兩片的 unicode-range 才可以完全不交疊。
    # 若重疊了（這裡一開始寫成 dic |= vis 就重疊），瀏覽器只會下載「後宣告的那一片」，
    # 實測首屏就直接去拉 2 MB 的 dict 片，分級等於失效。參照韻圖站：wk-ui 末碼位
    # U+FF5E、wk-dict 首碼位 U+0101，中間留著空隙，兩者互不相交。
    dic -= vis
    print("  介面字集        %5d 字" % len(vis))
    print("  字典字集        %5d 字（已扣除介面片的 %d 字）" % (len(dic), len(vis)))

    src_cmap = cmap_codepoints(SRC)
    print("  源字體碼位      %5d 個" % len(src_cmap))

    ui_p = os.path.join(OUT, "_ui.txt")
    dt_p = os.path.join(OUT, "_dict.txt")
    open(ui_p, "w", encoding="utf-8").write("".join(sorted(vis)))
    open(dt_p, "w", encoding="utf-8").write("".join(sorted(dic)))

    print("· 子集化")
    report = []

    ui_text = open(ui_p, encoding="utf-8").read()
    mb = run_cached("ui", os.path.join(OUT, "zy-ui.woff2"),
                    ["--text-file=" + ui_p], "介面字集（三語介面・說明彈窗）", ui_text)
    cui = cmap_codepoints(os.path.join(OUT, "zy-ui.woff2"))
    report.append({"file": "zy-ui.woff2", "family": FAMILY,
                   "range": compact_ranges(cui), "mb": round(mb, 2)})

    dt_text = open(dt_p, encoding="utf-8").read()
    mb = run_cached("dict", os.path.join(OUT, "zy-dict.woff2"),
                    ["--text-file=" + dt_p], "字典字集（查詢結果的漢字）", dt_text)
    cdt = cmap_codepoints(os.path.join(OUT, "zy-dict.woff2"))
    report.append({"file": "zy-dict.woff2", "family": FAMILY,
                   "range": compact_ranges(cdt), "mb": round(mb, 2)})

    for p in (ui_p, dt_p):
        os.remove(p)

    json.dump({"version": FONT_V, "faces": report},
              open(os.path.join(HERE, "font_report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # ---- 覆蓋率自檢 ----
    print("· 覆蓋率自檢")
    allneed = vis | dic
    need_in_src = {c for c in allneed if ord(c) in src_cmap}
    covered = cui | cdt
    missing = sorted(c for c in need_in_src if ord(c) not in covered)
    print("  需要而源字體有的字 %5d，兩片未覆蓋 %d" % (len(need_in_src), len(missing)))
    if missing:
        print("    !! 未覆蓋：", "".join(missing[:40]))
    gone = sorted(c for c in allneed if ord(c) not in src_cmap)
    print("  源字體就沒有的字   %5d（%s%s）" % (len(gone), "".join(gone[:24]),
                                              "…" if len(gone) > 24 else ""))
    ov = cui & cdt
    print("  兩片重疊碼位       %5d%s"
          % (len(ov), "  ← 必須為 0，否則瀏覽器只會下載後宣告的那一片" if ov else "  ✓"))
    print("  完成，報告寫入 font_report.json；總計 %.2f MB"
          % sum(r["mb"] for r in report))


if __name__ == "__main__":
    main()
