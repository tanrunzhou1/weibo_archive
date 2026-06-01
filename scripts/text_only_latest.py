import datetime
import json
import os
import random
import sys
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse

# 添加项目根目录到 Python 路径
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from debug_tools import debug_on_exception, http_get

# ==================== 配置区域 ====================
# 日期筛选配置（格式：YYYY-MM-DD）
# 设置为 None 表示不过滤日期
START_DATE = None  # 例如："2024-01-01"
END_DATE = None    # 例如："2024-12-31"

# 获取最新 N 条微博（在日期范围内的）
LATEST_N = 5  # 获取最新的 n 条微博
# ================================================

Path("cache").mkdir(exist_ok=True)
Path("ext/comment").mkdir(parents=True, exist_ok=True)
Path("ext/longtext").mkdir(parents=True, exist_ok=True)
Path("ext/posts").mkdir(parents=True, exist_ok=True)

HEADERS = {
    "authority": "m.weibo.cn",
    "accept": "application/json, text/plain, */*",
    "accept-language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "cache-control": "no-cache",
    "mweibo-pwa": "1",
    "origin": "https://m.weibo.cn",
    "pragma": "no-cache",
    "referer": "https://m.weibo.cn/compose/",
    "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?1",
    "sec-ch-ua-platform": '"Android"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?1",
    "sec-ch-ua-platform": '"Android"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36",
    "x-requested-with": "XMLHttpRequest",
}


cookie: dict = json.load(open("cookie.json", "r", encoding="utf-8"))
cookie["MLOGIN"] = 1


cache_dir = Path("cache")
cache_dir.mkdir(exist_ok=True)


def _request(url: str, custom_headers: dict = {}) -> dict:
    headers = {
        **HEADERS,
        **custom_headers,
        "cookie": "; ".join([f"{k}={v}" for k, v in cookie.items()]),
        "x-xsrf-token": cookie.get("XSRF-TOKEN", ""),
    }
    return http_get(url, headers=headers, timeout=(30, 60)).json()


def request(url: str, referer: str = "", cached: bool = False, all_ret=False) -> dict:
    cache_file = cache_dir / f"{url.split('/')[-1].replace('?','_')}.json"
    if cached and cache_file.exists():
        return json.load(cache_file.open("r", encoding="utf-8"))
    headers = {"referer": referer} if referer else {}
    resp = _request(url, headers)
    time.sleep(random.random() * 0.3 + 0.7)
    if "ok" not in resp:
        print(f'[?] {resp}')
        raise NotImplementedError
    if resp["ok"] != 1:
        if resp.get("msg", "") in ["已过滤部分评论", "快来发表你的评论吧", "还没有人评论哦~快来抢沙发！", "因存在疑似骚扰内容，已过滤部分评论"]:
            pass
        else:
            print(f'[?] {resp}')
            refresh_cookie()
            resp = _request(url, headers)
    while resp.get("code") == -100 or resp.get("ok") == -100:
        print(f'[?] {resp}')
        if resp.get("url"):
            print("[!] Weibo requested CAPTCHA verification. Open this URL and finish it:")
            print(resp["url"])
        else:
            print("[!] Weibo requested CAPTCHA verification.")
        input("[!] Press Enter after you finish verification to retry...")
        resp = _request(url, headers)
        time.sleep(random.random() * 0.3 + 0.7)
    if not all_ret:
        resp = resp.get("data", {})
    if cached:
        json.dump(resp, cache_file.open("w", encoding="utf-8"), ensure_ascii=False)
    return resp


@debug_on_exception
def refresh_cookie(return_uid=False):
    cookie["_T_WM"] = int(time.time() / 3600) * 100001
    resp = _request("https://m.weibo.cn/api/config")
    resp = resp.get("data", {})
    cookie["XSRF-TOKEN"] = resp["st"]

    print(f"[-] Cookie Refreshed")
    print(f"Time watermark: {cookie['_T_WM']}")
    print(f"XSRF token: {cookie['XSRF-TOKEN']}")

    if not resp.get("login", False):
        print("[!] Cookie 可能无效，请检查 cookie.json 文件")
        raise ValueError("Invalid cookie")

    if return_uid:
        return resp["uid"]


UID = refresh_cookie(return_uid=True)

more_url = request(
    f"https://m.weibo.cn/profile/info?uid={UID}",
    referer=f"https://m.weibo.cn/profile/{UID}",
)["more"]

CID = int(more_url.split("/")[-1].split("_")[0])


# ====================================================================================================


@debug_on_exception
def fetchLongText(post, dirname) -> None:
    pid = post["id"]
    filename = f"{dirname}/longtext/{pid}.json"
    if Path(filename).exists():
        post["longtext"] = json.load(open(filename, "r", encoding="utf-8"))
        return
    longtext = request(
        f"https://m.weibo.cn/statuses/extend?id={pid}",
        referer=f"https://m.weibo.cn/detail/{pid}",
    ).get("longTextContent", "")
    json.dump(longtext, open(filename, "w", encoding="utf-8"), ensure_ascii=False)
    post["longtext"] = longtext


@debug_on_exception
def fetchSecondComments(mid, cid, max_id, dirname) -> tuple[list, int]:
    if int(max_id) == 0:
        filename = f"{dirname}/comment/{mid}_{cid}.json"
    else:
        filename = f"{dirname}/comment/{mid}_{cid}_{max_id}.json"
    if Path(filename).exists():
        data = json.load(open(filename, "r", encoding="utf-8"))
    else:
        print("[+] Downloading Comment Child", cid, max_id)
        url = f"https://m.weibo.cn/comments/hotFlowChild?cid={cid}&max_id={max_id}&max_id_type=0"
        data = request(url, all_ret=True)
        json.dump(data, open(filename, "w", encoding="utf-8"), ensure_ascii=False)
    if "data" not in data:
        if data["errno"] == "100011" and data["msg"] == "暂无数据":
            return [], 0
        print(f'[?] data')
        raise NotImplementedError
    comments = data["data"]
    max_id = data["max_id"]
    return comments, max_id


@debug_on_exception
def fetchFirstComments(mid, max_id, dirname) -> tuple[list, int]:
    if int(max_id) == 0:
        filename = f"{dirname}/comment/{mid}.json"
    else:
        filename = f"{dirname}/comment/{mid}_{max_id}.json"
    if Path(filename).exists():
        data = json.load(open(filename, "r", encoding="utf-8"))
    else:
        print("[+] Downloading Comment", mid, max_id)
        url = f"https://m.weibo.cn/comments/hotflow?mid={mid}&max_id={max_id}&max_id_type=0"
        data = request(url, all_ret=True)
        json.dump(data, open(filename, "w", encoding="utf-8"), ensure_ascii=False)
    if "data" not in data:
        return [], 0
    data = data["data"]
    comments = []
    for x in data["data"]:
        if x["comments"] and x["total_number"] != len(x["comments"]):
            comments_all = []
            _max_id = 0
            while True:
                _data, _max_id = fetchSecondComments(mid, x["id"], _max_id, dirname)
                comments_all += _data
                if _max_id == 0:
                    break
            x["comments_all"] = comments_all
        comments.append(x)
    max_id = data["max_id"]
    return comments, max_id


@debug_on_exception
def fetchComments(post, dirname) -> None:
    mid = post["mid"]
    if post["comments_count"] == 0:
        post["comments"] = []
        return
    max_id = 0
    comments = []
    while True:
        _comments, max_id = fetchFirstComments(mid, max_id, dirname)
        comments += _comments
        if max_id == 0:
            break
    post["comments"] = comments


@debug_on_exception
def parse_weibo_date(date_str: str) -> datetime.datetime | None:
    """解析微博时间字符串为 datetime 对象"""
    try:
        # 格式如：Tue Mar 19 12:34:56 +0800 2024
        return datetime.datetime.strptime(date_str, '%a %b %d %H:%M:%S %z %Y')
    except:
        try:
            # 尝试其他常见格式
            return datetime.datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
        except:
            return None


@debug_on_exception
def should_save_post(post) -> bool:
    """检查微博是否在指定日期范围内"""
    if START_DATE is None and END_DATE is None:
        return True
    
    created_at = post.get("created_at", "")
    post_dt = parse_weibo_date(created_at)
    
    if post_dt is None:
        return True  # 无法解析日期的微博默认保存
    
    # 移除时区信息，只比较日期
    post_date = post_dt.date()
    
    if START_DATE:
        start_dt = datetime.datetime.strptime(START_DATE, '%Y-%m-%d').date()
        if post_date < start_dt:
            return False
    
    if END_DATE:
        end_dt = datetime.datetime.strptime(END_DATE, '%Y-%m-%d').date()
        if post_date > end_dt:
            return False
    
    return True


@debug_on_exception
def fetchRelatedContent(post):
    if not should_save_post(post):
        print(f"[!] 跳过日期外的微博：{post.get('created_at', 'Unknown')}")
        return False
    
    if post["isLongText"]:
        fetchLongText(post, "ext")
    fetchComments(post, "ext")
    save_post_to_txt(post)
    return True


@debug_on_exception
def save_post_to_txt(post) -> None:
    pid = post["id"]
    filename = f"ext/posts/{pid}.txt"
    
    text = post.get("text", "")
    if post.get("longtext"):
        text = post["longtext"]
    
    created_at = post.get("created_at", "")
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"发布时间：{created_at}\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"微博正文：\n{text}\n")
        f.write("\n" + "=" * 80 + "\n\n")
        
        comments = post.get("comments", [])
        if comments:
            f.write(f"评论 ({len(comments)}条):\n\n")
            for i, comment in enumerate(comments, 1):
                user = comment.get("user", {}).get("screen_name", "未知用户")
                comment_text = comment.get("text", "")
                comment_created_at = comment.get("created_at", "")
                
                f.write(f"[{i}] {user} ({comment_created_at}):\n{comment_text}\n")
                
                if comment.get("comments_all"):
                    for j, sub_comment in enumerate(comment["comments_all"], 1):
                        sub_user = sub_comment.get("user", {}).get("screen_name", "未知用户")
                        sub_text = sub_comment.get("text", "")
                        sub_created_at = sub_comment.get("created_at", "")
                        
                        f.write(f"    └─ [{j}] {sub_user} ({sub_created_at}): {sub_text}\n")
                
                f.write("\n")
        else:
            f.write("暂无评论\n")
    
    print(f"[+] Saved post {pid} to {filename}")


# ====================================================================================================


@debug_on_exception
def fetchLatestPosts():
    """
    优化版本：只获取最新的 N 条微博，不轮询所有历史微博
    通过分页获取，直到收集到足够的微博数量或超出日期范围
    """
    posts = []
    saved_count = 0
    page = 0
    max_pages = 50  # 最多爬取 50 页，防止无限循环
    
    print(f"[+] 开始获取最新的 {LATEST_N} 条微博（日期范围：{START_DATE or '开始'} 到 {END_DATE or '结束'}）")
    
    while saved_count < LATEST_N and page < max_pages:
        page += 1
        
        if page == 1:
            # 第一页
            data = request(
                f"https://m.weibo.cn/api/container/getIndex?containerid={CID}_-_WEIBO_SECOND_PROFILE_WEIBO",
                referer=f"https://m.weibo.cn/p/{CID}_-_WEIBO_SECOND_PROFILE_WEIBO",
                cached=False,
            )
        else:
            # 后续页面使用 since_id
            if not data.get("cardlistInfo", {}).get("since_id"):
                print(f"[+] 没有更多页面了，当前共 {saved_count} 条微博")
                break
            
            since_id = data["cardlistInfo"]["since_id"]
            data = request(
                f"https://m.weibo.cn/api/container/getIndex?containerid={CID}_-_WEIBO_SECOND_PROFILE_WEIBO&page_type=03&since_id={since_id}",
                referer=f"https://m.weibo.cn/p/{CID}_-_WEIBO_SECOND_PROFILE_WEIBO",
                cached=False,
            )
        
        # 提取微博
        new_posts = []
        for card in data.get("cards", []):
            if card["card_type"] == 9:
                new_posts.append(card["mblog"])
            elif card["card_type"] == 11 and "card_group" in card:
                for sub_card in card["card_group"]:
                    if sub_card["card_type"] == 9:
                        new_posts.append(sub_card["mblog"])
        
        if not new_posts:
            print(f"[+] 当前页面没有微博")
            break
        
        print(f"[+] 第 {page} 页，找到 {len(new_posts)} 条微博")
        
        # 处理微博
        for post in new_posts:
            if saved_count >= LATEST_N:
                print(f"[+] 已获取足够的 {LATEST_N} 条微博")
                break
            
            # 检查日期范围
            if not should_save_post(post):
                created_at = post.get("created_at", "")
                print(f"[!] 跳过日期外的微博：{created_at}")
                
                # 如果日期已经早于 START_DATE，可以提前结束
                post_dt = parse_weibo_date(created_at)
                if post_dt and START_DATE:
                    start_dt = datetime.datetime.strptime(START_DATE, '%Y-%m-%d').date()
                    if post_dt.date() < start_dt:
                        print(f"[+] 微博日期已早于 {START_DATE}，提前结束爬取")
                        return posts
                continue
            
            # 保存微博
            fetchRelatedContent(post)
            posts.append(post)
            saved_count += 1
        
        # 显示进度
        if posts:
            print(f"[+] 进度：{saved_count}/{LATEST_N} 条微博，最新：{posts[-1]['created_at']}")
    
    if saved_count < LATEST_N:
        print(f"[+] 已爬取所有可用页面，共获取 {saved_count} 条微博（目标：{LATEST_N} 条）")
    else:
        print(f"[+] 成功获取 {saved_count} 条微博")
    
    return posts


if __name__ == "__main__":
    posts = fetchLatestPosts()
    print("Total", len(posts), "posts")

    posts = sorted(posts, key=lambda x: x["id"], reverse=True)
    print(f"[+] Saving into posts.json")
    json.dump(posts, open("posts.json", "w", encoding="utf-8"), ensure_ascii=False)

    def zipdir(path, ziph):
        for root, dirs, files in os.walk(path):
            for file in files:
                ziph.write(
                    os.path.join(root, file),
                    os.path.relpath(os.path.join(root, file), os.path.join(path, "..")),
                )

    # 创建 store 目录
    store_dir = Path("store")
    store_dir.mkdir(exist_ok=True)
    
    current_date = datetime.datetime.now().strftime("%Y%m%d")
    zip_filename = store_dir / f"weibo_text_archive_{current_date}.zip"
    print(f"[+] Saving into {zip_filename}")
    zipf = zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED)
    folders = ["ext"]
    for folder in folders:
        zipdir(folder, zipf)
    zipf.close()
