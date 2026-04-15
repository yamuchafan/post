import base64
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


def auth_headers():
    token = base64.b64encode(f"{WP_USER}:{WP_APP_PASSWORD}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
    }


def load_state():
    if not STATE_PATH.exists():
        return {"done": []}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def get_candidates():
    url = f"{WP_BASE}/wp-json/yoruplus/v1/actress-candidates?limit=50&min_count=170"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.json()


def wp_post_exists(slug):
    url = f"{WP_BASE}/wp-json/wp/v2/posts"
    params = {
        "slug": slug,
        "status": "draft,publish,pending,future,private",
        "context": "edit",
        "per_page": 5,
    }
    r = requests.get(url, headers=auth_headers(), params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    return data[0] if data else None


def build_intro(c):
    genres = c.get("top_genres", [])
    g1 = genres[0]["name"] if len(genres) > 0 else "主要ジャンル"
    g2 = genres[1]["name"] if len(genres) > 1 else ""
    maker = (c.get("top_maker") or {}).get("name", "")
    genre_text = f"{g1}や{g2}" if g2 else g1
    maker_text = f"、メーカーでは{maker}系の出演も比較的目立ちます" if maker else ""
    return (
        f"{c['name']}の作品を選ぶときは、雰囲気だけで探すより、出演本数やジャンル傾向を見た方が失敗しにくくなります。"
        f"出演作は全{c['count']}件あり、全体では{genre_text}が目立ち{maker_text}。"
        f"この記事では、初見で入りやすいおすすめ3本と、向いている人・向いていない人、失敗しにくい選び方を整理します。"
    )


def build_for(c):
    cluster = c.get("cluster", "mixed")
    name = c["name"]
    if cluster == "bishoujo":
        return f"{name}は、雰囲気や見た目のまとまりを重視して選びたい人に向いています。"
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
    return f"反対に、条件を決めずに広く眺めたい人は、最初に作品一覧へ行くより、先におすすめ3本から相性を確認した方が判断しやすくなります。"


def build_how(c):
    name = c["name"]
    count = c["count"]
    maker_bias = c.get("maker_bias", False)
    maker = (c.get("top_maker") or {}).get("name", "")
    genres = c.get("top_genres", [])
    g1 = genres[0]["name"] if len(genres) > 0 else ""
    g2 = genres[1]["name"] if len(genres) > 1 else ""

    if maker_bias and maker:
        return f"{name}はメーカー傾向が比較的はっきりしているので、まず代表作を見たあと、{maker}系の作品へ広げる見方が失敗しにくいです。"
    if count > 40:
        return f"{name}は作品数が多いため、最初から一覧で迷うより、{g1}や{g2}など上位ジャンルから入る方が効率的です。"
    return f"{name}は、まず代表作を見て全体の雰囲気を掴み、その後に作品一覧へ進む流れが合っています。"


def build_picks(c):
    lines = []
    for i, p in enumerate(c.get("picks", [])[:3], start=1):
        title = p.get("title", f"おすすめ作品{i}")
        url = p.get("url", "#")
        lines.append(f"### {i}. [{title}]({url})\n入口として確認しやすい1本です。")
    return "\n\n".join(lines)


def build_related(c):
    lines = []
    for r in c.get("related", [])[:3]:
        lines.append(f"- [{r['name']}]({r['url']})")
    return "\n".join(lines) if lines else "比較候補は今後追加予定です。"


def build_article(c):
    return f"""# {c['name']}のおすすめ作品3選｜初めて見る人向けに選び方も解説

## 導入
{build_intro(c)}

出演作品を一覧で確認したい方は、[{c['name']}の出演作品一覧ページ]({c['actress_url']})もあわせて確認してください。

## {c['name']}が向いている人
{build_for(c)}

## {c['name']}が向いていない人
{build_not(c)}

## まず見るべきおすすめ3本
{build_picks(c)}

## 失敗しにくい選び方
{build_how(c)}

## 同系統で比較したい女優
{build_related(c)}

## 総評
{c['name']}は、まず代表作で全体の傾向を確認し、その後に一覧ページへ進む流れが使いやすいタイプです。

## 出演作品一覧はこちら
作品一覧・ジャンル傾向・メーカー傾向までまとめて見たい方は、[{c['name']}の出演作品一覧ページ]({c['actress_url']})を確認してください。
"""


def create_wp_draft(c, content):
    slug = f"seo-actress-{c['slug']}"
    existing = wp_post_exists(slug)
    payload = {
        "title": f"{c['name']}のおすすめ作品3選｜初めて見る人向けに選び方も解説",
        "slug": slug,
        "status": "draft",
        "content": content,
        "categories": [WP_CATEGORY_ID],
    }

    if existing:
        post_id = existing["id"]
        url = f"{WP_BASE}/wp-json/wp/v2/posts/{post_id}"
    else:
        url = f"{WP_BASE}/wp-json/wp/v2/posts"

    r = requests.post(url, headers=auth_headers(), data=json.dumps(payload), timeout=60)
    r.raise_for_status()
    return r.json()


def touch_actress(c, post):
    url = f"{WP_BASE}/wp-json/yoruplus/v1/actress-touch/{c['term_id']}"
    payload = {
        "article_url": post.get("link", ""),
        "article_title": post["title"]["rendered"] if isinstance(post.get("title"), dict) else post.get("title", ""),
        "checked_at": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d"),
    }
    r = requests.post(url, headers=auth_headers(), data=json.dumps(payload), timeout=60)
    r.raise_for_status()
    return r.json()


def main():
    state = load_state()
    done = set(state.get("done", []))

    candidates = get_candidates()

    chosen = None
    for c in candidates:
        if c["slug"] in done:
            continue
        if wp_post_exists(f"seo-actress-{c['slug']}"):
            done.add(c["slug"])
            continue
        chosen = c
        break

    if not chosen:
        print("No candidate.")
        save_state({"done": sorted(done)})
        return

    content = build_article(chosen)
    out_file = DRAFT_DIR / f"{datetime.now().date().isoformat()}-{chosen['slug']}.md"
    out_file.write_text(content, encoding="utf-8")

    post = create_wp_draft(chosen, content)
    touch_actress(chosen, post)

    done.add(chosen["slug"])
    save_state({"done": sorted(done)})

    print(f"Draft created for: {chosen['name']}")


if __name__ == "__main__":
    main()
