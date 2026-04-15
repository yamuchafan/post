import base64
import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

WP_BASE = os.environ["WP_BASE_URL"].rstrip("/")
WP_USER = os.environ["WP_USER"]
WP_APP_PASSWORD = os.environ["WP_APP_PASSWORD"]
WP_CATEGORY_ID = int(os.environ["WP_CATEGORY_ID"])

STATE_PATH = Path("state/processed.json")
DRAFT_DIR = Path("drafts")
DRAFT_DIR.mkdir(parents=True, exist_ok=True)


def basic_token():
    return base64.b64encode(f"{WP_USER}:{WP_APP_PASSWORD}".encode()).decode()


def public_get_headers():
    return {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; yoruplus-bot/1.0; +https://yoruplus-navi.com/)"
    }


def auth_get_headers():
    return {
        "Authorization": f"Basic {basic_token()}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; yoruplus-bot/1.0; +https://yoruplus-navi.com/)"
    }


def auth_post_headers():
    return {
        "Authorization": f"Basic {basic_token()}",
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "Mozilla/5.0 (compatible; yoruplus-bot/1.0; +https://yoruplus-navi.com/)"
    }


def load_state():
    if not STATE_PATH.exists():
        return {"done_term_ids": []}

    data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    if "done_term_ids" not in data:
        data["done_term_ids"] = []
    return data


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def get_candidates():
    url = f"{WP_BASE}/wp-json/yoruplus/v1/actress-candidates"
    params = {
        "limit": 50,
        "min_count": 170,
    }
    r = requests.get(url, headers=public_get_headers(), params=params, timeout=60)

    if not r.ok:
        print("get_candidates failed")
        print("status:", r.status_code)
        print("body:", r.text[:1000])
        r.raise_for_status()

    data = r.json()

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        if "term_id" in data:
            return [data]

        if "data" in data and isinstance(data["data"], list):
            return data["data"]

    print("Unexpected candidates response type:", type(data).__name__)
    print("Response JSON:", json.dumps(data, ensure_ascii=False)[:2000])
    raise ValueError("actress-candidates response is not a list")


def wp_post_exists(post_slug):
    url = f"{WP_BASE}/wp-json/wp/v2/posts"
    params = {
        "slug": post_slug,
        "status": ["draft", "publish", "pending", "future", "private"],
        "context": "edit",
        "per_page": 5,
    }
    r = requests.get(url, headers=auth_get_headers(), params=params, timeout=60)

    if not r.ok:
        print("wp_post_exists failed")
        print("status:", r.status_code)
        print("body:", r.text[:1000])
        r.raise_for_status()

    data = r.json()
    return data[0] if data else None


def h(text):
    return html.escape(str(text), quote=True)


def genre_names(c):
    return [g["name"] for g in c.get("top_genres", []) if g.get("name")][:3]


def top_counts(c):
    genres = c.get("top_genres", [])
    total = int(c.get("count", 0))

    out = []
    for g in genres[:3]:
        name = g.get("name", "")
        cnt = int(g.get("count", 0))
        ratio = round((cnt / total) * 100) if total > 0 else 0
        out.append((name, cnt, ratio))
    return out


def detect_article_axis(c):
    genres = c.get("top_genres", [])
    joined = " / ".join([g.get("name", "") for g in genres[:5]])

    if any(k in joined for k in ["中出し", "顔射", "ぶっかけ", "アナル"]):
        return "hard"
    if any(k in joined for k in ["熟女", "人妻", "母", "叔母"]):
        return "jyukujo"
    if any(k in joined for k in ["痴女", "主観", "逆ナン", "レズ"]):
        return "character"
    if any(k in joined for k in ["フェラ", "手コキ"]):
        return "oral"
    if any(k in joined for k in ["美少女", "清楚", "スレンダー", "アイドル", "巨乳"]):
        return "bishoujo"
    return "mixed"


def build_intro(c):
    name = c["name"]
    count = int(c.get("count", 0))
    maker = (c.get("top_maker") or {}).get("name", "")
    gstats = top_counts(c)
    gnames = genre_names(c)

    g1 = gnames[0] if len(gnames) > 0 else "主要ジャンル"
    g2 = gnames[1] if len(gnames) > 1 else ""
    maker_text = f"、メーカーでは{maker}系の出演が多いです" if maker else ""

    ratio_text = ""
    if gstats:
        n1, c1, r1 = gstats[0]
        ratio_text = f"特に「{n1}」は{count}件中{c1}件と大部分をしめており、"

    if g2:
        return (
            f"{name}の作品を選ぶなら、雰囲気だけで探すよりも出演本数やジャンル傾向から入った方が失敗が無いです。"
            f"出演作は全{count}件あり、上位では「{g1}」「{g2}」が多く{maker_text}。"
            f"{ratio_text}どこから見始めるべきかを決めやすいタイプです。"
            f"この記事では、最初に押さえたいおすすめ3本と、向いている人・向いていない人、買って後悔しにくい選び方を絞って整理します。"
        )

    return (
        f"{name}の作品は、出演数が{count}件と多いため、一覧から順に見ていくだけでは選びにくい、後悔しやすい傾向があります。"
        f"まずは代表作と上位作品の傾向を把握しておくことで、自分に合う作品を絞り込みやすくなります。"
        f"この記事では、最初に確認したいおすすめ3本と、貴方と相性の合いやすい作品傾向をまとめます。"
    )


def build_for(c):
    name = c["name"]
    axis = detect_article_axis(c)
    gnames = genre_names(c)
    g1 = gnames[0] if len(gnames) > 0 else ""
    g2 = gnames[1] if len(gnames) > 1 else ""

    if axis == "hard":
        return f"{name}は、条件がはっきりした作品から入りたい人に向いています。特に「{g1}」や「{g2}」のように、入口となる条件を決めて探すと相性を判断しやすいです。"
    if axis == "bishoujo":
        return f"{name}は、見た目や雰囲気を重視して選びたい人に向いています。まず王道寄りの作品から入りたい人には比較的使いやすいです。"
    if axis == "oral":
        return f"{name}は、プレイ傾向を先に決めてから選びたい人に向いています。条件を絞りながら見たい人ほどミスマッチを減らしやすくなります。"
    if axis == "jyukujo":
        return f"{name}は、落ち着いた空気感や年上系の雰囲気を重視したい人に向いています。派手さより作品の相性で選びたい人に合います。"
    if axis == "character":
        return f"{name}は、役柄やキャラクター性の立ち方を重視して選びたい人に向いています。キャラ設定や女優の立ち位置から入りたい人向けです。"

    return f"{name}は、代表作で全体の作品傾向を確認してから条件で絞り込みたい人に向いています。"


def build_not(c):
    name = c["name"]
    axis = detect_article_axis(c)

    if axis == "hard":
        return f"一方で、まずは軽めの作品や雰囲気重視の作品から入りたい人には、{name}は最初の1本選びで好みが分かれる可能性があります。"
    if axis == "bishoujo":
        return f"反対に、強い条件や刺激を最優先で絞り込みたい人には、{name}は少し方向性が違って見える場合があります。"
    if axis == "oral":
        return f"逆に、作品全体の雰囲気や見た目を最優先で選びたい人には、{name}はやや条件寄りに感じることがあります。"
    if axis == "jyukujo":
        return f"若めの見た目や王道寄りの雰囲気から入りたい人には、{name}は最初の入口として好みが分かれる可能性があります。"
    if axis == "character":
        return f"まずは万人向けの作品から広く触れたい人には、{name}は少しギャップが立って見えることがあります。"

    return f"条件を決めずに一覧を流し見したい人は、最初から作品一覧へ行くより、先におすすめ3本を確認した方が選びやすくなります。"


def build_how(c):
    name = c["name"]
    count = int(c.get("count", 0))
    maker_bias = c.get("maker_bias", False)
    maker = (c.get("top_maker") or {}).get("name", "")
    gnames = genre_names(c)
    g1 = gnames[0] if len(gnames) > 0 else ""
    g2 = gnames[1] if len(gnames) > 1 else ""

    if maker_bias and maker:
        return f"{name}はメーカー傾向が比較的はっきりしているため、まず代表作を確認したあと、{maker}系の作品へ広げる方が後悔しにくいです。"

    if count >= 200:
        return f"{name}は作品数がかなり多いため、最初から一覧で探すよりも、まず「{g1}」や「{g2}」のような上位傾向を確認し、そのうえで代表作3本から入る方が探しやすいです。"

    if count >= 50:
        return f"{name}は代表作で作品全体、女優の雰囲気を確認したあと、上位ジャンルから絞りこみ検索がおすすめです。"

    return f"{name}は作品数が極端に多いタイプではないので、まずおすすめ3本を順に見てから一覧ページへ進む流れがいいです。"


def build_summary_box(c):
    name = c["name"]
    gnames = genre_names(c)
    g1 = gnames[0] if len(gnames) > 0 else "主要ジャンル"
    g2 = gnames[1] if len(gnames) > 1 else "次点ジャンル"

    return f"""
<div class="ypn-summary-box">
  <p class="ypn-summary-title">この記事で分かること</p>
  <ul class="ypn-summary-list">
    <li>{h(name)}を最初に見るなら、どの作品から入るべきか</li>
    <li>出演上位ジャンルである「{h(g1)}」「{h(g2)}」をどう見分けるか</li>
    <li>一通り見終わったあとに出演作品一覧ページでどう選ぶのか</li>
  </ul>
</div>
""".strip()


def build_pick_reason(c, pick, index):
    matched = pick.get("matched_genres", [])
    maker = pick.get("maker_name", "")
    g1 = matched[0] if len(matched) > 0 else ""
    g2 = matched[1] if len(matched) > 1 else ""

    if index == 1:
        if g1:
            return f"最初の1本として全体の雰囲気を掴みやすい作品です。特に「{g1}」寄りの入口として見やすく、まず良作かを判断したい人はここから入ると雰囲気をつかみやすくなります。"
        return "最初の1本として全体の雰囲気を掴みやすい作品です。まずは、作品相性を判断したい人はここから入ると流れが掴みやすくなります。"

    if index == 2:
        if g1 and maker:
            return f"1本目で合いそうだと感じた人が、次に作品傾向を確かめるのに向いている作品です。特に「{g1}」とメーカー傾向の両方を確認しやすく、作品比較の材料として使いやすい1本です。"
        if g1:
            return f"1本目で合いそうだと感じた人が、次に作品傾向を確かめるのに向いている作品です。特に「{g1}」寄りの見方をしたい人には比較材料になります。"
        return "1本目で合いそうだと感じた人が、次に作品傾向を確かめるのに向いている作品です。入口としての相性確認から一段進めたい人向けです。"

    if g1 or g2:
        joined = "」「".join([x for x in [g1, g2] if x])
        return f"3本目は比較用です。1本目・2本目と見比べることで、「{joined}」だけで入るべきか、少し違う方向まで含めて追うべきかを判断しやすくなります。"

    return "3本目は比較用です。1本目・2本目と見比べることで、どこまで作品軸を広げて追うべきかを判断しやすくなります。"


def build_pick_label(index):
    if index == 1:
        return "まずはここから"
    if index == 2:
        return "傾向確認用"
    return "作品比較用"


def build_picks_html(c):
    items = c.get("picks", [])[:3]
    if not items:
        return '<p class="ypn-empty">おすすめ候補は準備中です。</p>'

    parts = []
    for i, p in enumerate(items, start=1):
        title = h(p.get("title", f"おすすめ作品{i}"))
        url = h(p.get("url", "#"))
        reason = h(build_pick_reason(c, p, i))
        thumb_url = h(p.get("thumb_url", ""))
        date = h(p.get("date", ""))
        label = h(build_pick_label(i))

        image_html = ""
        if thumb_url:
            image_html = f"""
<div class="ypn-pick-thumb">
  <a href="{url}">
    <img src="{thumb_url}" alt="{title}">
  </a>
</div>
""".strip()

        meta_html = ""
        if date:
            meta_html = f'<div class="ypn-pick-date">配信日: {date}</div>'

        parts.append(f"""
<div class="ypn-pick-card">
  {image_html}
  <div class="ypn-pick-body">
    <div class="ypn-pick-label">{label}</div>
    <h3 class="ypn-pick-title">
      {i}. <a href="{url}">{title}</a>
    </h3>
    {meta_html}
    <p class="ypn-pick-reason">{reason}</p>
  </div>
</div>
""".strip())

    return "\n".join(parts)


def build_related_line(c, name, index):
    axis = detect_article_axis(c)

    if axis == "hard":
        lines = [
            f"{name}は、条件別で比較検討したいときの候補です。似た傾向の作品との違いを確認したい人に向いています。",
            f"{name}は、同じく条件を先に決めて比較したいときの候補です。どちらが入りやすいかを見比べやすくなります。",
            f"{name}は、近い傾向の中で別の入り口を探したい人向けの比較先です。"
        ]
    elif axis == "bishoujo":
        lines = [
            f"{name}は、雰囲気や見た目のまとまりで比較したいときの候補です。",
            f"{name}は、王道寄りの方向で比べたいときの比較先として使えます。",
            f"{name}は、近い空気感の中で相性差を見たい人向けです。"
        ]
    else:
        lines = [
            f"{name}は、近い系統の作品と比較したいときに押さえておきたい候補です。",
            f"{name}は、作品ごとの入り方や印象の違いを見比べたいときに比較しやすい1本です。",
            f"{name}は、相性の近い作品をあわせて検討したい人に向いています。"
        ]

    idx = min(index, len(lines) - 1)
    return lines[idx]


def build_related_html(c):
    items = c.get("related", [])[:3]
    if not items:
        return '<p class="ypn-empty">比較候補は今後追加予定です。</p>'

    parts = ['<p class="ypn-related-intro">近い方向性で比較するなら、次の女優も候補に入ります。違いまで含めて見たいときの作品の比較先として使えます。</p>']
    for idx, r in enumerate(items):
        name = h(r["name"])
        url = h(r["url"])
        line = h(build_related_line(c, r["name"], idx))
        parts.append(f"""
<div class="ypn-related-card">
  <p class="ypn-related-name"><a href="{url}">{name}</a></p>
  <p class="ypn-related-text">{line}</p>
</div>
""".strip())
    return "\n".join(parts)


def build_article_html(c):
    name = h(c["name"])
    actress_url = h(c["actress_url"])

    return f"""
<div class="ypn-seo-article">
  {build_summary_box(c)}

  <div class="article-entry">

  <h2>{name}を初めて見る人が最初に押さえたいポイント</h2>
  <p>{h(build_intro(c))}</p>
  <p>{name}の作品を一覧で確認したい方は、<a href="{actress_url}">{name}の出演作品一覧ページ</a>もあわせて確認してください。</p>

  <h2>{name}の作品が向いている人・向いていない人</h2>
  <h3>{name}の作品が向いている人</h3>
  <p>{h(build_for(c))}</p>

  <h3>{name}の作品が向いていない人</h3>
  <p>{h(build_not(c))}</p>

  <h2>{name}を最初に見るならおすすめしたい3本</h2>
  {build_picks_html(c)}

  <h2>{name}の作品選びで失敗しにくい見方</h2>
  <p>{h(build_how(c))}</p>

  <h2>同系統で比較したい女優</h2>
  {build_related_html(c)}

  <h2>{name}を選ぶときの結論</h2>
  <p>{name}は、最初に代表作で全体の傾向を確認し、その後に出演作品一覧ページで絞り込む見方がもっとも外しにくいです。まず好みの1本を決めたい人向けの入口記事として使いやすいタイプです。</p>

  <h2>{name}の出演作品一覧から探したい方へ</h2>
  <p>作品一覧、上位ジャンル、メーカー傾向までまとめて見たい方は、<a href="{actress_url}">{name}の出演作品一覧ページ</a>を確認してください。</p>

</div>


def build_excerpt(c):
    return build_intro(c)[:120]


def create_wp_draft(c, content_html):
    term_id = int(c["term_id"])
    post_slug = f"seo-actress-{term_id}"

    existing = wp_post_exists(post_slug)

    first_pick = c.get("picks", [{}])[0] if c.get("picks") else {}
    featured_media = int(first_pick.get("thumb_id", 0) or 0)

    payload = {
        "title": f"{c['name']}のおすすめ作品3選｜初めて見る人向けに選び方も解説",
        "slug": post_slug,
        "status": "draft",
        "content": content_html,
        "excerpt": build_excerpt(c),
        "categories": [WP_CATEGORY_ID],
    }

    if featured_media > 0:
        payload["featured_media"] = featured_media

    if existing:
        post_id = existing["id"]
        url = f"{WP_BASE}/wp-json/wp/v2/posts/{post_id}"
    else:
        url = f"{WP_BASE}/wp-json/wp/v2/posts"

    r = requests.post(url, headers=auth_post_headers(), json=payload, timeout=60)

    if not r.ok:
        print("create_wp_draft failed")
        print("status:", r.status_code)
        print("body:", r.text[:1000])
        r.raise_for_status()

    return r.json()


def touch_actress(c):
    url = f"{WP_BASE}/wp-json/yoruplus/v1/actress-touch/{c['term_id']}"
    payload = {
        "article_url": "",
        "article_title": "",
        "checked_at": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d"),
    }

    r = requests.post(url, headers=auth_post_headers(), json=payload, timeout=60)

    if not r.ok:
        print("touch_actress failed")
        print("status:", r.status_code)
        print("body:", r.text[:1000])
        r.raise_for_status()

    return r.json()


def main():
    state = load_state()
    done_term_ids = set(str(x) for x in state.get("done_term_ids", []))

    candidates = get_candidates()

    if not isinstance(candidates, list):
        print("Candidates is not a list:", type(candidates).__name__)
        raise ValueError("candidates must be a list")

    chosen = None
    for c in candidates:
        if not isinstance(c, dict):
            print("Invalid candidate item:", c)
            continue

        if "term_id" not in c:
            print("Candidate missing term_id:", c)
            continue

        term_id = str(c["term_id"])
        post_slug = f"seo-actress-{c['term_id']}"

        if term_id in done_term_ids:
            continue

        if wp_post_exists(post_slug):
            done_term_ids.add(term_id)
            continue

        chosen = c
        break

    if not chosen:
        print("No candidate.")
        save_state({"done_term_ids": sorted(done_term_ids, key=lambda x: int(x))})
        return

    content_html = build_article_html(chosen)

    out_file = DRAFT_DIR / f"{datetime.now().date().isoformat()}-{chosen['term_id']}.html"
    out_file.write_text(content_html, encoding="utf-8")

    create_wp_draft(chosen, content_html)
    touch_actress(chosen)

    done_term_ids.add(str(chosen["term_id"]))
    save_state({"done_term_ids": sorted(done_term_ids, key=lambda x: int(x))})

    print(f"Draft created for: {chosen['name']} (term_id={chosen['term_id']})")


if __name__ == "__main__":
    main()
