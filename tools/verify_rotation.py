# -*- coding: utf-8 -*-
"""验证 SW Transform2 旋转矩阵的解读方向（行主序 vs 列主序/转置）

关键推理:
1. 推杆(suppressed=false): 单位矩阵, Z=510.8mm — 零件Z轴=装配体Z轴
2. 鱼眼轴承(suppressed=true): Z=957.8mm, STEP几何Y轴最长(422mm=杆长)
3. 两者Z差 = 957.8 - 510.8 = 447mm ≈ 杆长422mm
   → 鱼眼轴承杆从推杆前端延伸到Z=957.8, 杆方向应为+Z(向前)

行主序解读: 零件Y→装配体-Z (杆向后) ← 方向反!
列主序解读: 零件Y→装配体+Z (杆向前) ← 方向正确!
"""
import json
import math

with open(r'e:\分享代码\step__glb_pdf\data\parts_transform.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print("=== 位置关系分析 ===\n")

# 推杆
rod = data['250推杆-1']
rod_z = rod['transform_matrix'][11] * 1000
print(f"推杆: Z={rod_z:.1f}mm, 旋转=单位矩阵(零件Z→装配体Z)")

# 鱼眼轴承
eye = data['250鱼眼轴承-1']
eye_z = eye['transform_matrix'][11] * 1000
print(f"鱼眼轴承: Z={eye_z:.1f}mm, STEP杆长≈422mm(Y轴)")

diff = eye_z - rod_z
print(f"\nZ坐标差: {diff:.1f}mm")
print(f"杆长: ~422mm")
print(f"差值接近杆长 → 鱼眼轴承杆从推杆位置延伸到Z={eye_z:.1f}")
print(f"→ 杆方向应为 +Z(向前)")

# 旋转矩阵分析
rot = [0.0 if abs(eye['transform_matrix'][i]) < 1e-10 else eye['transform_matrix'][i] for i in range(9)]

print(f"\n=== 旋转矩阵解读对比 ===\n")
print(f"SW ArrayData: {rot}")

# 行主序: R = [rot[0..2]; rot[3..5]; rot[6..8]]
# v' = R · v,  第二列 = 零件Y轴在装配体中的方向
row_y = (rot[1], rot[4], rot[7])
print(f"行主序: 零件Y(杆方向) → 装配体({row_y[0]:.1f}, {row_y[1]:.1f}, {row_y[2]:.1f})")
if abs(row_y[2] + 1.0) < 0.01:
    print(f"  → 杆指向 -Z (向后) ✗ 方向反!")
elif abs(row_y[2] - 1.0) < 0.01:
    print(f"  → 杆指向 +Z (向前) ✓ 方向正确")

# 列主序(转置): R = [rot[0],rot[3],rot[6]; rot[1],rot[4],rot[7]; rot[2],rot[5],rot[8]]
# 第二列 = (rot[3], rot[4], rot[5])
col_y = (rot[3], rot[4], rot[5])
print(f"列主序: 零件Y(杆方向) → 装配体({col_y[0]:.1f}, {col_y[1]:.1f}, {col_y[2]:.1f})")
if abs(col_y[2] + 1.0) < 0.01:
    print(f"  → 杆指向 -Z (向后) ✗ 方向反!")
elif abs(col_y[2] - 1.0) < 0.01:
    print(f"  → 杆指向 +Z (向前) ✓ 方向正确")

print(f"\n=== 结论 ===")
print(f"SW Transform2.ArrayData 的旋转矩阵需要转置(列主序解读)")
print(f"当前代码按行主序解读，导致旋转方向反转")
print(f"修复: 在 matrix_to_trsf 中转置旋转矩阵")

# 验证其他带旋转的零件
print(f"\n=== 其他带旋转零件的影响 ===")
for name, info in data.items():
    m = info.get("transform_matrix")
    if not m:
        continue
    r = [0.0 if abs(m[i]) < 1e-10 else m[i] for i in range(9)]
    is_identity = all(abs(r[i] - (1 if i % 4 == 0 else 0)) < 0.01 for i in range(9))
    if is_identity:
        continue

    # 检查是否对称矩阵(转置=自身)
    is_symmetric = (abs(r[1] - r[3]) < 0.01 and abs(r[2] - r[6]) < 0.01 and abs(r[5] - r[7]) < 0.01)

    # 旋转轴分析
    if abs(r[8] - 1.0) < 0.01 and abs(r[0]) < 0.01 and abs(r[4]) < 0.01:
        axis = "Z轴"
    elif abs(r[0] - 1.0) < 0.01 and abs(r[4]) < 0.01 and abs(r[8]) < 0.01:
        axis = "X轴"
    else:
        axis = "其他"

    sym = "对称(不受影响)" if is_symmetric else "非对称(方向反转)"
    print(f"  {name}: 绕{axis}旋转, {sym}")
