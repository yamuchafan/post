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
    return [g["name"] for g in c.get("top_genres", []) if g.get("name")][:3]


def build_intro(c):
    genres = genre_names(c)
    g1 = genres[0] if len(genres) > 0 else "主要ジャンル"
    g2 = genres[1] if len(genres) > 1 else ""
    maker = (c.get("top_maker") or {}).get("name", "")

    genre_text = f"{g1}や{g2}" if g2 else g1
    maker_text = f"、メーカーでは{maker}系の出演が多いです。" if maker else ""

    return (
        f"{c['name']}の作品を選ぶときは、雰囲気で探すより、出演本数やジャンル傾向を見た方が失敗しにくいです。"
        f"出演作は全{c['count']}件あり、全体では{genre_text}の傾向が強く{maker_text}。"
        f"この記事では、初見からでも入りやすいおすすめ3本と、向いている人・向いていない人、失敗しにくい選び方を整理しています。"
    )


def build_for(c):
    cluster = c.get("cluster", "mixed")
    name = c["name"]

    if cluster == "bishoujo":
        return f"{name}は、雰囲気や作品の完成度を重視して選びたい人に向いています。"
    if cluster == "oral":
        return f"{name}は、プレイ傾向を先に決めてから選びたい人に向いています。"
    if cluster == "jyukujo":
        return f"{name}は、落ち着いた空気感や年上系の雰囲気を重視したい人に向いています。"
    if cluster == "character":
        return f"{name}は、役柄やキャラクター性を重視して選びたい人に向いています。"
    if cluster == "hard":
        return f"{name}は、分かりやすい強めの方向性から入りたい人に向いています。"

    return f"{name}は、代表作を見てから条件で絞り込みたい人に向いています。"


def build_not(c):
    name = c["name"]
    return f"反対に、条件を決めずに広く眺めたい人は、最初に作品一覧へ行くより、先におすすめ3本から作品を確認した方が良作に出会えます。"


def build_how(c):
    name = c["name"]
    count = c["count"]
    maker_bias = c.get("maker_bias", False)
    maker = (c.get("top_maker") or {}).get("name", "")
    genres = genre_names(c)
    g1 = genres[0] if len(genres) > 0 else ""
    g2 = genres[1] if len(genres) > 1 else ""

    if maker_bias and maker:
        return f"{name}はメーカー傾向が比較的はっきりしているので、まず代表作を見たあと、{maker}系の作品へ広げる見方が失敗しにくいです。"
    if count > 40:
        return f"{name}は作品数が多いため、最初から一覧で迷うより、{g1}や{g2}など上位ジャンルから入る方がいいです。"
    return f"{name}は、まず代表作を見て女優の雰囲気を掴み、その後に作品一覧へ進む流れが合っています。"


def build_picks_html(c):
    items = c.get("picks", [])[:3]
    if not items:
        return "<p>おすすめ候補は準備中です。</p>"

    parts = []
    for i, p in enumerate(items, start=1):
        title = h(p.get("title", f"おすすめ作品{i}"))
        url = h(p.get("url", "#"))
        parts.append(
            f"<h3>{i}. <a href=\"{url}\">{title}</a></h3>"
            f"<p>入口として確認しやすい1本です。</p>"
        )
    return "\n".join(parts)


def build_related_html(c):
    items = c.get("related", [])[:3]
    if not items:
        return "<p>比較候補は今後追加予定です。</p>"

    lis = []
    for r in items:
        lis.append(
            f"<li><a href=\"{h(r['url'])}\">{h(r['name'])}</a></li>"
        )
    return "<ul>\n" + "\n".join(lis) + "\n</ul>"


def build_article_html(c):
    name = h(c["name"])
    actress_url = h(c["actress_url"])

    return f"""
<h1>{name}のおすすめ作品3選｜初めて見る人向けに選び方も解説</h1>

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
<p>{name}は、まず代表作で全体の傾向を確認し、その後に一覧ページへ進む流れが王道です。</p>

<h2>出演作品一覧はこちら</h2>
<p>作品一覧・ジャンル傾向・メーカー傾向までまとめて見たい方は、<a href="{actress_url}">{name}の出演作品一覧ページ</a>を確認してください。</p>
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
