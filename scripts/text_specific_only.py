import os
import re
from pathlib import Path
from datetime import datetime

# ==================== 配置区域 ====================
TARGET_USERNAME = "Aoi-StarDiary"  # 要筛选的用户名，可修改
# ===============================================


def clean_html_tags(text: str) -> str:
    """清理 HTML 标签，保留重要信息"""
    result = text
    
    result = re.sub(r'<a href=[^>]*>([^<]*)</a>', r'\1', result)
    
    result = re.sub(r'<span class="url-icon">.*?</span>', '', result, flags=re.DOTALL)
    
    result = re.sub(r'<[^>]+>', '', result)
    
    result = re.sub(r'\s+', ' ', result)
    
    return result.strip()


def parse_post_time(time_str: str) -> tuple[str, datetime]:
    """解析微博发布时间并格式化为合法文件名，返回格式化时间和 datetime 对象"""
    try:
        dt = datetime.strptime(time_str, '%a %b %d %H:%M:%S %z %Y')
        formatted = dt.strftime('%a %b %d %H-%M-%S %Y')
        return formatted.replace(':', '-'), dt
    except:
        return time_str.replace(':', '-'), None


def process_file(input_path: Path, output_path: Path) -> tuple[bool, datetime]:
    """处理单个文件，返回是否包含目标用户和 datetime 对象"""
    with open(input_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if TARGET_USERNAME not in content:
        return False, None
    
    lines = content.split('\n')
    post_time = ""
    processed_lines = []
    
    for line in lines:
        if line.startswith('发布时间：'):
            post_time = line.replace('发布时间：', '').strip()
            processed_lines.append(f"发布时间：{post_time}")
        elif line.startswith('=' * 10):
            processed_lines.append('=' * 80)
        elif line.startswith('微博正文：'):
            processed_lines.append('微博正文：')
        elif line.startswith('评论 (') and '条):' in line:
            processed_lines.append(line)
        elif line.startswith('暂无评论'):
            processed_lines.append('暂无评论')
        elif line.strip() == '':
            processed_lines.append('')
        else:
            cleaned_line = clean_html_tags(line)
            processed_lines.append(cleaned_line)
    
    if not post_time:
        print(f"[!] 无法解析文件时间：{input_path}")
        return False, None
    
    safe_post_time, dt = parse_post_time(post_time)
    output_filename = f"{safe_post_time}.txt"
    output_file = output_path / output_filename
    
    counter = 1
    while output_file.exists():
        output_file = output_path / f"{safe_post_time}_{counter}.txt"
        counter += 1
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(processed_lines))
    
    print(f"[+] 处理完成：{input_path.name} -> {output_file.name}")
    return True, dt


def main():
    input_dir = Path("ext/posts")
    output_dir = Path("ext/posts_specific")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if not input_dir.exists():
        print(f"[!] 输入目录不存在：{input_dir}")
        return
    
    txt_files = list(input_dir.glob("*.txt"))
    print(f"[*] 找到 {len(txt_files)} 个微博文件")
    
    processed_files = []
    for txt_file in txt_files:
        try:
            success, dt = process_file(txt_file, output_dir)
            if success and dt:
                processed_files.append((dt, txt_file))
        except Exception as e:
            print(f"[!] 处理文件失败 {txt_file.name}: {e}")
    
    processed_files.sort(key=lambda x: x[0], reverse=True)
    
    for i, (dt, old_file) in enumerate(processed_files, 1):
        safe_time, _ = parse_post_time(dt.strftime('%a %b %d %H:%M:%S %z %Y'))
        new_name = f"{i:03d}_{safe_time}.txt"
        old_path = output_dir / f"{safe_time}.txt"
        new_path = output_dir / new_name
        
        if old_path.exists():
            old_path.rename(new_path)
            print(f"[+] 重命名：{safe_time}.txt -> {new_name}")
    
    print(f"\n[+] 完成！共处理 {len(processed_files)} 个包含 {TARGET_USERNAME} 的微博")
    print(f"[+] 保存位置：{output_dir.absolute()}")
    print(f"[+] 文件已按时间从新到旧排序（前缀 001_, 002_, ...）")


if __name__ == "__main__":
    main()
