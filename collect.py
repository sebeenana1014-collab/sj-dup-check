"""S저널 기사 수집기.

- RSS(전체기사)에서 새 기사 번호를 찾고, 처음 실행(또는 --backfill)일 때는
  기사 목록 페이지를 걸어가며 최근 KEEP_DAYS일치 기사 번호를 모은다.
- 아직 없는 기사만 본문 페이지를 열어 제목·기자·시각·본문을 저장한다.
- 결과는 docs/articles.json (검사 페이지가 그대로 읽는다).
"""
import json, re, sys, time, html
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://www.s-journal.co.kr"
RSS = f"{BASE}/rss/allArticle.xml"
LIST = f"{BASE}/news/articleList.html?page={{page}}&view_type=sm"
VIEW = f"{BASE}/news/articleView.html?idxno={{idx}}"
OUT = Path(__file__).parent / "docs" / "articles.json"
KEEP_DAYS = 45
KST = timezone(timedelta(hours=9))
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SJournalDupCheck/1.0; +internal desk tool)"}

sess = requests.Session()
sess.headers.update(HEADERS)


def get(url, tries=3):
    for i in range(tries):
        try:
            r = sess.get(url, timeout=20)
            if r.status_code == 200:
                r.encoding = r.apparent_encoding or "utf-8"
                return r.text
            if r.status_code == 404:
                return None
        except requests.RequestException as e:
            print("  retry", url, e, file=sys.stderr)
        time.sleep(1.5 * (i + 1))
    return None


def load():
    if OUT.exists():
        return {a["id"]: a for a in json.loads(OUT.read_text("utf-8"))["articles"]}
    return {}


def save(store):
    arts = sorted(store.values(), key=lambda a: a["date"], reverse=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "count": len(arts),
        "articles": arts,
    }, ensure_ascii=False, indent=0), "utf-8")


def ids_from_rss():
    xml = get(RSS)
    if not xml:
        return []
    return [int(m) for m in re.findall(r"idxno=(\d+)", xml)]


def ids_from_list(max_pages=60):
    """기사 목록 페이지에서 기사 번호 모으기 (보조 수단)."""
    ids = []
    for p in range(1, max_pages + 1):
        page = get(LIST.format(page=p))
        if not page:
            break
        found = [int(m) for m in dict.fromkeys(re.findall(r"articleView\.html\?idxno=(\d+)", page))]
        print(f"  목록 {p}쪽: {len(found)}건")
        if not found:
            break
        ids += found
        time.sleep(0.3)
    return ids


def text_of(node):
    for bad in node.select("script, style, figure, figcaption, .photo, .caption, iframe, table.photo, .ad, .article-ad"):
        bad.decompose()
    ps = [p.get_text(" ", strip=True) for p in node.find_all("p")]
    ps = [t for t in ps if t]
    if len(ps) >= 2:
        parts = []
        for t in ps:
            if not parts or t != parts[-1]:
                parts.append(t)
    else:
        for br in node.find_all("br"):
            br.replace_with("\n")
        parts = [l.strip() for l in node.get_text("\n").split("\n") if l.strip()]
    body = "\n".join(parts)
    body = re.sub(r"\n{2,}", "\n", body)
    return body.strip()


def parse_article(idx, page):
    s = BeautifulSoup(page, "html.parser")
    title = ""
    og = s.find("meta", property="og:title")
    if og and og.get("content"):
        title = og["content"].split(" - ")[0].strip()
    if not title:
        h = s.find(["h1", "h2", "h3"], class_=re.compile("heading|title", re.I)) or s.find("h1")
        title = h.get_text(" ", strip=True) if h else f"기사 {idx}"

    node = (s.select_one("#article-view-content-div") or s.select_one("[itemprop=articleBody]")
            or s.select_one("#articleBody") or s.select_one("article") or s.body)
    body = text_of(node) if node else ""
    if len(body) < 80:
        # 마지막 수단: <p>가 가장 많이 모인 블록
        best = max(s.find_all("div"), key=lambda d: len(d.find_all("p", recursive=False)), default=None)
        if best:
            body = text_of(best)

    reporter = ""
    for m in (s.find("meta", attrs={"name": "author"}), s.find("meta", property="dable:author"),
              s.find("meta", property="article:author")):
        if m and m.get("content"):
            reporter = m["content"].strip()
            break
    if not reporter:
        hit = re.search(r"([가-힣]{2,4})\s*기자", page)
        reporter = hit.group(1) + " 기자" if hit else ""
    reporter = re.sub(r"\s*기자$", "", reporter).strip()

    date = ""
    for m in (s.find("meta", property="article:published_time"), s.find("meta", attrs={"name": "article:published_time"})):
        if m and m.get("content"):
            date = m["content"][:16].replace("T", " ")
            break
    if not date:
        hit = re.search(r"입력\s*(\d{4})[.-](\d{2})[.-](\d{2})\s+(\d{2}):(\d{2})", page) or \
              re.search(r"(\d{4})[.-](\d{2})[.-](\d{2})\s+(\d{2}):(\d{2})", page)
        if hit:
            y, mo, d, hh, mm = hit.groups()
            date = f"{y}-{mo}-{d} {hh}:{mm}"
    if not date:
        date = datetime.now(KST).strftime("%Y-%m-%d %H:%M")

    return {"id": idx, "title": html.unescape(title), "url": VIEW.format(idx=idx),
            "reporter": reporter, "date": date, "body": body}


def fetch_one(idx, store):
    """기사 한 건 저장. 반환: 'saved' | 'short' | 'miss'"""
    page = get(VIEW.format(idx=idx))
    if not page:
        return "miss"
    try:
        a = parse_article(idx, page)
    except Exception as e:  # 한 건 실패가 전체를 막지 않게
        print("  해석 실패", idx, e, file=sys.stderr)
        return "miss"
    if len(a["body"]) < 80:
        return "short"
    store[idx] = a
    return "saved"


def main():
    backfill = "--backfill" in sys.argv
    store = load()
    cutoff = datetime.now(KST) - timedelta(days=KEEP_DAYS)
    cut_s = cutoff.strftime("%Y-%m-%d")
    deadline = time.time() + (32 if backfill else 8) * 60

    rss = ids_from_rss()
    print(f"RSS: {len(rss)}건")
    have = set(store)
    newest = max(rss) if rss else (max(have) if have else 0)

    # 1) RSS에 있는 새 기사 + 빠진 번호 메우기
    todo = [i for i in rss if i not in have]
    if have:
        gap = [i for i in range(max(have) + 1, newest) if i not in have]
        todo += gap[-300:]
    fetched = 0
    for idx in sorted(set(todo), reverse=True):
        if time.time() > deadline:
            break
        if fetch_one(idx, store) == "saved":
            fetched += 1
            if fetched % 25 == 0:
                save(store)
        time.sleep(0.35)
    print(f"최신분 {fetched}건 저장")

    # 2) 과거 채우기: 기사 번호를 거꾸로 훑는다
    if backfill and newest:
        idx = min(have) - 1 if have else newest
        old_streak = miss_streak = 0
        added = 0
        while idx > 0 and time.time() < deadline:
            if idx in store:
                idx -= 1
                continue
            r = fetch_one(idx, store)
            if r == "miss":
                miss_streak += 1
                if miss_streak >= 80:
                    print("  빈 번호가 계속돼 중단")
                    break
            else:
                miss_streak = 0
                if r == "saved":
                    added += 1
                    if store[idx]["date"][:10] < cut_s:
                        old_streak += 1
                        if old_streak >= 30:
                            print("  기간을 넘어서 중단")
                            break
                    else:
                        old_streak = 0
                    if added % 50 == 0:
                        save(store)
                        print(f"  과거 {added}건 (현재 {store[idx]['date']})")
            idx -= 1
            time.sleep(0.35)
        print(f"과거분 {added}건 저장")

    # 오래된 기사 정리
    for k in [k for k, a in store.items() if a["date"][:10] < cut_s]:
        del store[k]

    save(store)
    print(f"총 {len(store)}건 보관 중")


if __name__ == "__main__":
    main()
