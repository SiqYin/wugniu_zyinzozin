# -*- coding: utf-8 -*-
"""把 font_report.json 的三片／兩片字體接進兩份模板，寫法與韻圖站 generate_html.py 一致。

做四件事：
  1. 在 <style> 最前面插入 @font-face（由 font_report.json 生成unicode-range）
  2. 插入 :root 的 --wk / --ui / --ipa / --mono 四个字体栈變數
  3. 把 body 與各處字體宣告換成 var(--…)，並保留系統襯線為回退
  4. 兩份模板（index_static.html 線上部署、index.html Flask 版）同步

用法：python inject_font.py
（改過介面文案後：measure_firstpaint.py → make_font.py → inject_font.py）
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT = os.path.join(HERE, "font_report.json")
TARGETS = [os.path.join(HERE, "templates", "index_static.html"),
           os.path.join(HERE, "templates", "index.html")]

# 與韻圖站同樣的處理：霞鶩文楷（自托管兩片）→ 幾個「系統自帶、專門收擴展 B 區」的字型
# → 通用襯線族。霞鶩文楷沒有的 107 個擴展 B 生僻字靠這一層顯示。
EXTB = ('"SimSun-ExtB","MingLiU-ExtB","MiSans L3","I.Ming",'
        '"HanaMinB","BabelStone Han",')

VARS = """
:root{
--wk:"LXGW WenKai",%(extb)s"Songti SC","Source Han Serif TC","Noto Serif CJK TC",Georgia,"SimSun",serif;
--ui:"LXGW WenKai",%(extb)ssystem-ui,-apple-system,"Segoe UI","Microsoft JhengHei","Microsoft YaHei",sans-serif;
--ipa:"LXGW WenKai",%(extb)s"Times New Roman","Noto Serif",serif;
--mono:"LXGW WenKai",%(extb)s"SFMono-Regular",Consolas,"Courier New",monospace}
""" % {"extb": EXTB}

# 舊字體棧 → CSS 變數
STACK_MAP = [
    # body 的襯線栈
    ('"Noto Serif TC", "Source Han Serif TC", "SimSun", serif', 'var(--wk)'),
    # 羅馬字／音值用的 Times 栈（含無空格變體）
    ('"Times New Roman", "Noto Serif", serif', 'var(--ipa)'),
    ("'Times New Roman','Noto Serif',serif", 'var(--ipa)'),
    ('"Times New Roman","Noto Serif",serif', 'var(--ipa)'),
]


def font_face_css():
    rep = json.load(open(REPORT, encoding="utf-8"))
    v = rep["version"]
    out = []
    for it in rep["faces"]:
        # local() 優先：使用者電腦已安裝霞鶩文楷就直接用，不必下載
        out.append(
            '@font-face{font-family:"%s";font-style:normal;font-weight:400;'
            'font-display:swap;src:local("LXGW WenKai"),local("霞鶩文楷"),'
            'url("fonts/%s?v=%s") format("woff2");unicode-range:%s}'
            % (it["family"], it["file"], v, ",".join(it["range"])))
    return "\n".join(out)


def inject(path):
    s = open(path, encoding="utf-8").read()
    orig = s

    # 1) 拆掉先前注入過的區塊（讓腳本可重複執行）
    s = re.sub(r"@font-face\{font-family:\"LXGW WenKai\"[^\n]*\}\n?", "", s)
    s = re.sub(r":root\{\n--wk:\"LXGW WenKai\"[^\n]*\n", "", s)

    # 2) 字體棧換成變數
    for a, b in STACK_MAP:
        s = s.replace(a, b)

    # 3) 在 <style> 後插 @font-face + 變數
    assert "<style>" in s, path
    s = s.replace("<style>", "<style>\n" + font_face_css() + "\n" + VARS, 1)

    # 4) .gender-hanzi 的 fallback 也要換（它原本直接寫死襯線栈）
    s = s.replace('var(--ui-font, "Noto Serif TC", "Source Han Serif TC", "SimSun", serif)',
                  'var(--wk)')

    if s == orig:
        print("  ! %s 沒有變化" % os.path.basename(path))
        return False
    open(path, "w", encoding="utf-8").write(s)
    n = s.count("@font-face")
    print("  ✓ %-20s @font-face %d 處" % (os.path.basename(path), n))
    return True


def main():
    if not os.path.exists(REPORT):
        print("找不到 font_report.json，請先跑 make_font.py")
        sys.exit(1)
    for t in TARGETS:
        if not os.path.exists(t):
            print("  ! 缺少", t)
            continue
        inject(t)


if __name__ == "__main__":
    main()
