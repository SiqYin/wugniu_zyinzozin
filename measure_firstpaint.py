# -*- coding: utf-8 -*-
"""實測字音查詢站「可見字」，產出 firstpaint.txt 供 make_font.py 使用。

原理與韻圖站的 measure_firstpaint.py 相同：把探針腳本注��模板副本，用無頭 Chrome
分別以三語載入，走訪整棵 DOM 但跳過 display:none / visibility:hidden 的子樹，取可見
文字的並集。差別有二：

  1. 韻圖站要量「展開韻圖之後」的字；本站結果區一開始就是空的，必須**真的跑一次查詢**
     （羅馬字查詢 + 漢字查詢）才量得到結果卡片裡的字。
  2. 介面文字是執行期由 i18n 字典填入的，靜態掃描 HTML 抓不到，必須靠瀏覽器實測。

另外本站的「音系說明」彈窗（showPhonology）與「來源說明」彈窗（showSourceInfo）都是
點擊才出現的，探針會順手把它們開起來再量一次。

改過介面文字之後重跑：
    python measure_firstpaint.py
"""
import io, os, re, sys, html, json, shutil, subprocess, threading, http.server, socketserver

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(HERE, "templates/index_static.html")

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    shutil.which("google-chrome"),
    shutil.which("chromium"),
]

# 取可見文字 + 依序觸發「開彈窗」「跑查詢」，最後把三段結果一起吐進 <pre>
PROBE = u"""
<script>
function __vis(el){
  var s='';
  (function w(n){
    if(n.nodeType===3){ s+=n.nodeValue; return; }
    if(n.nodeType===1){
      if(n.tagName==='SCRIPT'||n.tagName==='STYLE') return;
      var cs=getComputedStyle(n);
      if(cs.display==='none'||cs.visibility==='hidden') return;
      for(var i=0;i<n.childNodes.length;i++) w(n.childNodes[i]);
    }
  })(el);
  return s;
}
function __dump(out,tag){ out.push(tag+__vis(document.body)); }
function __fin(out){
  var p=document.createElement('pre'); p.id='FP';
  p.textContent='[VIS]'+out.join('[/VIS][VIS]')+'[/VIS]';
  document.documentElement.appendChild(p);
  document.title='OK';
}
setTimeout(function(){
  var out=[];
  try{
    __dump(out,'A');                                   // 初始畫面
    // 兩個說明彈窗
    ['showPhonology','showPhonologyWu','showPhonologyJa','showPhonologyEn',
     'showSourceInfo'].forEach(function(fn){
      if(typeof window[fn]==='function'){ try{ window[fn]('suhu'); }catch(e){} }
    });    __dump(out,'B');                                   // 彈窗打開後
    ['closePhonology','closePhonologyWu','closePhonologyJa','closePhonologyEn',
     'closeSourceInfo'].forEach(function(fn){
      if(typeof window[fn]==='function'){ try{ window[fn](); }catch(e){} }
    });
    // 拼音反查（羅馬字 → 漢字結果卡）：要先展開那個面板
    var tg=document.getElementById('pinyinLookupToggle');
    if(tg && typeof togglePinyinLookup==='function'){ try{ togglePinyinLookup(); }catch(e){} }
    var pi=document.getElementById('pinyinInput');
    if(pi){
      pi.value='ku5';
      if(typeof doPinyinLookup==='function'){ try{ doPinyinLookup(); }catch(e){} }
    }
    setTimeout(function(){
      __dump(out,'C');                                 // 羅馬字結果
      // 漢字查詢
      var ci=document.getElementById('charInput');
      if(ci){
        ci.value='話';
        if(typeof doSearch==='function'){ try{ doSearch(); }catch(e){} }
      }
      setTimeout(function(){ __dump(out,'D'); __fin(out); },3000);
    },3000);
  }catch(e){
    out.push('ERR:'+e);
    __fin(out);
  }
},2000);
</script>
"""


def find_chrome():
    for c in CHROME_CANDIDATES:
        if c and os.path.exists(c):
            return c
    print("找不到 Chrome，請自行設定 CHROME_CANDIDATES")
    sys.exit(1)


def serve(directory):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=directory, **k)

        def log_message(self, *a):
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), Quiet)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1], srv.shutdown


def static_only_chars():
    """DOM 探針量不到、但確實會顯示的字。

    探針走訪的是 body 的**文字節點**，所以有兩類字會漏掉：

      1. head 與屬性裡的文字：`<title>`、`placeholder=`、`alt=`、`aria-label=`。
      2. JS 裡的文案字串：錯誤提示、靜態說明（例如「未收錄」「錄音」這類三語字串）。

    漏掉的後果很實在：這些字不在介面片裡，瀏覽器就會為了它們去下載 2 MB 的字典片，
    分級等於失效（實測首屏就會請求 zy-dict.woff2）。所以在這裡補回來。
    """
    h = io.open(TPL, encoding="utf-8").read()
    s = set()

    for pat in (r'(?:placeholder|title|alt|value|aria-label)\s*=\s*"([^"]*)"',
                r"(?:placeholder|title|alt|value|aria-label)\s*=\s*'([^']*)'"):
        for m in re.finditer(pat, h):
            s.update(m.group(1))
    for m in re.finditer(r"<title[^>]*>(.*?)</title>", h, re.S):
        s.update(m.group(1))

    # script 裡帶中日文（或韓文）的引號字串：顯示用的文案
    body = h[h.find("<body"):]
    body = re.sub(r"<style[\s\S]*?</style>", " ", body)
    for m in re.finditer(r"'([^'\\\n]{2,60})'", body):
        lit = m.group(1)
        if re.search(u"[一-鿿぀-ヿ가-힯]", lit):
            s.update(lit)
            for u in re.findall(r"\\u([0-9a-fA-F]{4})", lit):
                s.add(chr(int(u, 16)))
    return s


def main():
    if not os.path.exists(TPL):
        print("找不到 templates/index_static.html")
        sys.exit(1)

    base = io.open(TPL, encoding="utf-8").read()
    probe_name = "__fp_probe.html"
    probe_path = os.path.join(HERE, probe_name)
    io.open(probe_path, "w", encoding="utf-8").write(
        base.replace("</body>", PROBE + "\n</body>"))

    chrome = find_chrome()
    port, shutdown = serve(HERE)
    union = set()
    try:
        for lang in ("wu", "en", "ja"):
            url = "http://127.0.0.1:%d/%s?lang=%s" % (port, probe_name, lang)
            out = subprocess.run(
                [chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
                 "--window-size=1400,1200", "--virtual-time-budget=20000",
                 "--dump-dom", url],
                capture_output=True, timeout=240).stdout.decode("utf-8", "replace")
            m = re.search(r'<pre id="FP">\[VIS\](.*?)\[/VIS\]</pre>', out, re.S)
            if not m:
                print("  ?lang=%-3s 探針沒回來" % lang)
                continue
            segs = html.unescape(m.group(1)).split("[/VIS][VIS]")
            counts = [len(set(s)) for s in segs]
            for s in segs:
                union |= set(s)
            print("  ?lang=%-3s 分段可見字 %s" % (lang, counts))
    finally:
        shutdown()
        os.remove(probe_path)

    n0 = len(union)
    union |= static_only_chars()
    # 介面隨時可能動態出現的符號：數字、拉丁、框線、標點、IPA 修飾字母。
    # 只取 Latin-1 的「可打印」段（U+0020–U+007E 與 U+00A0–U+00FF）；
    # U+007F 是 DEL、U+0080–U+009F 是 C1 控制字元，頁面上永遠不會出現，不放進字集。
    union |= {chr(c) for c in range(0x20, 0x7F)}
    union |= {chr(c) for c in range(0xA0, 0x100)}
    union |= set("▼▶■□●○◆◇·—–…「」『』（）《》〈〉〔〕【】、。，：；！？　・～×÷±≈"
                 "√°′″←→↑↓⇒⇔∀∃∈∉⊂⊃∪∩∅")
    union |= set("βʐɿʮᵝᶽɑɒɤɯɛe̞i̯ɪʊʌəɚœːˤ")
    union |= set("ǀǁǂǃˈˌ")
    union = {c for c in union if ord(c) >= 0x20 and c != "\x7f"
             and not (0x7F < ord(c) < 0xA0)}

    io.open(os.path.join(HERE, "firstpaint.txt"), "w", encoding="utf-8").write(
        "".join(sorted(union)))
    print("三語並集 %d 字，加安全邊際後 %d 字 → firstpaint.txt" % (n0, len(union)))


if __name__ == "__main__":
    main()
