import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import html

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

    # 旧形式にも対応
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

    return r.json()


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
    names = []
    for g in c.get("top_genres", []):
        name = (g.get("name") or "").strip()
        if not name:
            continue

        # 文章で使いにくいものを除外
        ng_words = [
            "ベスト", "総集編", "単体作品", "独占配信", "配信専用",
            "4時間", "8時間", "16時間", "Blu-ray", "VR", "ハイビジョン"
        ]
        if any(w in name for w in ng_words):
            continue

        # 複合タグを優先しすぎない
        if " " in name:
            continue

        names.append(name)

    return names[:3]


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

    # 強めを先に判定
    if any(k in joined for k in ["中出し", "顔射", "ぶっかけ", "アナル"]):
        return "hard"
    if any(k in joined for k in ["熟女", "人妻", "母", "叔母"]):
        return "jyukujo"
    if any(k in joined for k in ["痴女", "主観", "逆ナン", "レズ"]):
        return "character"
    if any(k in joined for k in ["フェラ", "手コキ"]):
        return "oral"
    if any(k in joined for k in ["美少女", "清楚", "スレンダー", "アイドル"]):
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
    maker_text = f"、メーカーでは{maker}系の比重も見えます" if maker else ""

    ratio_text = ""
    if gstats:
        n1, c1, r1 = gstats[0]
        ratio_text = f"特に「{n1}」は{count}件中{c1}件と比率が高く、"

    if g2:
        return (
            f"{name}の作品を選ぶなら、雰囲気だけで探すよりも出演本数やジャンル傾向から入った方が失敗しにくくなります。"
            f"出演作は全{count}件あり、上位では「{g1}」「{g2}」が目立ち{maker_text}。"
            f"{ratio_text}どこから見始めるべきかを決めやすいタイプです。"
            f"この記事では、最初に押さえたいおすすめ3本と、向いている人・向いていない人、失敗しにくい選び方を絞って整理します。"
        )

    return (
        f"{name}の作品は、出演数が{count}件と多く、最初の入口を決めずに一覧から入ると迷いやすいタイプです。"
        f"そのため、まずは代表作と上位傾向を確認してから絞り込む方が失敗しにくくなります。"
        f"この記事では、最初に見ておきたいおすすめ3本と、相性を判断しやすい見方をまとめます。"
    )


def build_for(c):
    name = c["name"]
    axis = detect_article_axis(c)
    gnames = genre_names(c)
    g1 = gnames[0] if len(gnames) > 0 else ""
    g2 = gnames[1] if len(gnames) > 1 else ""

    if axis == "hard":
        return f"{name}は、やや強めの方向性を含めて選びたい人に向いています。特に「{g1}」や「{g2}」のように、分かりやすい条件から入ると相性を判断しやすいです。"
    if axis == "bishoujo":
        return f"{name}は、見た目や雰囲気のまとまりを重視して選びたい人に向いています。まずは王道寄りの作品から確認したい人には入りやすいタイプです。"
    if axis == "oral":
        return f"{name}は、プレイ傾向を先に決めてから選びたい人に向いています。条件を先に固めたい人ほど迷いを減らしやすいです。"
    if axis == "jyukujo":
        return f"{name}は、落ち着いた空気感や年上系の雰囲気を重視したい人に向いています。派手さより相性で選びたい人に合います。"
    if axis == "character":
        return f"{name}は、役柄やキャラクター性の立ち方を重視して選びたい人に向いています。雰囲気より設定から入りたい人に使いやすいタイプです。"

    return f"{name}は、代表作で全体の傾向を確認してから条件で絞り込みたい人に向いています。"


def build_not(c):
    name = c["name"]
    axis = detect_article_axis(c)

    if axis == "hard":
        return f"反対に、まずは軽めの作品や雰囲気重視の作品から入りたい人には、{name}は最初の1本選びで好みが分かれる可能性があります。"
    if axis == "bishoujo":
        return f"一方で、強い条件や刺激を最優先で絞り込みたい人には、{name}は少し方向性が違って見える場合があります。"
    if axis == "oral":
        return f"逆に、作品全体の雰囲気や見た目のまとまりを最優先で選びたい人には、{name}は入り口としてやや条件寄りに感じることがあります。"
    if axis == "jyukujo":
        return f"若めの見た目や王道寄りの作品から入りたい人には、{name}は最初の入口として好みが分かれる可能性があります。"
    if axis == "character":
        return f"まずは万人向けの作品から広く触れたい人には、{name}は少し方向性が立って見えることがあります。"

    return f"条件を決めずに一覧を流し見したい人は、最初から作品一覧へ行くより、先におすすめ3本から相性を確認した方が判断しやすくなります。"


def build_how(c):
    name = c["name"]
    count = int(c.get("count", 0))
    maker_bias = c.get("maker_bias", False)
    maker = (c.get("top_maker") or {}).get("name", "")
    gnames = genre_names(c)
    g1 = gnames[0] if len(gnames) > 0 else ""
    g2 = gnames[1] if len(gnames) > 1 else ""

    if maker_bias and maker:
        return f"{name}はメーカー傾向が比較的はっきりしているため、まず代表作を確認したあと、{maker}系の作品へ広げる見方が失敗しにくいです。"

    if count >= 200:
        return f"{name}は作品数がかなり多いため、最初から一覧で探すよりも、まず「{g1}」や「{g2}」のような上位傾向を確認し、そのうえで代表作3本から入る方が効率的です。"

    if count >= 50:
        return f"{name}は代表作で全体の雰囲気を確認したあと、上位ジャンルを軸に絞り込む見方が合っています。"

    return f"{name}は作品数が極端に多いタイプではないので、まずおすすめ3本を順に見てから一覧ページへ進む流れで十分です。"


def build_pick_reason(c, index):
    axis = detect_article_axis(c)
    gnames = genre_names(c)
    g1 = gnames[0] if len(gnames) > 0 else "上位傾向"
    g2 = gnames[1] if len(gnames) > 1 else "別方向"

    if index == 1:
        return f"最初の1本として全体の雰囲気を掴みやすい作品です。まず相性判断をしたい人はここから入ると流れが分かりやすくなります。"
    if index == 2:
        return f"1本目で合いそうだと感じた人が、次に傾向を確かめるのに向いている作品です。特に「{g1}」寄りの見方をしたい人には比較材料になります。"
    return f"3本目は比較用です。1本目・2本目と見比べることで、{g1}だけで入るべきか、少し違う方向まで含めて追うべきかを判断しやすくなります。"


def build_picks_html(c):
    items = c.get("picks", [])[:3]
    if not items:
        return "<p>おすすめ候補は準備中です。</p>"

    parts = []
    for i, p in enumerate(items, start=1):
        title = h(p.get("title", f"おすすめ作品{i}"))
        url = h(p.get("url", "#"))
        reason = h(build_pick_reason(c, i))
        parts.append(
            f"<h3>{i}. <a href=\"{url}\">{title}</a></h3>"
            f"<p>{reason}</p>"
        )
    return "\n".join(parts)


def build_related_html(c):
    items = c.get("related", [])[:3]
    if not items:
        return "<p>比較候補は今後追加予定です。</p>"

    intro = "<p>近い方向性で比較するなら、次の女優も候補に入ります。違いまで含めて見たいときの比較先として使えます。</p>"
    lis = []
    for r in items:
        lis.append(f"<li><a href=\"{h(r['url'])}\">{h(r['name'])}</a></li>")
    return intro + "<ul>\n" + "\n".join(lis) + "\n</ul>"


def build_article_html(c):
    name = h(c["name"])
    actress_url = h(c["actress_url"])

    return f"""
<h2>導入</h2>
<p>{h(build_intro(c))}</p>
<p>出演作品を一覧で確認したい方は、<a href="{actress_url}">{name}の出演作品一覧ページ</a>もあわせて確認してください。</p>

<h2>{name}が向いている人</h2>
<p>{h(build_for(c))}</p>

<h2>{name}が向いていない人</h2>
<p>{h(build_not(c))}</p>

<h2>まず見るべきおすすめ3本</h2>
{build_picks_html(c)}

<h2>失敗しにくい選び方</h2>
<p>{h(build_how(c))}</p>

<h2>同系統で比較したい女優</h2>
{build_related_html(c)}

<h2>総評</h2>
<p>{name}は、最初に代表作で全体の傾向を確認し、その後に出演作品一覧ページで絞り込む見方がもっとも失敗しにくいタイプです。まず1本を決めたい人向けの入口記事として使うのが適しています。</p>

<h2>出演作品一覧はこちら</h2>
<p>作品一覧、上位ジャンル、メーカー傾向までまとめて見たい方は、<a href="{actress_url}">{name}の出演作品一覧ページ</a>を確認してください。</p>
""".strip()


def create_wp_draft(c, content_html):
    term_id = int(c["term_id"])
    post_slug = f"seo-actress-{term_id}"

    existing = wp_post_exists(post_slug)

    payload = {
        "title": f"{c['name']}のおすすめ作品3選｜初めて見る人向けに選び方も解説",
        "slug": post_slug,
        "status": "draft",
        "content": content_html,
        "categories": [WP_CATEGORY_ID],
    }

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
    # draft は公開前なので、女優ページには public link を出さない
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

    chosen = None
    for c in candidates:
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
