#!/usr/bin/env python3
# 完全修复JSON文件
import json
import re

def fix_complete():
    with open('task_v3_1.json', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 首先处理第126行的问题 - 替换字符串中的"为\"
    # 问题是在setup字符串中包含了未转义的双引号
    lines = content.split('\n')
    
    # 手动查看和修复问题行
    # 第126行（索引125）
    if len(lines) > 125:
        line126 = lines[125]
        print(f"原始行126: {repr(line126)}")
        
        # 修复这个行
        # 行中有: "全是网上能查到的，没有自己的判断"
        # 替换为: \"全是网上能查到的，没有自己的判断\"
        line126 = line126.replace(
            '批为"全是网上能查到的，没有自己的判断"。周总说',
            '批为\\"全是网上能查到的，没有自己的判断\\"。周总说'
        )
        lines[125] = line126
        print(f"修复后行126: {repr(line126)}")
    
    content = '\n'.join(lines)
    
    # 尝试逐段解析
    # 或者我们可以使用更简单的方法 - 使用ast.literal_eval或者其他库
    # 让我们尝试用demjson3或者直接尝试清理
    try:
        # 先尝试标准json
        data = json.loads(content)
        print("✓ 直接解析成功！")
        return write_data(data)
    except Exception as e1:
        print(f"标准解析失败: {e1}")
        
        # 尝试修复方法 - 只保留第一个完整的JSON对象
        # 找到最后一个匹配的闭合大括号
        try:
            # 寻找JSON的边界 - 找到第一个{和对应的匹配}
            import sys
            count = 0
            start = -1
            end = -1
            
            for i, char in enumerate(content):
                if char == '{':
                    count += 1
                    if start == -1:
                        start = i
                elif char == '}':
                    count -= 1
                    if count == 0 and start != -1:
                        end = i + 1
                        break
            
            if start != -1 and end != -1:
                json_content = content[start:end]
                data = json.loads(json_content)
                print("✓ 截取JSON后解析成功！")
                return write_data(data)
        except Exception as e2:
            print(f"截取解析也失败: {e2}")
    
    return False

def write_data(data):
    with open('task_v3_1.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("✓ 文件已保存！")
    print(f"  包含 {len(data.get('stages', []))} 个阶段")
    return True

if __name__ == '__main__':
    fix_complete()
