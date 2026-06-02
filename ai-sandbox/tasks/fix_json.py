#!/usr/bin/env python3
# 修复JSON文件中的转义问题
import json
import re

def fix_json_file():
    with open('task_v3_1.json', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 替换字符串中的未转义双引号为转义版本
    # 但这有点复杂，让我们用另一种方法
    # 直接读取并修复特定问题
    lines = content.split('\n')
    
    # 修复第126行 (索引125)
    if len(lines) > 125:
        line126 = lines[125]
        # 找到问题："全是网上能查到的，没有自己的判断" 这里双引号没有转义
        line126 = line126.replace('"全是网上能查到的，没有自己的判断"', '\\"全是网上能查到的，没有自己的判断\\"')
        lines[125] = line126
    
    content_fixed = '\n'.join(lines)
    
    # 现在尝试解析
    try:
        data = json.loads(content_fixed)
        print("✓ JSON 解析成功！")
        # 写回文件
        with open('task_v3_1.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print("✓ 文件已成功修复！")
        return True
    except Exception as e:
        print(f"仍然有错误：{e}")
        return False

if __name__ == '__main__':
    fix_json_file()
