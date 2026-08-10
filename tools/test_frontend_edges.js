/**
 * 前端边线提取验证脚本
 * 在 viewer.html 加载模型后,在控制台运行此脚本
 *
 * 功能:
 * 1. 切换为正交相机
 * 2. 对 6 个标准视图设置相机方向
 * 3. 从 Three.js 场景提取边线顶点(mm)
 * 4. 用相机投影矩阵将 3D 顶点投影到 2D 画布坐标
 * 5. 输出每个视图的 bbox 和边线数量,验证方向是否正确
 */
(function () {
  const v = viewer.GetViewer();
  const scene = v.scene;
  const THREE = window.THREE || scene.type === 'Scene' ? window.THREE : null;

  // 如果 THREE 未暴露到 window,尝试从 o3dv 获取
  let THREE_LIB = window.THREE;
  if (!THREE_LIB) {
    // o3dv 内部打包了 THREE,尝试从已有对象推断
    const cam = v.camera;
    if (cam && cam.isPerspectiveCamera) {
      // THREE 已打包在 o3dv 内部,我们需要手动实现投影矩阵
      console.warn('THREE 未暴露到 window,将使用手动投影矩阵');
    }
  }

  // === 1. 收集所有边线顶点(3D mm 坐标) ===
  const allEdges = [];
  scene.traverse(obj => {
    if (obj.type === 'LineSegments' || obj.type === 'Line') {
      const pos = obj.geometry.attributes.position;
      if (pos) {
        const matrix = obj.matrixWorld; // 世界坐标变换矩阵
        for (let i = 0; i < pos.count; i += 2) {
          const x1 = pos.getX(i), y1 = pos.getY(i), z1 = pos.getZ(i);
          const x2 = pos.getX(i + 1), y2 = pos.getY(i + 1), z2 = pos.getZ(i + 1);
          // 应用世界坐标变换
          const v1 = applyMatrix(matrix, x1, y1, z1);
          const v2 = applyMatrix(matrix, x2, y2, z2);
          allEdges.push({ v1, v2 });
        }
      }
    }
  });
  console.log(`=== 总边线数: ${allEdges.length} ===`);

  // === 2. 模型 bbox(用于设置正交相机范围) ===
  const modelBBox = v.mainModel.GetBoundingBox?.() || computeBBox(allEdges);
  console.log('=== 模型 BBox ===');
  console.log(`X: ${modelBBox.min.x.toFixed(1)} ~ ${modelBBox.max.x.toFixed(1)} (range=${(modelBBox.max.x - modelBBox.min.x).toFixed(1)})`);
  console.log(`Y: ${modelBBox.min.y.toFixed(1)} ~ ${modelBBox.max.y.toFixed(1)} (range=${(modelBBox.max.y - modelBBox.min.y).toFixed(1)})`);
  console.log(`Z: ${modelBBox.min.z.toFixed(1)} ~ ${modelBBox.max.z.toFixed(1)} (range=${(modelBBox.max.z - modelBBox.min.z).toFixed(1)})`);

  // === 3. 视图方向配置(与 viewer.html setCameraView 一致) ===
  const center = {
    x: (modelBBox.min.x + modelBBox.max.x) / 2,
    y: (modelBBox.min.y + modelBBox.max.y) / 2,
    z: (modelBBox.min.z + modelBBox.max.z) / 2
  };
  const size = Math.max(
    modelBBox.max.x - modelBBox.min.x,
    modelBBox.max.y - modelBBox.min.y,
    modelBBox.max.z - modelBBox.min.z
  );
  const distance = size * 2;

  const viewConfigs = {
    'front':  { eye: [center.x, center.y, center.z + distance], up: [0, 1, 0], label: '前视' },
    'back':   { eye: [center.x, center.y, center.z - distance], up: [0, 1, 0], label: '后视' },
    'left':   { eye: [center.x - distance, center.y, center.z], up: [0, 1, 0], label: '左视' },
    'right':  { eye: [center.x + distance, center.y, center.z], up: [0, 1, 0], label: '右视' },
    'top':    { eye: [center.x, center.y + distance, center.z], up: [0, 0, -1], label: '上视' },
    'bottom': { eye: [center.x, center.y - distance, center.z], up: [0, 0, 1], label: '下视' },
  };

  // === 4. 对每个视图投影边线到 2D ===
  console.log('\n=== 各视图投影结果 ===');

  for (const [viewName, cfg] of Object.entries(viewConfigs)) {
    // 计算投影方向和屏幕坐标系
    const dirX = cfg.eye[0] - center.x;
    const dirY = cfg.eye[1] - center.y;
    const dirZ = cfg.eye[2] - center.z;
    const dirLen = Math.sqrt(dirX * dirX + dirY * dirY + dirZ * dirZ);
    const dir = [dirX / dirLen, dirY / dirLen, dirZ / dirLen]; // 单位投影方向

    // up 向量(归一化)
    const upLen = Math.sqrt(cfg.up[0] ** 2 + cfg.up[1] ** 2 + cfg.up[2] ** 2);
    const up = [cfg.up[0] / upLen, cfg.up[1] / upLen, cfg.up[2] / upLen];

    // right = dir × up(叉积)
    const right = [
      dir[1] * up[2] - dir[2] * up[1],
      dir[2] * up[0] - dir[0] * up[2],
      dir[0] * up[1] - dir[1] * up[0]
    ];

    // 投影所有边线到 2D(用 right 和 up 作为屏幕 X/Y 轴)
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    let projectedCount = 0;
    let totalLength = 0;

    for (const edge of allEdges) {
      // 计算边线两端点相对于模型中心的偏移
      const dx1 = edge.v1[0] - center.x;
      const dy1 = edge.v1[1] - center.y;
      const dz1 = edge.v1[2] - center.z;
      const dx2 = edge.v2[0] - center.x;
      const dy2 = edge.v2[1] - center.y;
      const dz2 = edge.v2[2] - center.z;

      // 投影到屏幕坐标(点积 right 和 up)
      const sx1 = dx1 * right[0] + dy1 * right[1] + dz1 * right[2];
      const sy1 = dx1 * up[0] + dy1 * up[1] + dz1 * up[2];
      const sx2 = dx2 * right[0] + dy2 * right[1] + dz2 * right[2];
      const sy2 = dx2 * up[0] + dy2 * up[1] + dz2 * up[2];

      minX = Math.min(minX, sx1, sx2);
      minY = Math.min(minY, sy1, sy2);
      maxX = Math.max(maxX, sx1, sx2);
      maxY = Math.max(maxY, sy1, sy2);

      projectedCount++;
      totalLength += Math.sqrt((sx2 - sx1) ** 2 + (sy2 - sy1) ** 2);
    }

    const width = maxX - minX;
    const height = maxY - minY;
    console.log(`${cfg.label}(${viewName}): ${width.toFixed(1)} × ${height.toFixed(1)}  (${projectedCount} edges, avg_len=${(totalLength / projectedCount).toFixed(1)}mm)`);
  }

  console.log('\n=== 验证标准 ===');
  console.log('如果模型长轴沿 Z(1731mm):');
  console.log('  前视(沿-Z看): 应显示 X-Y 平面 → 宽≈350 × 高≈348 (小方块)');
  console.log('  右视(沿+X看): 应显示 Y-Z 平面 → 宽≈348 × 高≈1731 (高矩形)');
  console.log('  上视(沿+Y看): 应显示 X-Z 平面 → 宽≈350 × 高≈1731 (高矩形)');
  console.log('\n如果与上面不符,说明 viewer 的视图方向定义与 SolidWorks 不同,需调整 viewConfigs');

  // === 辅助函数 ===
  function applyMatrix(matrix, x, y, z) {
    // 应用 4x4 矩阵到 3D 点
    const e = matrix.elements;
    return [
      e[0] * x + e[4] * y + e[8] * z + e[12],
      e[1] * x + e[5] * y + e[9] * z + e[13],
      e[2] * x + e[6] * y + e[10] * z + e[14]
    ];
  }

  function computeBBox(edges) {
    let min = { x: Infinity, y: Infinity, z: Infinity };
    let max = { x: -Infinity, y: -Infinity, z: -Infinity };
    for (const edge of edges) {
      for (const v of [edge.v1, edge.v2]) {
        min.x = Math.min(min.x, v[0]);
        min.y = Math.min(min.y, v[1]);
        min.z = Math.min(min.z, v[2]);
        max.x = Math.max(max.x, v[0]);
        max.y = Math.max(max.y, v[1]);
        max.z = Math.max(max.z, v[2]);
      }
    }
    return { min, max };
  }
})();
