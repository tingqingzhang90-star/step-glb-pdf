# -*- coding: utf-8 -*-
"""分析所有零件的变换矩阵，对比行主序 vs 列主序解读"""
import json
import math

with open(r'e:\分享代码\step__glb_pdf\data\parts_transform.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print("=" * 100)
print("零件变换矩阵分析")
print("=" * 100)

for name, info in data.items():
    m = info.get("transform_matrix")
    if not m:
        continue

    # 清理极小值
    rot = [0.0 if abs(m[i]) < 1e-10 else m[i] for i in range(9)]
    t = [m[9] * 1000, m[10] * 1000, m[11] * 1000]
    suppressed = info.get("suppressed", False)

    # 判断旋转类型
    is_identity = all(abs(rot[i] - (1 if i % 4 == 0 else 0)) < 0.01 for i in range(9))
    has_rotation = not is_identity

    if not has_rotation:
        print(f"\n[{name}] (suppressed={suppressed})")
        print(f"  旋转: 单位矩阵 (纯平移)")
        print(f"  平移: ({t[0]:.1f}, {t[1]:.1f}, {t[2]:.1f}) mm")
        continue

    # 行主序解读
    row_major = [
        [rot[0], rot[1], rot[2]],
        [rot[3], rot[4], rot[5]],
        [rot[6], rot[7], rot[8]],
    ]
    # 列主序解读 (转置)
    col_major = [
        [rot[0], rot[3], rot[6]],
        [rot[1], rot[4], rot[7]],
        [rot[2], rot[5], rot[8]],
    ]

    print(f"\n[{name}] (suppressed={suppressed})")
    print(f"  平移: ({t[0]:.1f}, {t[1]:.1f}, {t[2]:.1f}) mm")

    print(f"  行主序 R (当前代码):")
    for row in row_major:
        print(f"    [{row[0]:8.4f}, {row[1]:8.4f}, {row[2]:8.4f}]")

    print(f"  列主序 R (转置后):")
    for row in col_major:
        print(f"    [{row[0]:8.4f}, {row[1]:8.4f}, {row[2]:8.4f}]")

    # 分析旋转效果
    # 行主序: v' = R_row · v  →  零件Y轴映射到装配体的哪个轴？
    # R_row 的第二列 (rot[1], rot[4], rot[7]) 表示零件 Y 轴在装配体中的方向
    row_y_dir = (rot[1], rot[4], rot[7])
    row_z_dir = (rot[2], rot[5], rot[8])

    # 列主序: v' = R_col · v = R_row^T · v
    # R_col 的第二列 (rot[3], rot[4], rot[7]) 表示零件 Y 轴在装配体中的方向
    col_y_dir = (rot[3], rot[4], rot[7])
    col_z_dir = (rot[6], rot[7], rot[8] if len(rot) > 8 else 0)

    print(f"  行主序: 零件Y→装配体({row_y_dir[0]:.1f},{row_y_dir[1]:.1f},{row_y_dir[2]:.1f})  零件Z→装配体({row_z_dir[0]:.1f},{row_z_dir[1]:.1f},{row_z_dir[2]:.1f})")
    print(f"  列主序: 零件Y→装配体({col_y_dir[0]:.1f},{col_y_dir[1]:.1f},{col_y_dir[2]:.1f})  零件Z→装配体({col_z_dir[0]:.1f},{col_z_dir[1]:.1f},{col_z_dir[2]:.1f})")

    # 判断是否绕 X 轴旋转 (关键: 鱼眼轴承)
    if abs(rot[0] - 1.0) < 0.01 and abs(rot[4]) < 0.01 and abs(rot[8]) < 0.01:
        print(f"  ★ 绕 X 轴旋转!")
        if abs(rot[5] - 1.0) < 0.01 and abs(rot[7] + 1.0) < 0.01:
            print(f"    行主序: Y→Z, Z→-Y (绕X -90°)")
            print(f"    列主序: Y→-Z, Z→Y (绕X +90°)")
        elif abs(rot[5] + 1.0) < 0.01 and abs(rot[7] - 1.0) < 0.01:
            print(f"    行主序: Y→-Z, Z→Y (绕X +90°)")
            print(f"    列主序: Y→Z, Z→-Y (绕X -90°)")
