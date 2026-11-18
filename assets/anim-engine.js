/* 408 真题 · 动画公共引擎（与 kmp demo 同款交互：步进/自动播放/日志/序号带/结果卡）
 *
 * 用法（anim/{id}.html 内）：
 *   AW.init({
 *     title: '标题', subtitle: '副标题（可含 <code>）',
 *     counterLabel: '已比较',            // 计数 chip 文案（默认「步数」）
 *     snaps: [...],                     // 每步一个快照对象（见下）
 *     build:   (stage) => {...},        // 可选：建立持久 DOM（算法类动画）
 *     render:  (stage, sn, i, dir) => {...}, // 可选：每步更新（不给则默认 stage.innerHTML = sn.html）
 *     result:  { big: '10 次', html: '结论说明…' },  // 可选：到达末步时弹出的结果卡
 *   });
 *
 * snaps[i] 字段（全部可选，按需给）：
 *   cls: 'ok'|'miss'|'shift'|'done'|'step'   —— 状态栏与日志配色
 *   tag: '相等 ✓'                            —— 状态栏彩色小标签文案
 *   log: '第 3 次比较：…'                     —— 日志一行 + 状态栏正文
 *   count: 3                                 —— 计数 chip 数值
 *   ribbon: {k:3, ok:true}                   —— 序号带点亮一个圆点（ok→✓绿，否则✗红）
 *   done: true                               —— 标记为最终步（引擎停播）
 */
(function(){
  var DELAYS = [1400, 1000, 700, 450, 250];
  var E = {};

  function $(id){ return document.getElementById(id); }
  function el(tag, cls, html){
    var d = document.createElement(tag);
    if(cls) d.className = cls;
    if(html != null) d.innerHTML = html;
    return d;
  }

  /* 只转义「不像合法 HTML 标签」的裸 <。题面/推理文本里常出现 (-1<x<1)、$x<0$ 这类
   * 数学式，直接 innerHTML 会被浏览器当标签解析，整段内容被吞。真标签
   * （<b>、</p>、<img src="…">、<!--…-->）原样保留；转义后的 &lt; 在 DOM 文本里
   * 还原为 <，KaTeX auto-render 读的是文本节点，公式照常渲染。 */
  function safeHtml(s){
    return String(s == null ? '' : s).replace(/</g, function(m, off, str){
      var rest = str.slice(off);
      if (/^<\/?[a-zA-Z][a-zA-Z0-9-]*(?:\s[^<>]*)?\/?>/.test(rest) || /^<!/.test(rest)) return m;
      return '&lt;';
    });
  }

  /* 对节点做 KaTeX 渲染（页面未加载 auto-render 时静默跳过）。
   * 用于日志/状态栏/标题/结果卡等引擎自绘区域，snaps[].log 里的 $x\ge0$ 不再裸显。 */
  function texify(node){
    if (node && window.renderMathInElement) {
      try {
        window.renderMathInElement(node, {
          delimiters: [{ left: '$$', right: '$$', display: true }, { left: '$', right: '$', display: false }],
          throwOnError: false,
        });
      } catch (e) {}
    }
  }

  function render(cur, animate){
    var sn = E.snaps[cur];
    if(!animate){ E.stage.classList.add('notrans'); }
    if(E.render){ E.render(E.stage, sn, cur, animate); }
    else if(sn.html != null){ E.stage.innerHTML = safeHtml(sn.html); }
    texify(E.stage);
    if(!animate){ void E.stage.offsetWidth; E.stage.classList.remove('notrans'); }

    E.count.innerHTML = E.counterLabel + ' <span>' + (sn.count != null ? sn.count : cur) + '</span>';
    if(cur === 0 && !sn.log){
      E.status.textContent = E.introText;
    } else {
      var cls = sn.cls || 'step';
      var tag = sn.tag ? '<span class="tag t-' + cls + '">' + sn.tag + '</span>' : '';
      E.status.innerHTML = tag + safeHtml(sn.log || '');
      texify(E.status);
    }
    // 日志
    if(cur === 0){
      E.log.innerHTML = '<div class="aw-log-line">（尚未开始）</div>';
      E.ribbon.innerHTML = '<span style="font-size:12.5px;color:#94a3b8">随演示逐个点亮…</span>';
    } else {
      var d = el('div', 'aw-log-line ' + (sn.cls || 'step'), safeHtml(sn.log || ''));
      E.log.appendChild(d);
      texify(d);
      E.log.scrollTop = E.log.scrollHeight;
      if(sn.ribbon){
        var c = el('div', 'aw-chip pop ' + (sn.ribbon.ok ? 'ok' : 'miss'));
        c.innerHTML = (sn.ribbon.ok ? '✓' : '✗') + '<em>第' + sn.ribbon.k + '</em>';
        var placeholder = E.ribbon.querySelector('span');
        if(placeholder) placeholder.remove();
        E.ribbon.appendChild(c);
      }
    }
    if(sn.done && E.result){
      E.big.textContent = E.result.big;
      E.desc.innerHTML = safeHtml(E.result.html);
      E.resultBox.classList.add('show');
      texify(E.resultBox);
    }
    if(cur >= E.snaps.length - 1) stopPlay();
  }

  function goto(t, animate){
    t = Math.max(0, Math.min(E.snaps.length - 1, t));
    if(t === E.cur && E.built) return; // 已在该步（末步重复点击），不重复渲染
    E.built = true;
    var jump = Math.abs(t - E.cur) > 1;
    E.cur = t;
    if(E.cur === 0){
      // 重置：清空日志并整体重画
      if(E.build) E.build(E.stage);
      render(0, false);
      E.log.innerHTML = '<div class="aw-log-line">（尚未开始）</div>';
      E.ribbon.innerHTML = '<span style="font-size:12.5px;color:#94a3b8">随演示逐个点亮…</span>';
      E.resultBox.classList.remove('show');
      return;
    }
    render(E.cur, animate && !jump);
  }

  function stopPlay(){
    if(E.timer){ clearInterval(E.timer); E.timer = null; }
    E.playBtn.textContent = '▶ 播放';
  }
  function togglePlay(){
    if(E.timer){ stopPlay(); return; }
    if(E.cur >= E.snaps.length - 1) goto(0, false);
    E.playBtn.textContent = '⏸ 暂停';
    E.timer = setInterval(function(){
      if(E.cur >= E.snaps.length - 1) stopPlay();
      else goto(E.cur + 1);
    }, DELAYS[+E.speed.value - 1]);
  }

  /* ---- 题目头自动注入：按自身 URL 从题库拉取题干/选项/答案 ---- */
  function loadQuestionHeader(root){
    try {
      var m = (location.pathname || '').match(/anim\/([A-Za-z0-9._-]+)\.html/);
      if (!m) return;
      var id = m[1];
      var ym = id.match(/(\d{4})/);
      if (!ym) return;
      fetch('../data/questions/' + ym[1] + '.json').then(function(r){
        return r.ok ? r.json() : Promise.reject(new Error('http ' + r.status));
      }).then(function(d){
        var qs = Array.isArray(d) ? d : (d.questions || []);
        var q = null;
        for (var i = 0; i < qs.length; i++) if (qs[i].id === id) { q = qs[i]; break; }
        if (!q) return;
        // 题库 stem/options 里有两种历史写法：HTML 的 <img src="images/…">（含 content-images/）
        // 与 markdown 的 ![](images/…png)。统一转成路径改写到 ../images/ 的 <img>。
        // 最后过一道 safeHtml：题干数学式里的裸 <（如 (-1<x<1)）不再破坏 DOM 结构。
        var fixHtml = function(h){
          var s = String(h || '');
          s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g, function(_, alt, src){
            return '<img src="' + src.replace(/"/g, '%22') + '" alt="' + alt.replace(/"/g, '&quot;') + '">';
          });
          s = s.replace(/src=["'](\/?content-images\/)/g, 'src="../images/');
          s = s.replace(/src=["'](images\/)/g, 'src="../images/');
          return safeHtml(s);
        };
        var opts = '';
        if (q.options && q.options.length) {
          opts = '<div class="aw-qopts">' + q.options.map(function(o){
            return '<div class="aw-qopt"><span class="aw-qletter">' + o.letter +
              '</span><span class="aw-qtext">' + fixHtml(o.html || '') + '</span></div>';
          }).join('') + '</div>';
        }
        var tags = (q.tags || []).map(function(t){ return '<span class="aw-qtag">' + t + '</span>'; }).join(' ');
        // 参考答案：裸 TeX 公式必须整体进 $…$，绝不能按字符数截断——
        // 截断会把 \mathrm/\mathcal 切成 \math 残片，KaTeX 失败后原样露码。
        var ansRaw = String(q.answer == null ? '' : q.answer).trim().replace(/\r\n?/g, ' ');
        var ansTxt;
        if (q.answerLetter) {
          ansTxt = '<b>' + q.answerLetter + '</b>';
        } else if (!ansRaw || ansRaw === '略') {
          ansTxt = '见下方结论卡';
        } else if (ansRaw.indexOf('$') >= 0) {
          ansTxt = '<b>' + safeHtml(ansRaw) + '</b>';          // 题库已带 $…$ 定界符：原样交给渲染
        } else if (/[\\^_{}]/.test(ansRaw)) {
          ansTxt = '<b>$' + ansRaw + '$</b>';                  // 裸 TeX：整体包裹
        } else {
          ansTxt = '<b>' + safeHtml(ansRaw.length > 80 ? ansRaw.slice(0, 80) + '…' : ansRaw) + '</b>';
        }
        var box = document.createElement('details');
        box.className = 'aw-question';
        // 站点规范：高屏（舞台卡锁视口高的同一断点）下题目卡默认折叠，避免把舞台顶出首屏
        box.open = !(window.matchMedia &&
          window.matchMedia('(min-width: 1200px) and (min-height: 860px)').matches);
        box.innerHTML = '<summary>📋 题目与选项 · ' + id + '（全屏时也在）</summary>' +
          '<div class="aw-qbody">' +
          '<div class="aw-qstem">' + fixHtml(q.stemHtml || q.stem || '') + '</div>' + opts +
          '<div class="aw-qmeta">参考答案：' + ansTxt + (tags ? '　' + tags : '') + '</div>' +
          '</div>';
        root.insertBefore(box, root.firstChild);
        // 图片加载失败（图源缺失）时换成占位说明，不显示破图图标
        var imgs = box.querySelectorAll('img');
        for (var im = 0; im < imgs.length; im++) {
          imgs[im].addEventListener('error', function(){
            var ph = document.createElement('span');
            ph.className = 'aw-img-missing';
            ph.textContent = '（配图缺失：' + (this.getAttribute('src') || '') + '）';
            if (this.parentNode) this.parentNode.replaceChild(ph, this);
          });
        }
        texify(box);
      }).catch(function(){ /* file:// 打开或离线时静默跳过 */ });
    } catch (e) {}
  }

  function init(cfg){
    E.cfg = cfg;
    E.snaps = cfg.snaps;
    E.render = cfg.render || null;
    E.build = cfg.build || null;
    E.result = cfg.result || null;
    E.counterLabel = cfg.counterLabel || '步数';
    E.cur = 0; E.timer = null;

    var root = document.querySelector('.aw');
    root.innerHTML =
      '<h1>' + (cfg.title || '') + '</h1>' +
      '<div class="sub">' + (cfg.subtitle || '') + '</div>' +
      '<div class="aw-grid">' +
        '<div class="aw-main">' +
          '<div class="aw-card aw-stage-card">' +
            '<div class="aw-stage" id="awStage"></div>' +
            '<div class="aw-status" id="awStatus"></div>' +
            '<div class="aw-hint">快捷键：← 上一步　→ 下一步　空格 播放/暂停</div>' +
          '</div>' +
        '</div>' +
        '<aside class="aw-side">' +
          '<div id="awResult" class="aw-result"><div class="big"></div><div class="desc"></div></div>' +
          '<div class="aw-card aw-controls">' +
            '<button id="awReset" class="warn">⏮ 重置</button>' +
            '<button id="awPrev">◀ 上一步</button>' +
            '<button id="awPlay" class="primary">▶ 播放</button>' +
            '<button id="awNext">下一步 ▶</button>' +
            '<button id="awEnd" class="warn">⏭ 看结果</button>' +
            '<div class="aw-speed"><span>慢</span><input type="range" id="awSpeed" min="1" max="5" value="3" step="1"><span>快</span></div>' +
            '<div class="aw-counter" id="awCount"></div>' +
          '</div>' +
          '<div class="aw-card aw-sidecard">' +
            '<div class="aw-panel-title" id="awRibbonTitle">序号（✓ 对 / ✗ 错）</div>' +
            '<div class="aw-ribbon" id="awRibbon"></div>' +
            '<div class="aw-panel-title" style="margin-top:12px">过程日志</div>' +
            '<div id="awLog"></div>' +
          '</div>' +
        '</aside>' +
      '</div>';
    loadQuestionHeader(root);

    E.stage = $('awStage'); E.status = $('awStatus'); E.log = $('awLog');
    E.ribbon = $('awRibbon'); E.count = $('awCount'); E.resultBox = $('awResult');
    E.big = E.resultBox.querySelector('.big'); E.desc = E.resultBox.querySelector('.desc');
    E.speed = $('awSpeed'); E.playBtn = $('awPlay');
    E.introText = cfg.intro || '点击「▶ 播放」或「下一步」开始演示。';
    if(cfg.ribbonTitle) $('awRibbonTitle').textContent = cfg.ribbonTitle;
    // 标题/副标题常含 $…$ 公式（如 m2-2012-20 的标题），引擎负责渲染
    texify(root.querySelector('h1'));
    texify(root.querySelector('.sub'));

    $('awNext').onclick = function(){ stopPlay(); goto(E.cur + 1); };
    $('awPrev').onclick = function(){ stopPlay(); goto(E.cur - 1); };
    $('awReset').onclick = function(){ stopPlay(); goto(0, false); };
    $('awEnd').onclick = function(){ stopPlay(); goto(E.snaps.length - 1, false); };
    E.playBtn.onclick = togglePlay;
    E.speed.oninput = function(){ if(E.timer){ stopPlay(); togglePlay(); } };
    document.addEventListener('keydown', function(e){
      if(e.key === 'ArrowRight'){ stopPlay(); goto(E.cur + 1); }
      else if(e.key === 'ArrowLeft'){ stopPlay(); goto(E.cur - 1); }
      else if(e.key === ' '){ e.preventDefault(); togglePlay(); }
    });

    goto(0, false);
  }

  /* ---- 题面常用的渲染小工具 ---- */

  // 一行字符格：chars=['a','b',...], classes=['ok','hit','miss',...]（可含 ''）,
  // ptrMap={3:'i=3'} → 第 3 格上方显示指针
  function cellRow(chars, classes, ptrMap, idxStart){
    var row = el('div', 'aw-cells');
    chars.forEach(function(ch, i){
      var col = el('div', 'aw-col');
      col.appendChild(el('div', 'aw-ptr', (ptrMap && ptrMap[i + 1]) || ''));
      col.appendChild(el('div', 'aw-box' + (classes && classes[i] ? ' ' + classes[i] : ''), String(ch)));
      col.appendChild(el('div', 'aw-idx', String((idxStart || 1) + i)));
      row.appendChild(col);
    });
    return row;
  }

  // 把 wrapper 平移到第 idx 格（pitch = 格宽 + 间距，默认 48）
  function shiftTo(wrapperEl, idx, pitch){
    wrapperEl.style.transform = 'translateX(' + ((idx - 1) * (pitch || 48)) + 'px)';
  }

  window.AW = { init: init, el: el, cellRow: cellRow, shiftTo: shiftTo };
})();
